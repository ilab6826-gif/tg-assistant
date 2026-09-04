"""
Клиентский Telegram-бот: только трекер заказов через Mini App.

Ассистент (bot/main.py) — для владельца: запись заказов и смена статусов.
Этот бот — для клиентов: открывают Mini App, видят все свои заказы и получают
пуш-уведомления, когда владелец меняет статус через ассистента.
"""
import html
import logging
from typing import Optional
from urllib.parse import quote

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from bot import clients_service, config, referrals_service, reviews_service

logger = logging.getLogger(__name__)

client_bot = Bot(token=config.CLIENT_BOT_TOKEN) if config.CLIENT_BOT_TOKEN else None
client_dp = Dispatcher()

# Эмодзи для каждого этапа доставки (индекс = статус - 1).
_STATUS_EMOJI = ["🛒", "🏭", "🚚", "🛃", "🏙", "📮", "🎉"]

# Префикс полезной нагрузки реферальной ссылки: t.me/bot?start=ref_ABC123
_REF_PREFIX = "ref_"

# main.py подставляет сюда отправку сообщения владельцу — чтобы клиентский бот
# не импортировал ассистента (иначе циклический импорт).
notify_owner = None


async def _tell_owner(text: str, reply_chat_id: int = None, reply_username: str = "") -> None:
    if not notify_owner:
        logger.warning("Некому сообщить владельцу — обработчик не подключён.")
        return
    try:
        await notify_owner(
            text,
            reply_chat_id=reply_chat_id,
            reply_username=reply_username,
        )
    except Exception:
        logger.exception("Не удалось отправить сообщение владельцу")


def _mini_app_keyboard() -> Optional[ReplyKeyboardMarkup]:
    if not config.MINI_APP_URL:
        return None
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📦 Мои заказы", web_app=WebAppInfo(url=config.MINI_APP_URL))]],
        resize_keyboard=True,
    )


def _notify_keyboard(tracking_url: str = "") -> Optional[InlineKeyboardMarkup]:
    rows = []
    if config.MINI_APP_URL:
        rows.append([
            InlineKeyboardButton(text="📦 Открыть трекер", web_app=WebAppInfo(url=config.MINI_APP_URL))
        ])
    if tracking_url:
        rows.append([
            InlineKeyboardButton(text="🚚 Отследить посылку", url=tracking_url)
        ])
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _mini_app_inline_keyboard() -> Optional[InlineKeyboardMarkup]:
    return _notify_keyboard()


def _money(value) -> str:
    return f"{int(value):,}".replace(",", " ") + " ₽"


def referral_link(code: str) -> str:
    """Ссылка-приглашение. Пустая строка, если @username бота ещё неизвестен."""
    bot_username = clients_service.get_client_bot_username()
    if not bot_username or not code:
        return ""
    return f"https://t.me/{bot_username}?start={_REF_PREFIX}{code}"


def _share_keyboard(link: str) -> Optional[InlineKeyboardMarkup]:
    if not link:
        return None
    text = (
        f"Заказываю вещи из Китая через {config.BRAND_NAME} — все заказы видно в приложении. "
        f"По этой ссылке тебе дадут скидку {config.REFERRAL_FRIEND_BONUS} ₽ на первый заказ"
    )
    share_url = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(text, safe='')}"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📨 Поделиться с другом", url=share_url)]]
    )


def referral_text(username: str, chat_id: Optional[int] = None) -> str:
    """Текст блока приглашений для чата с ботом."""
    if not username:
        return (
            "🎁 Приглашай друзей и получай бонусы\n\n"
            "Но сначала задай @username в Telegram: без него я не смогу привязать "
            "приглашения к тебе.\nНастройки → Изменить профиль → Имя пользователя."
        )

    data = referrals_service.summary(username, chat_id)
    link = referral_link(data["code"])

    lines = [
        "🎁 Приглашай друзей",
        "",
        "Друг оформляет первый заказ — бонус получаете оба:",
        f"• тебе {_money(config.REFERRAL_BONUS)} на следующий заказ",
        f"• другу скидка {_money(config.REFERRAL_FRIEND_BONUS)} на первый",
        "",
    ]
    if link:
        lines.append("Твоя ссылка:")
        lines.append(link)
    else:
        lines.append(f"Твой код: {data['code']} — назови его менеджеру при заказе.")

    lines.append("")
    lines.append(
        f"Перешли по ссылке: {data['invited']} · "
        f"заказали: {data['rewarded']} · "
        f"твой бонус: {_money(data['bonus'])}"
    )
    return "\n".join(lines)


async def _apply_referral_start(payload: str, user, chat_id: int) -> str:
    """
    Засчитывает переход по реферальной ссылке. Возвращает текст для приветствия
    (или пустую строку, если приглашение не засчитано).
    """
    code = payload[len(_REF_PREFIX):].strip().upper()
    if not code or not user or not user.username:
        return ""

    # Приглашение имеет смысл только для нового человека: у своих клиентов
    # ссылка друга не должна перебивать историю заказов.
    if clients_service.exists(user.username):
        return ""

    referrer = referrals_service.record_invite(
        code=code,
        invitee_username=user.username,
        invitee_chat_id=chat_id,
        invitee_name=user.first_name or "",
    )
    if not referrer:
        return ""

    logger.info("Клиент @%s пришёл по приглашению @%s", user.username, referrer)

    referrer_chat_id = clients_service.get_chat_id(referrer)
    if referrer_chat_id and client_bot:
        who = f"@{user.username}"
        try:
            await client_bot.send_message(
                referrer_chat_id,
                f"👋 По твоей ссылке пришёл {who}.\n\n"
                f"Как только он оформит первый заказ, начислю тебе "
                f"{_money(config.REFERRAL_BONUS)} на следующую покупку.",
            )
        except Exception:
            logger.exception("Не удалось уведомить пригласившего @%s", referrer)

    await _tell_owner(
        f"🎁 Новый клиент по приглашению\n\n"
        f"@{user.username} пришёл по ссылке @{referrer}.\n"
        f"При первом заказе дай скидку {_money(config.REFERRAL_FRIEND_BONUS)} — я напомню."
    )

    return (
        f"🎁 Ты пришёл по приглашению @{referrer} — "
        f"скидка {_money(config.REFERRAL_FRIEND_BONUS)} на первый заказ уже за тобой. "
        "Менеджер учтёт её при оформлении.\n\n"
    )


@client_dp.message(CommandStart())
async def on_client_start(message: Message, command: CommandObject = None) -> None:
    user = message.from_user
    name = user.first_name if user and user.first_name else ""
    payload = (command.args or "").strip() if command else ""

    referral_note = ""
    if payload.startswith(_REF_PREFIX):
        try:
            referral_note = await _apply_referral_start(payload, user, message.chat.id)
        except Exception:
            logger.exception("Не удалось обработать реферальную ссылку %s", payload)

    if user and user.username:
        clients_service.register(user.username, message.chat.id, name)
        logger.info("Клиент @%s зарегистрирован (chat_id=%s)", user.username, message.chat.id)

    greeting = (
        f"Привет{', ' + name if name else ''}! "
        f"Это {config.BRAND_NAME} — сервис доставки товаров из Китая.\n\n"
        "Здесь ты можешь отслеживать все свои заказы: этап доставки, "
        "номер заказа и что именно в пути.\n\n"
    )
    greeting += referral_note

    if not user or not user.username:
        greeting += (
            "⚠️ У тебя не задан @username в Telegram — без него заказы не подтянутся автоматически.\n"
            "Настройки → Изменить профиль → Имя пользователя.\n\n"
        )

    keyboard = _mini_app_keyboard()
    if keyboard:
        await message.answer(
            greeting + "Нажми кнопку ниже, чтобы открыть трекер. "
            "А когда статус заказа изменится — пришлю уведомление сюда.\n\n"
            "И ещё: за приглашённых друзей я начисляю бонусы — команда /invite.",
            reply_markup=keyboard,
        )
    else:
        await message.answer(
            greeting + "⚠️ Трекер заказов скоро будет доступен — мы ещё настраиваем приложение."
        )


@client_dp.message(Command("invite"))
async def on_invite(message: Message) -> None:
    user = message.from_user
    username = user.username if user else ""
    if username:
        clients_service.register(username, message.chat.id, user.first_name or "")

    data = referrals_service.summary(username, message.chat.id) if username else {"code": ""}
    await message.answer(
        referral_text(username, message.chat.id),
        reply_markup=_share_keyboard(referral_link(data["code"])),
    )


_COMMENT_LIMIT = 1000


def _who(user) -> str:
    if user and user.username:
        return f"@{user.username}"
    if user and user.first_name:
        return user.first_name
    return "клиент"


def _is_owner(message: Message) -> bool:
    owner = clients_service.get_owner_chat_id()
    return bool(owner and message.from_user and message.from_user.id == owner)


async def _download_client_photo(file_id: str) -> bytes:
    file_info = await client_bot.get_file(file_id)
    downloaded = await client_bot.download_file(file_info.file_path)
    return downloaded.read()


async def _forward_to_owner(message: Message, note: str = "") -> bool:
    """
    Нативная пересылка Telegram: у владельца сообщение выглядит как
    «Переслано от: Иван», с исходным фото и подписью. Копию бот не собирает.
    """
    owner = clients_service.get_owner_chat_id()
    if not client_bot or not owner:
        return False

    try:
        forwarded = await client_bot.forward_message(
            chat_id=owner,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception:
        logger.exception("Не удалось переслать сообщение владельцу из чата %s", message.chat.id)
        return False

    username = message.from_user.username if message.from_user else ""
    clients_service.remember_forwarded(
        forwarded.message_id, message.chat.id, username or ""
    )
    if note:
        await _tell_owner(note, reply_chat_id=message.chat.id, reply_username=username or "")
    return True


async def _handle_owner_reply(message: Message) -> bool:
    """
    Владелец иногда отвечает в этом же чате реплаем на пересланное.
    True — сообщение уже обработано, клиентским его считать нельзя.
    """
    if not _is_owner(message):
        return False

    if message.reply_to_message:
        target = clients_service.get_forwarded(message.reply_to_message.message_id)
        if target:
            text = (message.text or message.caption or "").strip()
            if not text:
                await message.answer("Напиши текстом, что передать клиенту.")
                return True
            if await send_to_client(target["chat_id"], text):
                who = f"@{target['username']}" if target["username"] else "клиенту"
                await message.answer(f"📨 Ответ отправлен {who}.")
            else:
                await message.answer("⚠️ Не получилось доставить ответ.")
            return True

    await message.answer(
        "Чтобы ответить клиенту, сделай реплай на пересланное сообщение."
    )
    return True


async def _finish_review(
    message: Message,
    order_number: str,
    comment: str = "",
    photo: bytes = None,
    waiting_for_photo: bool = False,
) -> None:
    """Сохраняет часть отзыва и либо благодарит, либо просит фото."""
    if comment:
        reviews_service.save_comment(order_number, comment[:_COMMENT_LIMIT])
    if photo:
        reviews_service.save_photo(order_number, photo)
        reviews_service.cancel_expected_comment(message.chat.id)

    review = reviews_service.get(order_number) or {}
    rating = review.get("rating") or 0
    low = rating and rating <= reviews_service.LOW_RATING
    stars = "⭐" * rating if rating else "без оценки"
    who = _who(message.from_user)

    if waiting_for_photo:
        await message.answer("Текст принял. Теперь пришли фото заказа — прямо сюда, одним снимком.")
        return

    if low:
        await message.answer(
            "Спасибо. Передал владельцу лично — он свяжется с тобой и разберётся. В канал это не попадёт."
        )
    elif photo:
        await message.answer(
            "Спасибо! Если не против, покажем фото в канале — напиши, если нет."
        )
    else:
        await message.answer("Спасибо, этого достаточно 🙏")

    if low:
        note = (
            f"🔴 Жалоба по заказу {order_number} · {stars} от {who}\n"
            "В канал не публиковать. Ответь реплаем — передам клиенту."
        )
    else:
        note = (
            f"📷 Отзыв по заказу {order_number} · {stars} от {who}\n"
            "Сообщение переслал как есть — можно сразу в канал. "
            "Ответь реплаем, если нужно написать клиенту."
        )

    if photo:
        if not await _forward_to_owner(message, note=note):
            await _tell_owner(
                note,
                reply_chat_id=message.chat.id,
                reply_username=message.from_user.username if message.from_user else "",
            )
    else:
        await _tell_owner(
            note,
            reply_chat_id=message.chat.id,
            reply_username=message.from_user.username if message.from_user else "",
        )


_review_albums = set()


@client_dp.message(F.photo)
async def on_client_photo(message: Message) -> None:
    """Фото клиента: отзыв или просто сообщение — пересылаем владельцу как есть."""
    if await _handle_owner_reply(message):
        return

    user = message.from_user
    if user and user.username:
        clients_service.register(user.username, message.chat.id, user.first_name or "")

    order_number = reviews_service.expected_order(message.chat.id)
    if not order_number:
        if message.media_group_id and message.media_group_id in _review_albums:
            return
        delivered = await _forward_to_owner(message)
        if delivered:
            await message.answer("✅ Передал менеджеру, он скоро ответит здесь же.")
        else:
            await message.answer(
                "Сообщение получено, но менеджер сейчас недоступен. "
                "Напиши, пожалуйста, чуть позже."
            )
        return

    if message.media_group_id:
        if len(_review_albums) > 200:
            _review_albums.clear()
        _review_albums.add(message.media_group_id)

    try:
        photo = await _download_client_photo(message.photo[-1].file_id)
    except Exception:
        logger.exception("Не удалось скачать фото отзыва по заказу %s", order_number)
        await message.answer("Не получилось сохранить фото, пришли ещё раз, пожалуйста.")
        return

    await _finish_review(
        message,
        order_number,
        comment=(message.caption or "").strip(),
        photo=photo,
    )


@client_dp.message(F.text)
async def on_client_message(message: Message) -> None:
    """Любое сообщение клиента (кроме команд) пересылаем владельцу как есть."""
    if await _handle_owner_reply(message):
        return

    user = message.from_user
    text = message.text or ""

    if user and user.username:
        clients_service.register(user.username, message.chat.id, user.first_name or "")

    order_number = reviews_service.expected_order(message.chat.id)
    if order_number and text.strip():
        # Текст без фото: комментарий сохраняем, но просим снимок следом.
        await _finish_review(message, order_number, comment=text.strip(), waiting_for_photo=True)
        return

    delivered = await _forward_to_owner(message)
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


async def notify_status_change(username: str, order_number: str, product: str, new_status: int,
                               tracking: Optional[dict] = None) -> bool:
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
    track = tracking or {}

    lines = [
        f"Заказ <b>{html.escape(order_number)}</b> · обновление",
        "",
        _status_line(new_status, html.escape(label)),
        f"Этап {new_status} из {total}",
    ]
    if product:
        lines.append(f"\n{html.escape(product)}")
    if track.get("number"):
        carrier = html.escape(track.get("carrier_label") or "Трек")
        number = html.escape(track["number"])
        lines.append(f"\n🚚 {carrier} <code>{number}</code>")
    if new_status >= total:
        lines.append("\nЗаказ доставлен. Спасибо, что выбрал нас!")

    try:
        await client_bot.send_message(
            chat_id,
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=_notify_keyboard(track.get("url") or ""),
        )
    except Exception:
        logger.exception("Не удалось отправить уведомление клиенту @%s", username)
        return False
    return True


async def notify_tracking(username: str, order_number: str, product: str, tracking: dict) -> bool:
    """Пуш только про трек — когда статус уже «в доставке», а номер пришёл позже."""
    if not client_bot:
        return False

    chat_id = clients_service.get_chat_id(username)
    if not chat_id:
        return False

    number = (tracking or {}).get("number") or ""
    if not number:
        return False

    carrier = html.escape((tracking.get("carrier_label") or "Трек"))
    lines = [
        f"Заказ <b>{html.escape(order_number)}</b> · трек отслеживания",
        "",
        f"🚚 {carrier} <code>{html.escape(number)}</code>",
    ]
    if product:
        lines.append(f"\n{html.escape(product)}")

    try:
        await client_bot.send_message(
            chat_id,
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=_notify_keyboard(tracking.get("url") or ""),
        )
    except Exception:
        logger.exception("Не удалось отправить трек клиенту @%s", username)
        return False
    return True


def _rating_keyboard(order_number: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=f"{value}⭐", callback_data=f"rev:{order_number}:{value}")
            for value in range(1, 6)
        ]]
    )


def _review_after_rating_keyboard(order_number: str) -> InlineKeyboardMarkup:
    """Кнопка открывает личку владельца — отзыв приходит как обычное сообщение от клиента."""
    username = clients_service.get_owner_username()
    rows = []
    if username:
        rows.append([
            InlineKeyboardButton(text="📸 Написать отзыв", url=f"https://t.me/{username}")
        ])
    rows.append([
        InlineKeyboardButton(text="Позже", callback_data=f"revskip:{order_number}")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_review_request(chat_id: int, order_number: str, product: str = "") -> None:
    """
    Просит оценить доставленный заказ. Вызывается планировщиком через
    REVIEW_DELAY_HOURS после перехода в последний статус.
    """
    if not client_bot:
        return

    review = reviews_service.get(order_number)
    if review and review.get("rating"):
        return  # клиент уже оценил — второй раз не спрашиваем

    lines = [
        f"Как всё прошло с заказом <b>{html.escape(order_number)}</b>?",
        "",
    ]
    if product:
        lines.append(f"{html.escape(product)}\n")
    lines.append("Поставь оценку — и следом пришли фото заказа мне в личку, с парой слов в подписи.")

    try:
        await client_bot.send_message(
            chat_id,
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=_rating_keyboard(order_number),
        )
    except Exception:
        logger.exception("Не удалось запросить отзыв по заказу %s", order_number)


@client_dp.callback_query(F.data.startswith("rev:"))
async def on_review_rating(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer()
        return

    order_number = parts[1]
    rating = max(1, min(5, int(parts[2])))
    reviews_service.save_rating(order_number, rating)
    reviews_service.cancel_expected_comment(callback.message.chat.id)

    stars = "⭐" * rating
    owner_username = clients_service.get_owner_username()
    low = rating <= reviews_service.LOW_RATING

    if owner_username:
        if low:
            follow_up = (
                "Извини, что не дотянули. Напиши мне в личку, что пошло не так, "
                f"и прикрепи фото заказа {order_number} — разберёмся лично, в канал это не попадёт."
            )
        else:
            follow_up = (
                f"Спасибо! Нажми кнопку ниже и пришли мне фото заказа {order_number} "
                "с парой слов в подписи. Если не против — покажем в канале."
            )
    else:
        if low:
            follow_up = (
                "Извини, что не дотянули. Пришли сюда фото заказа и в подписи напиши, "
                "что пошло не так — передам владельцу лично."
            )
        else:
            follow_up = (
                "Спасибо! Пришли сюда фото заказа и напиши пару слов в подписи."
            )
        reviews_service.expect_comment(callback.message.chat.id, order_number)

    try:
        await callback.message.edit_text(
            f"Заказ {order_number}\n\nТвоя оценка: {stars}\n\n{follow_up}",
            reply_markup=_review_after_rating_keyboard(order_number),
        )
    except Exception:
        logger.exception("Не удалось обновить сообщение с оценкой заказа %s", order_number)

    user = callback.from_user
    who = _who(user)
    prefix = "🔴 Низкая оценка" if low else "⭐ Новая оценка"
    hint = (
        "\nКлиент сейчас напишет тебе в личку. Фото придёт как обычное сообщение — "
        "можно сразу переслать в канал."
        if owner_username
        else "\n⚠️ Не знаю твой @username. Напиши ассистенту что угодно — запомню, "
        "и кнопка «Написать отзыв» начнёт открывать твою личку."
    )
    await _tell_owner(f"{prefix} по заказу {order_number}\n\n{stars} ({rating} из 5) от {who}{hint}")

    await callback.answer("Спасибо за оценку!")


@client_dp.callback_query(F.data.startswith("revskip:"))
async def on_review_skip(callback: CallbackQuery) -> None:
    order_number = (callback.data or "").split(":", 1)[1]
    reviews_service.cancel_expected_comment(callback.message.chat.id)

    review = reviews_service.get(order_number) or {}
    stars = "⭐" * (review.get("rating") or 0)
    try:
        await callback.message.edit_text(
            f"Заказ {order_number}\n\nТвоя оценка: {stars}\n\nСпасибо, этого достаточно 🙏"
        )
    except Exception:
        logger.exception("Не удалось убрать кнопку отзыва по заказу %s", order_number)
    await callback.answer()


async def notify_referral_reward(referrer_username: str, invitee_username: str) -> bool:
    """Сообщает пригласившему, что друг оформил первый заказ и бонус начислен."""
    if not client_bot:
        return False

    chat_id = clients_service.get_chat_id(referrer_username)
    if not chat_id:
        return False

    data = referrals_service.summary(referrer_username, chat_id)
    who = f"@{invitee_username}" if invitee_username else "твой друг"
    try:
        await client_bot.send_message(
            chat_id,
            f"🎁 {who} оформил первый заказ — тебе начислено "
            f"{_money(config.REFERRAL_BONUS)} на следующую покупку.\n\n"
            f"Всего накоплено: {_money(data['bonus'])}. "
            "Скажи менеджеру при оформлении, и он учтёт бонус.",
            reply_markup=_mini_app_inline_keyboard(),
        )
    except Exception:
        logger.exception("Не удалось сообщить о бонусе клиенту @%s", referrer_username)
        return False
    return True


async def notify_friend_discount(invitee_username: str, order_number: str) -> bool:
    """Напоминает приглашённому, что скидка на первый заказ за ним."""
    if not client_bot:
        return False
    chat_id = clients_service.get_chat_id(invitee_username)
    if not chat_id:
        return False
    try:
        await client_bot.send_message(
            chat_id,
            f"🎁 Заказ {order_number} записан. Скидка "
            f"{_money(config.REFERRAL_FRIEND_BONUS)} за приглашение друга "
            "уже за тобой — менеджер учтёт её при расчёте.",
            reply_markup=_mini_app_inline_keyboard(),
        )
    except Exception:
        logger.exception("Не удалось напомнить о скидке клиенту @%s", invitee_username)
        return False
    return True


async def start_client_polling() -> None:
    if not client_bot:
        logger.warning("CLIENT_BOT_TOKEN не задан — клиентский бот не запущен.")
        return

    # Свой @username нужен для реферальных ссылок. Спрашиваем один раз при
    # старте и запоминаем, чтобы API мини-аппа мог собрать ссылку без запроса.
    try:
        me = await client_bot.get_me()
        clients_service.remember_client_bot_username(me.username or "")
    except Exception:
        logger.exception("Не удалось узнать @username клиентского бота")

    logger.info("Клиентский бот запущен, ожидаю сообщения...")
    await client_dp.start_polling(client_bot)
