"""
Общение с Gemini API.

Ключевая идея: для каждого сообщения пользователя Gemini решает,
что нужно сделать - создать напоминание, записать заказ, или просто
ответить как обычный ассистент. Для этого используется function calling:
Gemini сам выбирает вызвать нужный "инструмент" с нужными аргументами.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import google.generativeai as genai

from bot import config

genai.configure(api_key=config.GEMINI_API_KEY, transport="rest")

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

Текущая дата и время пользователя: {now}.
Если пользователь называет время без даты ("в 12:00", "через час") — считай, что это
ближайшее будущее относительно текущего времени.
"""


def _now_str() -> str:
    tz = ZoneInfo(config.TIMEZONE)
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S (%A)")


def process_message(user_text: str) -> dict:
    """
    Отправляет сообщение в Gemini и возвращает результат в виде словаря:
    {"type": "reminder", "remind_at": ..., "text": ...}
    {"type": "order", "username": ..., "product": ..., ...}
    {"type": "reply", "text": "..."}
    """
    model = genai.GenerativeModel(
        model_name=config.GEMINI_MODEL,
        system_instruction=SYSTEM_PROMPT.format(now=_now_str()),
        tools=TOOLS,
    )
    response = model.generate_content(user_text)

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


def analyze_channel(channel_posts_text: str, channel_name: str) -> str:
    """
    Анализирует посты стороннего Telegram-канала в сравнении с описанием
    собственного канала и возвращает текстовый разбор (плюсы/минусы).
    """
    prompt = f"""Вот последние посты Telegram-канала "{channel_name}" (конкурент или рекламная площадка):

---
{channel_posts_text}
---

Моё описание своего канала:
"{config.OWN_CHANNEL_DESCRIPTION}"

Проанализируй этот канал и дай краткий структурированный разбор:
1. Чем занимается канал / его позиционирование
2. Сильные стороны (кратко, 3-5 пунктов)
3. Слабые стороны (кратко, 3-5 пунктов)
4. Мои плюсы и минусы на фоне этого канала
5. Если это может быть рекламной площадкой — стоит ли рассмотреть для рекламы и почему

Отвечай кратко и по делу, без длинных вступлений."""

    model = genai.GenerativeModel(model_name=config.GEMINI_MODEL)
    response = model.generate_content(prompt)
    return response.text.strip()
