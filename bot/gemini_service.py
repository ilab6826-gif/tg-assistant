"""
Общение с Gemini API.

Ключевая идея: для каждого сообщения пользователя Gemini решает,
что нужно сделать - создать напоминание, записать заказ, или просто
ответить как обычный ассистент. Для этого используется function calling:
Gemini сам выбирает вызвать нужный "инструмент" с нужными аргументами.
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import google.generativeai as genai

from bot import channel_analyzer, config

genai.configure(api_key=config.GEMINI_API_KEY, transport="rest")

logger = logging.getLogger(__name__)

TOOLS = [
    {
        "function_declarations": [
            {
                "name": "create_reminder",
                "description": (
                    "Создать напоминание пользователю на конкретную дату и время. "
                    "Используй, когда пользователь просит напомнить о чём-то "
                    "('напомни мне...', 'не забыть...', 'через час напомни...')."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "remind_at": {
                            "type": "string",
                            "description": (
                                "Дата и время напоминания в формате ISO 8601 "
                                "(YYYY-MM-DDTHH:MM:SS), в часовом поясе пользователя."
                            ),
                        },
                        "text": {
                            "type": "string",
                            "description": "О чём именно напомнить, коротко и по делу.",
                        },
                    },
                    "required": ["remind_at", "text"],
                },
            },
            {
                "name": "log_order",
                "description": (
                    "Сохранить новый заказ клиента в Google-таблицу. Используй, когда "
                    "пользователь описывает заказ клиента (кто заказал, что, размер, цвет)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "username": {
                            "type": "string",
                            "description": "Юзернейм клиента в Telegram (с @), если указан, иначе пустая строка.",
                        },
                        "product": {"type": "string", "description": "Название товара."},
                        "size": {"type": "string", "description": "Размер, если указан, иначе пустая строка."},
                        "color": {"type": "string", "description": "Цвет, если указан, иначе пустая строка."},
                        "full_name": {
                            "type": "string",
                            "description": "ФИО клиента, если указано, иначе пустая строка.",
                        },
                    },
                    "required": ["product"],
                },
            },
        ]
    }
]

SYSTEM_PROMPT = """Ты — личный ассистент владельца бизнеса по перепродаже товаров из Китая.
Твои задачи:
1. Если пользователь просит напомнить о чём-то — вызови create_reminder.
2. Если пользователь описывает новый заказ клиента — вызови log_order.
3. Во всех остальных случаях — просто ответь как полезный, дружелюбный ассистент,
   кратко и по делу, без лишней воды.

Есть и третья возможность, которая обрабатывается отдельно от тебя (не через
tool calling): если пользователь присылает ссылку на Telegram-канал (t.me/...)
или юзернейм канала, бот автоматически разбирает его посты и присылает анализ
конкурента/рекламной площадки. Если пользователь спрашивает, что ты умеешь —
обязательно упомяни и эту возможность тоже, наряду с напоминаниями и заказами.

Текущая дата и время пользователя: {now}.
Если пользователь называет время без даты ("в 12:00", "через час") — считай, что это
ближайшее будущее относительно текущего времени.
"""


def _now_str() -> str:
    tz = ZoneInfo(config.TIMEZONE)
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S (%A)")


def process_message(user_text: str, conversation_history: list = None) -> dict:
    """
    Отправляет сообщение в Gemini и возвращает результат в виде словаря:
    {"type": "reminder", "remind_at": ..., "text": ...}
    {"type": "order", "username": ..., "product": ..., ...}
    {"type": "reply", "text": "..."}

    conversation_history: предыдущие реплики чата в хронологическом порядке
    [{"role": "user"|"model", "text": "..."}, ...] — используется как контекст,
    чтобы Gemini "помнил" предыдущую переписку.
    """
    model = genai.GenerativeModel(
        model_name=config.GEMINI_MODEL,
        system_instruction=SYSTEM_PROMPT.format(now=_now_str()),
        tools=TOOLS,
    )

    contents = [
        {"role": msg["role"], "parts": [msg["text"]]}
        for msg in (conversation_history or [])
    ]
    contents.append({"role": "user", "parts": [user_text]})

    response = model.generate_content(contents)

    parts = response.candidates[0].content.parts
    for part in parts:
        function_call = getattr(part, "function_call", None)
        if function_call and function_call.name:
            args = dict(function_call.args)
            if function_call.name == "create_reminder":
                return {"type": "reminder", **args}
            if function_call.name == "log_order":
                return {"type": "order", **args}

    text_parts = [part.text for part in parts if getattr(part, "text", "")]
    return {"type": "reply", "text": "\n".join(text_parts).strip() or "Не понял вопрос, уточни, пожалуйста."}


def transcribe_voice(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    """
    Расшифровывает голосовое сообщение в текст через Gemini (аудио подаётся
    как обычный input наравне с текстом). Возвращает только сам текст.
    """
    model = genai.GenerativeModel(model_name=config.GEMINI_MODEL)
    response = model.generate_content(
        [
            {"mime_type": mime_type, "data": audio_bytes},
            "Расшифруй это голосовое сообщение дословно, на языке говорящего. "
            "В ответе верни только сам расшифрованный текст, без кавычек и пояснений.",
        ]
    )
    return response.text.strip()


def _own_channel_context() -> str:
    """
    Подгружает свежие посты собственного канала (OWN_CHANNEL_USERNAME) для сравнения.
    Если не получилось (канал приватный, Telegram отдал ошибку и т.п.) — откатывается
    на статичное текстовое описание OWN_CHANNEL_DESCRIPTION из .env.
    """
    try:
        own_posts = channel_analyzer.fetch_channel_posts(config.OWN_CHANNEL_USERNAME)
        logger.info(
            "Подгрузил свежие посты собственного канала @%s для сравнения (%d символов)",
            config.OWN_CHANNEL_USERNAME,
            len(own_posts),
        )
        return f'Реальные последние посты моего канала @{config.OWN_CHANNEL_USERNAME}:\n{own_posts}'
    except Exception:
        logger.warning(
            "Не удалось загрузить посты собственного канала @%s, "
            "использую запасное текстовое описание из .env",
            config.OWN_CHANNEL_USERNAME,
            exc_info=True,
        )
        return f'Моё описание своего канала (не удалось загрузить актуальные посты):\n"{config.OWN_CHANNEL_DESCRIPTION}"'


def analyze_channel(channel_posts_text: str, channel_name: str) -> str:
    """
    Анализирует посты стороннего Telegram-канала в сравнении с собственным каналом
    и возвращает текстовый разбор (плюсы/минусы).
    """
    own_channel_context = _own_channel_context()

    prompt = f"""Проанализируй чужой Telegram-канал "{channel_name}" (конкурент или рекламная площадка)
в сравнении с моим собственным каналом.

Посты канала "{channel_name}":
---
{channel_posts_text}
---

{own_channel_context}

Дай краткий структурированный разбор именно канала "{channel_name}" (не моего):
1. Чем занимается канал "{channel_name}" / его позиционирование
2. Сильные стороны канала "{channel_name}" (кратко, 3-5 пунктов)
3. Слабые стороны канала "{channel_name}" (кратко, 3-5 пунктов)
4. Мои плюсы и минусы (моего канала) на фоне канала "{channel_name}"
5. Если канал "{channel_name}" может быть рекламной площадкой — стоит ли рассмотреть его для рекламы и почему

Отвечай кратко и по делу, без длинных вступлений."""

    model = genai.GenerativeModel(model_name=config.GEMINI_MODEL)
    response = model.generate_content(prompt)
    return response.text.strip()
