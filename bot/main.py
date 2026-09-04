import asyncio
import logging
import re
import threading
from typing import Optional

import uvicorn
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message, ReplyKeyboardRemove

from bot import (
    api,
    channel_analyzer,
    client_bot,
    clients_service,
    config,
    gemini_service,
    memory_service,
    photo_service,
    referrals_service,
    reviews_service,
    scheduler,
    sheets_service,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Последний созданный заказ в каждом чате — чтобы фото без номера цеплялось к нему.
_last_order_number = {}

def _remember_owner(message: Message) -> None:
    if clients_service.remember_owner_chat_id(message.chat.id):
        logger.info("Запомнил чат владельца: %s", message.chat.id)
    if message.from_user and message.from_user.username:
        clients_service.remember_owner_username(message.from_user.username)


@dp.message(CommandStart())
async def on_start(message: Message) -> None:
    _remember_owner(message)
    await message.answer(
        "Привет! Я твой личный ассистент. Умею:\n\n"
        "📌 Напоминать о задачах — просто напиши, например:\n"
        "«напомни завтра в 12:00 обработать заказ»\n\n"
        "📦 Записывать заказы в таблицу — опиши заказ свободным текстом,\n"
        "в одном заказе может быть сразу много товаров:\n"
        "«@ivanov заказал кроссовки Nike 42 чёрные за 7500 и куртку\n"
        "Stone Island M синюю за 12000, Иванов Иван, закупка 9000»\n\n"
        "➕ Дозаказ — «в заказ A1042 добавь ещё кепку New Era за 3000»\n\n"
        "🔄 Менять статус заказа — «статус A1042 = 3»\n"
        "   1 — выкуплен · 2 — склад в Китае · 3 — Китай → Москва\n"
        "   4 — таможня · 5 — прибыл в Москву · 6 — передан в доставку\n"
        "   7 — доставлен\n\n"
        "🚚 Трек последней мили — «трек A1042 СДЭК 1234567890».\n"
        "   Клиент увидит номер в приложении и сможет открыть отслеживание.\n"
        "   Если заказ ещё не на этапе 6, статус поднимется сам.\n\n"
        "📚 Менять статус сразу у пачки — «все заказы со статусом 2 переведи в 3»\n\n"
        "🔍 Искать заказы — «что с A1042», «покажи заказы @ivanov»\n\n"
        "📷 Фото товаров — пришли одно или сразу альбом с номером заказа\n"
        "в подписи, клиент пролистает их в приложении\n\n"
        "💬 Отвечать клиентам — их сообщения приходят сюда,\n"
        "ответь реплаем, и я передам\n\n"
        "🎁 Рефералка — клиент зовёт друга своей ссылкой,\n"
        "оба получают бонус, когда друг оформляет первый заказ\n\n"
        "⭐ Отзывы — после доставки бот просит оценку, фото и комментарий\n\n"
        "🔍 Разбирать конкурентов/рекламные каналы — пришли ссылку на канал\n"
        "отдельным сообщением (t.me/somechannel или @somechannel)\n\n"
        "🎙 Понимаю и голосовые сообщения — просто наговори то же самое голосом\n\n"
        "Команды:\n"
        "/reminders — список активных напоминаний\n"
        "/cancel <номер> — отменить напоминание из списка\n"
        "/orders_today — сколько заказов добавлено сегодня\n"
        "/active — сколько сейчас активных заказов\n"
        "/stats — сводка и прибыль за 7 дней\n"
        "/month — сводка и прибыль за 30 дней\n"
        "/stuck — заказы, которые давно стоят на месте\n"
        "/reviews — последние отзывы клиентов\n"
        "/refs — кто кого привёл и сколько бонусов висит\n\n"
        f"Твой chat_id: {message.chat.id} — сохрани его в переменную OWNER_CHAT_ID, "
        "если хочешь получать напоминания и уведомления именно сюда.\n\n"
        "⚠️ В заказе всегда указывай @username клиента — иначе он не увидит заказ "
        "у себя и не получит уведомление о смене статуса.",
        reply_markup=ReplyKeyboardRemove(),
    )


@dp.message(Command("reminders"))
async def on_reminders(message: Message) -> None:
    reminders = scheduler.list_reminders(message.chat.id)
    if not reminders:
        await message.answer("У тебя нет активных напоминаний.")
        return

    lines = ["📋 Активные напоминания:\n"]
    for i, r in enumerate(reminders, start=1):
        lines.append(f"{i}. {r['text']} — {r['run_time'].strftime('%d.%m.%Y в %H:%M')}")
    lines.append("\nЧтобы отменить: /cancel <номер>")
    await message.answer("\n".join(lines))


@dp.message(Command("cancel"))
async def on_cancel(message: Message, command: CommandObject) -> None:
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Укажи номер напоминания для отмены, например: /cancel 2\n"
                              "Посмотреть номера: /reminders")
        return

    index = int(command.args.strip())
    try:
        text = scheduler.cancel_reminder(message.chat.id, index)
    except IndexError:
        await message.answer("Нет напоминания с таким номером. Посмотри список: /reminders")
        return
    await message.answer(f"❌ Напоминание «{text}» отменено.")


@dp.message(Command("orders_today"))
async def on_orders_today(message: Message) -> None:
    try:
        count = sheets_service.count_orders_today()
    except Exception:
        logger.exception("Ошибка при подсчёте заказов за сегодня")
        await message.answer("⚠️ Не получилось посчитать заказы, попробуй позже.")
        return
    await message.answer(f"📦 Сегодня добавлено заказов: {count}")


def _format_active(stats: dict) -> str:
    """Сводка по активным заказам для ответа владельцу."""
    active = stats["active"]
    if active == 0:
        lines = ["📦 Активных заказов сейчас нет."]
        if stats["delivered"]:
            lines.append(f"Уже доставлено: {stats['delivered']}.")
        return "\n".join(lines)

    lines = [f"📦 Активных заказов сейчас: {active}"]
    if stats["by_status"]:
        lines.append("")
        for item in stats["by_status"]:
            lines.append(f"• {item['status']} — {item['label']}: {item['count']}")
    if stats["delivered"]:
        lines.append(f"\n✅ Доставлено всего: {stats['delivered']}")
    return "\n".join(lines)


@dp.message(Command("active"))
async def on_active(message: Message) -> None:
    try:
        stats = sheets_service.active_orders_stats()
    except Exception:
        logger.exception("Ошибка при подсчёте активных заказов")
        await message.answer("⚠️ Не получилось посчитать активные заказы, попробуй позже.")
        return
    await message.answer(_format_active(stats))


def _money(value: float) -> str:
    """Красиво форматирует сумму: 12500.0 → «12 500 ₽»."""
    return f"{value:,.0f}".replace(",", " ") + " ₽"


def _format_stats(stats: dict, days: int) -> str:
    lines = [f"📊 За последние {days} дн.: {stats['total']} заказ(ов)."]

    if stats["revenue"] or stats["cost"]:
        lines.append("")
        lines.append(f"💰 Продажи: {_money(stats['revenue'])}")
        lines.append(f"💸 Закупка: {_money(stats['cost'])}")
        lines.append(f"📈 Прибыль: {_money(stats['profit'])}")
        if stats["with_money"] < stats["total"]:
            no_money = stats["total"] - stats["with_money"]
            lines.append(f"\n⚠️ У {no_money} заказ(ов) не указаны суммы — они не в подсчёте.")
    else:
        lines.append("\n💰 Суммы не указаны ни в одном заказе за период.\n"
                     "Добавляй их прямо в описание: «закупка 4000, продал за 7500».")

    if stats["top_products"]:
        lines.append("\nТоп товаров:")
        for product, count in stats["top_products"]:
            lines.append(f"• {product} — {count}")
    return "\n".join(lines)


@dp.message(Command("stats"))
async def on_stats(message: Message) -> None:
    try:
        stats = sheets_service.period_stats(7)
    except Exception:
        logger.exception("Ошибка при подсчёте статистики за неделю")
        await message.answer("⚠️ Не получилось посчитать статистику, попробуй позже.")
        return
    await message.answer(_format_stats(stats, 7))


@dp.message(Command("month"))
async def on_month(message: Message) -> None:
    try:
        stats = sheets_service.period_stats(30)
    except Exception:
        logger.exception("Ошибка при подсчёте статистики за месяц")
        await message.answer("⚠️ Не получилось посчитать статистику, попробуй позже.")
        return
    await message.answer(_format_stats(stats, 30))


@dp.message(Command("stuck"))
async def on_stuck(message: Message) -> None:
    try:
        orders = sheets_service.stuck_orders(config.STUCK_ORDER_DAYS)
    except Exception:
        logger.exception("Ошибка при поиске зависших заказов")
        await message.answer("⚠️ Не получилось проверить заказы, попробуй позже.")
        return
    await message.answer(_format_stuck(orders))


@dp.message(Command("reviews"))
async def on_reviews(message: Message) -> None:
    summary = reviews_service.stats()
    items = reviews_service.recent()
    if not summary["rated"]:
        await message.answer("⭐ Отзывов пока нет — бот попросит их после первой доставки.")
        return

    lines = [
        f"⭐ Отзывы: {summary['average']:.1f} из 5 "
        f"({summary['rated']} оценок, фото: {summary['with_photo']})\n"
    ]
    for item in items:
        who = f"@{item['username']}" if item["username"] else "клиент"
        stars = "⭐" * (item["rating"] or 0)
        extra = " 📷" if item.get("photo_path") else ""
        lines.append(f"• {item['order_number']} · {who} · {stars}{extra}")
        if item.get("comment"):
            lines.append(f"  {item['comment'][:180]}")
    await message.answer("\n".join(lines))


@dp.message(Command("refs"))
async def on_refs(message: Message) -> None:
    totals = referrals_service.totals()
    top = referrals_service.top_referrers()
    if not totals["invited"]:
        await message.answer(
            "🎁 Пока никто не пришёл по приглашению.\n"
            "Клиенты зовут друзей командой /invite или кнопкой в приложении."
        )
        return

    lines = [
        f"🎁 Рефералка: {totals['invited']} переходов, "
        f"{totals['rewarded']} заказов, {_money(totals['bonus'])} бонусов\n"
    ]
    for item in top:
        lines.append(
            f"• @{item['username']} — перешли {item['invited']}, "
            f"заказали {item['rewarded']}, бонус {_money(item['bonus'])}"
        )
    lines.append(
        f"\nСкидка другу {_money(config.REFERRAL_FRIEND_BONUS)} на первый заказ, "
        f"пригласившему {_money(config.REFERRAL_BONUS)} на следующий. "
        "Списываешь руками, бот только напоминает."
    )
    await message.answer("\n".join(lines))


_ONLY_CHANNEL_RE = re.compile(
    r"^(?:https?://)?(?:t\.me/(?:s/)?[A-Za-z0-9_]{4,}/?|@[A-Za-z0-9_]{4,})$"
)
_ANALYZE_WORDS = ("разбер", "разбор", "анализ", "проанализир", "оцени канал")


def _is_channel_request(text: str) -> bool:
    """
    Разбор канала запускается, только если сообщение — это сама ссылка/юзернейм
    или в нём есть явная просьба разобрать. Иначе заказ вида
    «@ivanov заказал кроссовки» уходил бы в анализ канала вместо записи в таблицу.
    """
    stripped = (text or "").strip()
    if _ONLY_CHANNEL_RE.match(stripped):
        return True
    if not channel_analyzer.extract_username(stripped):
        return False
    lowered = stripped.lower()
    return any(word in lowered for word in _ANALYZE_WORDS)


@dp.message(~F.reply_to_message & F.text & F.text.func(_is_channel_request))
async def on_channel_link(message: Message) -> None:
    """Если сообщение похоже на ссылку/юзернейм канала - делаем разбор."""
    username = channel_analyzer.extract_username(message.text)
    if not username:
        return  # пусть уйдёт в обычный обработчик ниже

    await message.answer(f"Разбираю канал @{username}, подожди немного...")
    try:
        posts_text = channel_analyzer.fetch_channel_posts(username)
        analysis = gemini_service.analyze_channel(posts_text, username)
        await message.answer(analysis)
    except ValueError as e:
        await message.answer(f"⚠️ {e}")
    except Exception:
        logger.exception("Ошибка при разборе канала")
        await message.answer("⚠️ Не получилось разобрать канал, попробуй ещё раз чуть позже.")


def _status_short(status: int) -> str:
    index = status - 1
    label = config.ORDER_STATUSES[index] if 0 <= index < len(config.ORDER_STATUSES) else "?"
    return f"{status} — {label}"


def _clean_items(raw_items) -> list:
    """Приводит товары от Gemini к виду, который ждёт таблица."""
    items = []
    for raw in raw_items or []:
        if not isinstance(raw, dict):
            continue
        product = str(raw.get("product") or "").strip()
        if not product:
            continue
        items.append({
            "product": product,
            "size": str(raw.get("size") or "").strip(),
            "color": str(raw.get("color") or "").strip(),
            "cost_price": float(raw.get("cost_price") or 0),
            "sale_price": float(raw.get("sale_price") or 0),
        })
    return items


def _item_line(item: dict) -> str:
    """Товар одной строкой: «Nike Air Force (размер 42 · чёрные · 7 500 ₽)»."""
    extra = []
    if item.get("size"):
        extra.append(f"размер {item['size']}")
    if item.get("color"):
        extra.append(item["color"])
    if item.get("sale_price"):
        extra.append(_money(item["sale_price"]))
    return item["product"] + (f" ({' · '.join(extra)})" if extra else "")


def _format_items(items: list, indent: str = "") -> str:
    return "\n".join(f"{indent}{i}. {_item_line(item)}" for i, item in enumerate(items, start=1))


def _format_orders(orders: list, query: str) -> str:
    """Список найденных заказов для ответа владельцу."""
    if not orders:
        return f"🔍 По запросу «{query}» ничего не нашёл."

    lines = [f"🔍 Нашёл заказ(ов): {len(orders)}\n"]
    for order in orders:
        who = order["username"] or order["full_name"] or "клиент не указан"
        lines.append(f"📦 {order['order_number']} · {who}")
        lines.append(f"   Статус {_status_short(order['status'])}")
        track = _tracking_text(order)
        if track:
            lines.append(f"   {track}")
        lines.append(_format_items(order["items"], indent="   "))
        if order["sale_price"]:
            lines.append(f"   Итого продажа {_money(order['sale_price'])}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_stuck(orders: list) -> str:
    if not orders:
        return "✅ Зависших заказов нет — всё движется."

    lines = [f"⏳ Давно без движения: {len(orders)} заказ(ов)\n"]
    for order in orders:
        who = order["username"] or order["full_name"] or "клиент не указан"
        lines.append(
            f"📦 {order['order_number']} — {order['product'] or 'товар не указан'}\n"
            f"   {who} · {_status_short(order['status'])} · стоит {order['idle_days']} дн."
        )
    return "\n".join(lines)


def _tracking_text(order: dict) -> str:
    data = order.get("tracking") or {}
    number = (data.get("number") or "").strip()
    if not number:
        return ""
    label = (data.get("carrier_label") or "").strip()
    return f"{label} {number}".strip() if label else f"Трек {number}"


def _tracking_payload(order: dict) -> Optional[dict]:
    data = order.get("tracking") or {}
    return data if data.get("number") else None


async def _notify_client(username: str, order_number: str, product: str, new_status: int,
                         tracking: Optional[dict] = None) -> str:
    """Шлёт клиенту пуш о новом статусе и возвращает строку об итоге — для ответа владельцу."""
    if not username:
        return "ℹ️ Клиент не уведомлён: в заказе не указан @username."
    if not config.CLIENT_BOT_TOKEN:
        return "ℹ️ Клиент не уведомлён: клиентский бот не настроен."

    sent = await client_bot.notify_status_change(
        username, order_number, product, new_status, tracking=tracking
    )
    scheduler.schedule_review_request(username, order_number, product, new_status)
    if sent:
        return f"📨 Уведомление отправлено клиенту {username}."
    return (
        f"ℹ️ Клиент {username} ещё не открыл диалог с клиентским ботом — "
        "уведомление не доставлено. Попроси его нажать /start."
    )


async def _notify_tracking(username: str, order_number: str, product: str, tracking: dict) -> str:
    if not username:
        return "ℹ️ Клиент не уведомлён: в заказе не указан @username."
    if not config.CLIENT_BOT_TOKEN:
        return "ℹ️ Клиент не уведомлён: клиентский бот не настроен."
    sent = await client_bot.notify_tracking(username, order_number, product, tracking)
    if sent:
        return f"📨 Трек отправлен клиенту {username}."
    return (
        f"ℹ️ Клиент {username} ещё не открыл диалог с клиентским ботом — "
        "уведомление не доставлено. Попроси его нажать /start."
    )


async def _apply_referral_if_first(username: str, order_number: str) -> str:
    """
    Если это первый заказ человека, пришедшего по ссылке друга — начисляет бонус
    и возвращает напоминание владельцу, какую скидку списать руками.
    """
    if not username:
        return ""
    try:
        orders = sheets_service.get_orders_by_username(username)
    except Exception:
        logger.exception("Не удалось проверить, первый ли это заказ @%s", username)
        return ""
    if len(orders) != 1:
        return ""

    reward = referrals_service.reward_for_order(username, order_number)
    if not reward:
        return ""

    referrer = reward["referrer_username"]
    await client_bot.notify_referral_reward(referrer, username)
    await client_bot.notify_friend_discount(username, order_number)
    return (
        f"\n\n🎁 Этот клиент пришёл от @{referrer}.\n"
        f"Дай @{username} скидку {_money(config.REFERRAL_FRIEND_BONUS)} на этот заказ, "
        f"@{referrer} — {_money(config.REFERRAL_BONUS)} на следующий."
    )


async def _apply_bulk_result(updated: list, new_status: int) -> str:
    """Рассылает уведомления после массовой смены статуса и собирает отчёт владельцу."""
    if not updated:
        return "ℹ️ Подходящих заказов не нашлось — ничего не изменил."

    notified, skipped = 0, []
    for order in updated:
        username = order["username"]
        scheduler.schedule_review_request(
            username, order["order_number"], order["product"], new_status
        )
        if username and config.CLIENT_BOT_TOKEN and await client_bot.notify_status_change(
            username, order["order_number"], order["product"], new_status,
            tracking=_tracking_payload(order),
        ):
            notified += 1
        else:
            skipped.append(order["order_number"])

    lines = [
        f"✅ Обновлено заказов: {len(updated)} → статус {_status_short(new_status)}",
        "",
        "Номера: " + ", ".join(order["order_number"] for order in updated),
        "",
        f"📨 Уведомлено клиентов: {notified}",
    ]
    if skipped:
        lines.append(
            f"ℹ️ Без уведомления ({len(skipped)}): " + ", ".join(skipped) +
            "\nУ этих заказов нет @username или клиент не открыл бота."
        )
    return "\n".join(lines)


async def _handle_text(message: Message, text: str) -> None:
    """Общая обработка: напоминание/заказ/обычный ответ + запись в историю чата."""
    _remember_owner(message)
    history = memory_service.get_history(message.chat.id)
    result = gemini_service.process_message(text, conversation_history=history)

    if result["type"] == "reminder":
        run_date = scheduler.add_reminder(
            chat_id=message.chat.id,
            remind_at_iso=result["remind_at"],
            text=result["text"],
        )
        reply_text = (
            f"✅ Напомню: «{result['text']}»\n"
            f"Когда: {run_date.strftime('%d.%m.%Y в %H:%M')}"
        )

    elif result["type"] == "order":
        items = _clean_items(result.get("items"))
        cost = sum(item["cost_price"] for item in items)
        sale = sum(item["sale_price"] for item in items)
        try:
            order_number = sheets_service.generate_order_number()
            sheets_service.append_order(
                username=result.get("username", ""),
                full_name=result.get("full_name", ""),
                order_number=order_number,
                items=items,
            )
        except ValueError as e:
            reply_text = f"⚠️ {e}"
        except Exception:
            logger.exception("Ошибка при записи заказа в таблицу")
            reply_text = "⚠️ Не получилось записать заказ, попробуй ещё раз."
        else:
            reply_text = (
                f"✅ Заказ записан в таблицу.\n"
                f"Номер заказа: {order_number} — передай его клиенту.\n\n"
                f"Товаров в заказе: {len(items)}\n{_format_items(items)}"
            )
            if cost or sale:
                reply_text += f"\n\n💰 Закупка {_money(cost)} · продажа {_money(sale)} · прибыль {_money(sale - cost)}"
            if not result.get("username"):
                reply_text += (
                    "\n\n⚠️ Не указан @username клиента — он не увидит заказ "
                    "в приложении и не получит уведомлений."
                )
            else:
                reply_text += await _apply_referral_if_first(result.get("username", ""), order_number)
            _last_order_number[message.chat.id] = order_number

    elif result["type"] == "add_items":
        order_number = str(result.get("order_number", "")).strip().upper()
        items = _clean_items(result.get("items"))
        try:
            order = sheets_service.add_items(order_number, items)
        except ValueError as e:
            reply_text = f"⚠️ {e}"
        except Exception:
            logger.exception("Ошибка при добавлении товаров в заказ %s", order_number)
            reply_text = "⚠️ Не получилось дописать товары, попробуй ещё раз."
        else:
            reply_text = (
                f"✅ Добавил в заказ {order_number} товаров: {len(items)}\n\n"
                f"Теперь в заказе {len(order['items'])}:\n{_format_items(order['items'])}"
            )
            _last_order_number[message.chat.id] = order_number

    elif result["type"] == "change_status":
        order_number = result.get("order_number", "")
        try:
            order = sheets_service.change_order_status(order_number, result.get("new_status"))
            track_number = str(result.get("tracking_number") or "").strip()
            if track_number:
                order = sheets_service.set_tracking(
                    order_number, track_number, str(result.get("carrier") or "")
                )
        except ValueError as e:
            reply_text = f"⚠️ {e}"
        except Exception:
            logger.exception("Ошибка при изменении статуса заказа")
            reply_text = "⚠️ Не получилось изменить статус, попробуй позже."
        else:
            new_status = int(order.get("status") or result.get("new_status"))
            status_label = config.ORDER_STATUSES[new_status - 1]
            product = order["product"]
            reply_text = f"✅ Статус заказа {order_number} ({product}) обновлён: {new_status} — {status_label}."
            track = _tracking_text(order)
            if track:
                reply_text += f"\n{track}"
            reply_text += "\n" + await _notify_client(
                order["username"], order_number, product, new_status,
                tracking=_tracking_payload(order),
            )

    elif result["type"] == "set_tracking":
        order_number = str(result.get("order_number") or "").strip().upper()
        try:
            order = sheets_service.set_tracking(
                order_number,
                str(result.get("tracking_number") or ""),
                str(result.get("carrier") or ""),
            )
        except ValueError as e:
            reply_text = f"⚠️ {e}"
        except Exception:
            logger.exception("Ошибка при записи трека заказа %s", order_number)
            reply_text = "⚠️ Не получилось записать трек, попробуй позже."
        else:
            product = order["product"]
            track = _tracking_text(order)
            reply_text = f"✅ Трек заказа {order_number} ({product}) записан: {track}."
            if order.get("status_changed"):
                status_label = config.ORDER_STATUSES[order["status"] - 1]
                reply_text += (
                    f"\nСтатус обновлён: {order['status']} — {status_label}."
                )
                reply_text += "\n" + await _notify_client(
                    order["username"], order_number, product, order["status"],
                    tracking=_tracking_payload(order),
                )
            else:
                reply_text += "\n" + await _notify_tracking(
                    order["username"], order_number, product, order["tracking"]
                )

    elif result["type"] == "change_status_bulk":
        from_status = int(result.get("from_status") or 0) or None
        numbers = [str(n) for n in (result.get("order_numbers") or [])]
        try:
            updated = sheets_service.change_orders_status_bulk(
                new_status=result.get("new_status"),
                from_status=from_status,
                order_numbers=numbers,
            )
        except ValueError as e:
            reply_text = f"⚠️ {e}"
        except Exception:
            logger.exception("Ошибка при массовой смене статуса")
            reply_text = "⚠️ Не получилось обновить заказы, попробуй позже."
        else:
            reply_text = await _apply_bulk_result(updated, int(result.get("new_status")))

    elif result["type"] == "find_orders":
        query = str(result.get("query", ""))
        try:
            orders = sheets_service.find_orders(query)
        except Exception:
            logger.exception("Ошибка при поиске заказов")
            reply_text = "⚠️ Не получилось найти заказы, попробуй позже."
        else:
            reply_text = _format_orders(orders, query)

    elif result["type"] == "stuck_orders":
        days = int(result.get("days") or config.STUCK_ORDER_DAYS)
        try:
            orders = sheets_service.stuck_orders(days)
        except Exception:
            logger.exception("Ошибка при поиске зависших заказов")
            reply_text = "⚠️ Не получилось проверить заказы, попробуй позже."
        else:
            reply_text = _format_stuck(orders)

    elif result["type"] == "active_orders":
        try:
            stats = sheets_service.active_orders_stats()
        except Exception:
            logger.exception("Ошибка при подсчёте активных заказов")
            reply_text = "⚠️ Не получилось посчитать активные заказы, попробуй позже."
        else:
            reply_text = _format_active(stats)

    else:
        reply_text = result["text"]

    await message.answer(reply_text)
    memory_service.add_message(message.chat.id, "user", text)
    memory_service.add_message(message.chat.id, "model", reply_text)


_ORDER_NUMBER_RE = re.compile(r"\b([A-Za-z]\d{4})\b")


async def _download_photo(file_id: str) -> bytes:
    file_info = await bot.get_file(file_id)
    downloaded = await bot.download_file(file_info.file_path)
    return downloaded.read()


# Альбом приходит в Telegram отдельными сообщениями с общим media_group_id,
# и подпись есть только у первого. Здесь держим номер заказа для всего альбома
# и помним, за какой альбом уже ответили, чтобы не слать пачку одинаковых ответов.
_album_order = {}
_answered_albums = set()


def _should_answer(message: Message) -> bool:
    """На альбом отвечаем один раз, а не на каждое фото в нём."""
    group_id = message.media_group_id
    if not group_id:
        return True
    if group_id in _answered_albums:
        return False
    if len(_answered_albums) > 200:
        _answered_albums.clear()
        _album_order.clear()
    _answered_albums.add(group_id)
    return True


async def _album_order_number(media_group_id: str) -> str:
    """Ждёт немного номер заказа из подписи первого фото альбома."""
    for _ in range(10):
        if media_group_id in _album_order:
            return _album_order[media_group_id]
        await asyncio.sleep(0.3)
    return ""


async def _resolve_photo_order(message: Message, caption: str) -> str:
    """К какому заказу приложить это фото."""
    match = _ORDER_NUMBER_RE.search(caption)
    if match:
        return match.group(1).upper()

    if caption:
        # В подписи описан новый заказ — сначала создаём его обычным путём.
        await _handle_text(message, caption)
        return _last_order_number.get(message.chat.id, "")

    if message.media_group_id:
        number = await _album_order_number(message.media_group_id)
        if number:
            return number

    return _last_order_number.get(message.chat.id, "")


@dp.message(F.photo)
async def on_photo(message: Message) -> None:
    """
    Фото товара — их можно прислать сколько угодно, хоть альбомом.
    Если в подписи есть номер заказа — цепляем к нему. Если подпись описывает
    новый заказ — создаём заказ и сразу прикладываем фото. Без подписи —
    цепляем к последнему заказу, с которым работали.
    """
    _remember_owner(message)
    caption = (message.caption or "").strip()
    order_number = await _resolve_photo_order(message, caption)

    if not order_number:
        if _should_answer(message):
            await message.answer(
                "📷 Фото получил, но не понял, к какому заказу его приложить.\n"
                "Добавь номер в подпись, например «A1042», или сначала создай заказ."
            )
        return

    if message.media_group_id:
        _album_order[message.media_group_id] = order_number
    _last_order_number[message.chat.id] = order_number

    try:
        data = await _download_photo(message.photo[-1].file_id)
        total = photo_service.add(order_number, data)
        sheets_service.set_photo_count(order_number, total)
    except ValueError as e:
        await message.answer(f"⚠️ {e}")
        return
    except Exception:
        logger.exception("Ошибка при сохранении фото заказа %s", order_number)
        await message.answer("⚠️ Не получилось сохранить фото, попробуй ещё раз.")
        return

    if not _should_answer(message):
        return

    if message.media_group_id:
        await message.answer(
            f"📷 Добавляю фото к заказу {order_number} — клиент сможет пролистать их в приложении."
        )
    else:
        await message.answer(
            f"📷 Фото добавлено к заказу {order_number} (всего {total}) — "
            "клиент увидит его в приложении."
        )


@dp.message(F.reply_to_message)
async def on_reply_to_client(message: Message) -> None:
    """Ответ реплаем на пересланное сообщение клиента — отправляем ему в клиентский бот."""
    target = clients_service.get_forwarded(message.reply_to_message.message_id)
    if not target:
        await _handle_text(message, message.text or "")
        return

    text = (message.text or "").strip()
    if not text:
        await message.answer("⚠️ Отправь текстом, что передать клиенту.")
        return

    if await client_bot.send_to_client(target["chat_id"], text):
        who = f"@{target['username']}" if target["username"] else "клиенту"
        await message.answer(f"📨 Ответ отправлен {who}.")
    else:
        await message.answer("⚠️ Не получилось доставить ответ — возможно, клиент заблокировал бота.")


async def notify_owner_message(
    text: str,
    reply_chat_id: int = None,
    reply_username: str = "",
) -> None:
    """Короткая пометка в ассистенте. Само сообщение клиента пересылает клиентский бот."""
    owner = clients_service.get_owner_chat_id()
    if not owner:
        logger.warning("Чат владельца неизвестен — не могу переслать уведомление.")
        return

    sent = await bot.send_message(owner, text)
    if reply_chat_id:
        clients_service.remember_forwarded(
            sent.message_id, reply_chat_id, reply_username or ""
        )


@dp.message(F.voice)
async def on_voice(message: Message) -> None:
    """Расшифровывает голосовое через Gemini и обрабатывает как обычный текст."""
    try:
        file_info = await bot.get_file(message.voice.file_id)
        file_bytes = await bot.download_file(file_info.file_path)
        transcribed = gemini_service.transcribe_voice(file_bytes.read())
    except Exception:
        logger.exception("Ошибка при расшифровке голосового сообщения")
        await message.answer("⚠️ Не получилось распознать голосовое, попробуй ещё раз или напиши текстом.")
        return

    if not transcribed:
        await message.answer("⚠️ Не удалось разобрать, что сказано, попробуй ещё раз.")
        return

    await message.answer(f"🗒 Расшифровка: «{transcribed}»")
    await _handle_text(message, transcribed)


@dp.message(F.text)
async def on_text(message: Message) -> None:
    await _handle_text(message, message.text)


def _run_api_server() -> None:
    """Поднимает FastAPI (трекер заказов) в отдельном потоке на порту из $PORT."""
    port = int(config.PORT)
    logger.info("Запускаю API-сервер трекера заказов на порту %s...", port)
    uvicorn.run(api.app, host="0.0.0.0", port=port, log_level="warning")


async def main() -> None:
    scheduler.init(bot)
    client_bot.notify_owner = notify_owner_message
    threading.Thread(target=_run_api_server, daemon=True).start()

    tasks = [dp.start_polling(bot)]
    if config.CLIENT_BOT_TOKEN:
        tasks.append(client_bot.start_client_polling())

    logger.info("Ассистент запущен, ожидаю сообщения...")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
