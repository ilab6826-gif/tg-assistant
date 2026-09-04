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

# Описания этапов для Gemini собираются из config.ORDER_STATUSES, чтобы при
# правке списка этапов не нужно было синхронизировать текст в двух местах.
_STATUS_COUNT = len(config.ORDER_STATUSES)
_STATUS_LIST = ", ".join(
    f"{i} - {label}" for i, label in enumerate(config.ORDER_STATUSES, start=1)
)

# Один товар внутри заказа — схема общая для создания заказа и дозаказа.
_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "product": {"type": "string", "description": "Название товара."},
        "size": {"type": "string", "description": "Размер, если указан, иначе пустая строка."},
        "color": {"type": "string", "description": "Цвет, если указан, иначе пустая строка."},
        "cost_price": {
            "type": "number",
            "description": (
                "Во сколько этот товар обошёлся тебе (закупка), если названо. "
                "Например «закупка 4000» или «взял за 4000». 0, если не указано."
            ),
        },
        "sale_price": {
            "type": "number",
            "description": (
                "Сколько платит клиент за этот товар (продажа), если названо. "
                "Например «продал за 7500». 0, если не указано."
            ),
        },
    },
    "required": ["product"],
}

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
                    "пользователь описывает заказ клиента (кто заказал, что, размер, цвет). "
                    "В одном заказе может быть сразу несколько товаров — тогда перечисли "
                    "их все в items, а не создавай несколько заказов."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "username": {
                            "type": "string",
                            "description": "Юзернейм клиента в Telegram (с @), если указан, иначе пустая строка.",
                        },
                        "full_name": {
                            "type": "string",
                            "description": "ФИО клиента, если указано, иначе пустая строка.",
                        },
                        "items": {
                            "type": "array",
                            "description": (
                                "Товары заказа. Один элемент на каждый товар: «кроссовки Nike 42 "
                                "чёрные и куртку Stone Island M» — это два элемента."
                            ),
                            "items": _ITEM_SCHEMA,
                        },
                    },
                    "required": ["items"],
                },
            },
            {
                "name": "add_items_to_order",
                "description": (
                    "Добавить товары в уже существующий заказ по его номеру. Используй, когда "
                    "пользователь дозаказывает: «в заказ A1042 добавь ещё кепку», "
                    "«к A1042 плюс футболка L белая за 2000»."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_number": {
                            "type": "string",
                            "description": "Номер заказа, например 'A1042'.",
                        },
                        "items": {
                            "type": "array",
                            "description": "Товары, которые нужно добавить в этот заказ.",
                            "items": _ITEM_SCHEMA,
                        },
                    },
                    "required": ["order_number", "items"],
                },
            },
            {
                "name": "change_order_status",
                "description": (
                    "Изменить статус существующего заказа по его номеру. Используй, когда "
                    "пользователь пишет что-то вроде 'статус A1042 = 3' или "
                    "'заказ B2087 передан в доставку' — во втором случае сопоставь "
                    f"формулировку с одним из {_STATUS_COUNT} этапов и передай нужное число."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_number": {
                            "type": "string",
                            "description": "Номер заказа, например 'A1042'.",
                        },
                        "new_status": {
                            "type": "integer",
                            "description": (
                                f"Новый статус, число от 1 до {_STATUS_COUNT}: {_STATUS_LIST}."
                            ),
                        },
                        "tracking_number": {
                            "type": "string",
                            "description": (
                                "Трек-номер последней мили, если пользователь назвал его "
                                "вместе со сменой статуса. Например «1234567890». "
                                "Пустая строка, если трека нет."
                            ),
                        },
                        "carrier": {
                            "type": "string",
                            "description": (
                                "Служба доставки, если названа: СДЭК, Яндекс, Почта России, "
                                "DPD, Boxberry. Пустая строка, если не названа."
                            ),
                        },
                    },
                    "required": ["order_number", "new_status"],
                },
            },
            {
                "name": "set_order_tracking",
                "description": (
                    "Записать трек-номер последней мили (СДЭК, Яндекс, Почта России и т.д.) "
                    "для существующего заказа. Используй, когда пользователь пишет "
                    "«трек A1042 СДЭК 1234567890», «A1042 отправил СДЭКом 123», "
                    "«трек-номер B2087 123456». Если заказ ещё не на этапе "
                    "«передан в доставку», статус поднимется до него автоматически."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_number": {
                            "type": "string",
                            "description": "Номер заказа, например 'A1042'.",
                        },
                        "tracking_number": {
                            "type": "string",
                            "description": "Сам номер отслеживания, без названия службы.",
                        },
                        "carrier": {
                            "type": "string",
                            "description": (
                                "Служба доставки: СДЭК, Яндекс, Почта России, DPD, Boxberry. "
                                "Пустая строка, если пользователь её не назвал."
                            ),
                        },
                    },
                    "required": ["order_number", "tracking_number"],
                },
            },
            {
                "name": "change_orders_status_bulk",
                "description": (
                    "Изменить статус сразу у пачки заказов. Используй, когда пользователь "
                    "говорит про группу заказов: «все заказы со статусом 2 переведи в 3», "
                    "«всё что на складе в Китае — отправил в Москву», "
                    "«A1042, B2087 и C3011 переведи на 4»."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "new_status": {
                            "type": "integer",
                            "description": (
                                f"Новый статус, число от 1 до {_STATUS_COUNT}: {_STATUS_LIST}."
                            ),
                        },
                        "from_status": {
                            "type": "integer",
                            "description": (
                                f"Текущий статус заказов, которые нужно перевести (1-{_STATUS_COUNT}). "
                                "Заполняй, когда пользователь говорит «все со статусом X». "
                                "0, если он вместо этого перечислил номера заказов."
                            ),
                        },
                        "order_numbers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Список номеров заказов, если пользователь перечислил их явно. "
                                "Пустой список, если он указал текущий статус."
                            ),
                        },
                    },
                    "required": ["new_status"],
                },
            },
            {
                "name": "find_orders",
                "description": (
                    "Найти заказы и показать их состояние. Используй, когда пользователь "
                    "спрашивает про заказы: «что там с A1042», «покажи заказы @ivanov», "
                    "«какие заказы у Иванова», «найди заказ на кроссовки»."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Что искать: номер заказа, @юзернейм клиента, ФИО или название товара."
                            ),
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "show_stuck_orders",
                "description": (
                    "Показать заказы, которые давно висят на одном этапе. Используй на вопросы "
                    "вида «что зависло», «какие заказы застряли», «что давно не двигалось»."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "days": {
                            "type": "integer",
                            "description": "Сколько дней заказ должен стоять без движения. По умолчанию 10.",
                        },
                    },
                },
            },
            {
                "name": "show_active_orders",
                "description": (
                    "Показать, сколько сейчас активных заказов (ещё не доставлены) и "
                    "расклад по этапам. Используй на вопросы: «сколько активных заказов», "
                    "«сколько заказов в работе», «сколько сейчас заказов», «активные заказы»."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]
    }
]

SYSTEM_PROMPT = """Ты — личный ассистент владельца бизнеса по перепродаже товаров из Китая.
Твои задачи:
1. Если пользователь просит напомнить о чём-то — вызови create_reminder.
2. Если пользователь описывает новый заказ клиента — вызови log_order. В одном
   заказе может быть несколько товаров: перечисли их все в items одним вызовом.
3. Если он дозаказывает товары в существующий заказ по номеру — add_items_to_order.
4. Если пользователь просит изменить статус уже существующего заказа по номеру
   (например «статус A1042 = 3» или «B2087 передан в доставку») — вызови
   change_order_status. Если в том же сообщении назван трек последней мили
   («в доставку, трек СДЭК 123…») — передай tracking_number и carrier туда же.
5. Если речь про группу заказов сразу («все со статусом 2 переведи в 3»,
   «A1042 и B2087 на 4») — вызови change_orders_status_bulk.
6. Если пользователь спрашивает про заказы («что с A1042», «заказы @ivanov») —
   вызови find_orders.
7. Если спрашивает, что зависло или застряло — вызови show_stuck_orders.
8. Если спрашивает, сколько сейчас активных / в работе заказов — show_active_orders.
9. Если даёт трек последней мили без смены статуса («трек A1042 СДЭК 123…»,
   «A1042 отправил СДЭКом») — вызови set_order_tracking.
10. Во всех остальных случаях — просто ответь как полезный, дружелюбный ассистент,
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


def _to_python(value):
    """
    Аргументы функции приходят от Gemini в proto-обёртках. Для вложенных
    структур (список товаров) их нужно развернуть в обычные dict и list.
    """
    if isinstance(value, (str, bytes, int, float, bool)) or value is None:
        return value
    if hasattr(value, "items"):
        return {key: _to_python(item) for key, item in value.items()}
    if hasattr(value, "__iter__"):
        return [_to_python(item) for item in value]
    return value


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
    status_args = None
    tracking_args = None
    other = None
    for part in parts:
        function_call = getattr(part, "function_call", None)
        if not (function_call and function_call.name):
            continue
        args = _to_python(function_call.args)
        if function_call.name == "change_order_status":
            status_args = args
        elif function_call.name == "set_order_tracking":
            tracking_args = args
        elif other is None:
            if function_call.name == "create_reminder":
                other = {"type": "reminder", **args}
            elif function_call.name == "log_order":
                other = {"type": "order", **args}
            elif function_call.name == "add_items_to_order":
                other = {"type": "add_items", **args}
            elif function_call.name == "change_orders_status_bulk":
                other = {"type": "change_status_bulk", **args}
            elif function_call.name == "find_orders":
                other = {"type": "find_orders", **args}
            elif function_call.name == "show_stuck_orders":
                other = {"type": "stuck_orders", **args}
            elif function_call.name == "show_active_orders":
                other = {"type": "active_orders"}

    if status_args is not None:
        if tracking_args:
            if not status_args.get("tracking_number"):
                status_args["tracking_number"] = tracking_args.get("tracking_number", "")
            if not status_args.get("carrier"):
                status_args["carrier"] = tracking_args.get("carrier", "")
        return {"type": "change_status", **status_args}
    if tracking_args is not None:
        return {"type": "set_tracking", **tracking_args}
    if other is not None:
        return other

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
