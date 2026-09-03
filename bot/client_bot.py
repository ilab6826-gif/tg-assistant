"""
Клиентский Telegram-бот: только трекер заказов через Mini App.

Ассистент (bot/main.py) — для владельца: запись заказов и смена статусов.
Этот бот — для клиентов: открывают Mini App, видят все свои заказы и получают
пуш-уведомления, когда владелец меняет статус через ассистента.
"""
import html
import logging
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from bot import clients_service, config

logger = logging.getLogger(__name__)

client_bot = Bot(token=config.CLIENT_BOT_TOKEN) if config.CLIENT_BOT_TOKEN else None
client_dp = Dispatcher()

# Эмодзи для каждого этапа доставки (индекс = статус - 1).
_STATUS_EMOJI = ["🛒", "🏭", "🚚", "🛃", "🏙", "📮", "🎉"]


def _mini_app_keyboard() -> Optional[ReplyKeyboardMarkup]:
    if not config.MINI_APP_URL:
        return None
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📦 Мои заказы", web_app=WebAppInfo(url=config.MINI_APP_URL))]],
        resize_keyboard=True,
    )


def _mini_app_inline_keyboard() -> Optional[InlineKeyboardMarkup]:
    if not config.MINI_APP_URL:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📦 Открыть трекер", web_app=WebAppInfo(url=config.MINI_APP_URL))]
        ]
    )


@client_dp.message(CommandStart())
async def on_client_start(message: Message) -> None:
    user = message.from_user
    name = user.first_name if user and user.first_name else ""

    if user and user.username:
        clients_service.register(user.username, message.chat.id, name)
        logger.info("Клиент @%s зарегистрирован (chat_id=%s)", user.username, message.chat.id)

    greeting = (
        f"Привет{', ' + name if name else ''}! "
        f"Это {config.BRAND_NAME} — сервис доставки товаров из Китая.\n\n"
        "Здесь ты можешь отслеживать все свои заказы: этап доставки, "
        "номер заказа и что именно в пути.\n\n"
    )

    if not user or not user.username:
        greeting += (
            "⚠️ У тебя не задан @username в Telegram — без него заказы не подтянутся автоматически.\n"
            "Настройки → Изменить профиль → Имя пользователя.\n\n"
        )

    keyboard = _mini_app_keyboard()
    if keyboard:
        await message.answer(
            greeting + "Нажми кнопку ниже, чтобы открыть трекер. "
            "А когда статус заказа изменится — пришлю уведомление сюда.",
            reply_markup=keyboard,
        )
    else:
        await message.answer(
            greeting + "⚠️ Трекер заказов скоро будет доступен — мы ещё настраиваем приложение."
        )


# main.py подставляет сюда функцию, которая пересылает сообщение владельцу.
# Через callback, чтобы клиентский бот не зависел от ассистента (иначе циклический импорт).
forward_to_owner = None


@client_dp.message(F.text | F.caption)
async def on_client_message(message: Message) -> None:
    """Любое сообщение клиента (кроме команд) пересылаем владельцу в ассистент."""
    user = message.from_user
    text = message.text or message.caption or ""

    if user and user.username:
        clients_service.register(user.username, message.chat.id, user.first_name or "")

    if not forward_to_owner:
        logger.warning("Некому переслать сообщение клиента — владелец не определён.")
        await message.answer(
            "Сообщение получено, но менеджер сейчас недоступен. "
            "Напиши, пожалуйста, чуть позже."
        )
        return

    delivered = await forward_to_owner(
        chat_id=message.chat.id,
        username=user.username if user else "",
        first_name=user.first_name if user else "",
        text=text,
    )

    if delivered:
        await message.answer("✅ Передал менеджеру, он скоро ответит здесь же.")
    else:
        await message.answer(
            "Сообщение получено, но менеджер сейчас недоступен. "
            "Напиши, пожалуйста, чуть позже."
        )


async def send_to_client(chat_id: int, text: str) -> bool:
    """Отправляет клиенту ответ владельца. Возвращает False, если не доставлено."""
    if not client_bot:
        return False
    try:
        await client_bot.send_message(chat_id, f"💬 Сообщение от менеджера:\n\n{text}")
    except Exception:
        logger.exception("Не удалось отправить ответ клиенту в чат %s", chat_id)
        return False
    return True


def _status_line(status: int, label: str) -> str:
    emoji = _STATUS_EMOJI[status - 1] if 1 <= status <= len(_STATUS_EMOJI) else "📦"
    return f"{emoji} <b>{label}</b>"


async def notify_status_change(username: str, order_number: str, product: str, new_status: int) -> bool:
    """
    Присылает клиенту пуш о новом статусе заказа.
    Возвращает False, если бот не настроен или клиент ещё не открыл диалог с ботом.
    """
    if not client_bot:
        return False

    chat_id = clients_service.get_chat_id(username)
    if not chat_id:
        return False

    total = len(config.ORDER_STATUSES)
    label = config.ORDER_STATUSES[new_status - 1] if 1 <= new_status <= total else ""

    lines = [
        f"Заказ <b>{html.escape(order_number)}</b> · обновление",
        "",
        _status_line(new_status, html.escape(label)),
        f"Этап {new_status} из {total}",
    ]
    if product:
        lines.append(f"\n{html.escape(product)}")
    if new_status >= total:
        lines.append("\nЗаказ доставлен. Спасибо, что выбрал нас!")

    try:
        # HTML, поэтому номер и название товара из таблицы экранируем.
        await client_bot.send_message(
            chat_id,
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=_mini_app_inline_keyboard(),
        )
    except Exception:
        logger.exception("Не удалось отправить уведомление клиенту @%s", username)
        return False
    return True


async def start_client_polling() -> None:
    if not client_bot:
        logger.warning("CLIENT_BOT_TOKEN не задан — клиентский бот не запущен.")
        return
    logger.info("Клиентский бот запущен, ожидаю сообщения...")
    await client_dp.start_polling(client_bot)
