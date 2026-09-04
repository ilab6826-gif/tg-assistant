"""
Планировщик напоминаний. Использует SQLite-хранилище задач, чтобы
напоминания не терялись при перезапуске бота (например, при деплое на Railway).
"""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from bot import client_bot, clients_service, config, reviews_service, sheets_service

logger = logging.getLogger(__name__)

_jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{config.data_path('reminders.sqlite')}")}
scheduler = AsyncIOScheduler(jobstores=_jobstores, timezone=ZoneInfo(config.TIMEZONE))

_bot = None  # инициализируется в main.py через init()


def init(bot_instance) -> None:
    global _bot
    _bot = bot_instance
    scheduler.add_job(
        _send_weekly_digest,
        trigger="cron",
        day_of_week="mon",
        hour=9,
        minute=0,
        id="weekly_digest",
        replace_existing=True,
    )
    scheduler.add_job(
        _check_stuck_orders,
        trigger="cron",
        hour=10,
        minute=0,
        id="stuck_orders_check",
        replace_existing=True,
    )
    scheduler.start()


async def _send_reminder(chat_id: int, text: str) -> None:
    await _bot.send_message(chat_id, f"⏰ Напоминание: {text}")


def add_reminder(chat_id: int, remind_at_iso: str, text: str) -> datetime:
    """Регистрирует напоминание. Возвращает datetime, на которое оно запланировано."""
    tz = ZoneInfo(config.TIMEZONE)
    run_date = datetime.fromisoformat(remind_at_iso)
    if run_date.tzinfo is None:
        run_date = run_date.replace(tzinfo=tz)

    scheduler.add_job(
        _send_reminder,
        trigger="date",
        run_date=run_date,
        args=[chat_id, text],
        misfire_grace_time=3600,  # если бот был выключен - напомнит с опозданием до часа
    )
    return run_date


def schedule_review_request(username: str, order_number: str, product: str, new_status: int) -> bool:
    """
    Ставит отложенный запрос отзыва, когда заказ дошёл до последнего этапа.
    False, если спрашивать не нужно: статус не финальный, клиент не открывал
    бота или по этому заказу отзыв уже запрашивали.
    """
    if new_status < len(config.ORDER_STATUSES) or not config.CLIENT_BOT_TOKEN:
        return False

    chat_id = clients_service.get_chat_id(username)
    if not chat_id:
        return False

    if not reviews_service.mark_asked(order_number, username, chat_id):
        return False

    # Пять секунд сверху даже при нулевой задержке: пуш о доставке должен
    # прийти раньше просьбы об оценке.
    delay = timedelta(hours=max(0.0, config.REVIEW_DELAY_HOURS), seconds=5)
    scheduler.add_job(
        _ask_review,
        trigger="date",
        run_date=datetime.now(ZoneInfo(config.TIMEZONE)) + delay,
        kwargs={"chat_id": chat_id, "order_number": order_number, "product": product},
        id=f"review_{order_number}",
        replace_existing=True,
        misfire_grace_time=86400,  # бот мог быть выключен — спросим с опозданием до суток
    )
    return True


async def _ask_review(chat_id: int, order_number: str, product: str) -> None:
    await client_bot.send_review_request(chat_id, order_number, product)


def list_reminders(chat_id: int) -> list:
    """
    Возвращает активные напоминания пользователя, отсортированные по времени:
    [{"job_id": ..., "run_time": datetime, "text": ...}, ...]
    """
    jobs = [
        job
        for job in scheduler.get_jobs()
        if job.args and job.args[0] == chat_id and job.next_run_time is not None
    ]
    jobs.sort(key=lambda job: job.next_run_time)
    return [{"job_id": job.id, "run_time": job.next_run_time, "text": job.args[1]} for job in jobs]


def cancel_reminder(chat_id: int, index: int) -> str:
    """
    Отменяет напоминание по номеру (1-based) из list_reminders(chat_id).
    Возвращает текст отменённого напоминания. Бросает IndexError при неверном номере.
    """
    reminders = list_reminders(chat_id)
    if index < 1 or index > len(reminders):
        raise IndexError(f"Нет напоминания с номером {index}")
    target = reminders[index - 1]
    scheduler.remove_job(target["job_id"])
    return target["text"]


def _money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ") + " ₽"


async def _send_weekly_digest() -> None:
    """Раз в неделю присылает владельцу сводку заказов из Google Таблицы."""
    owner_chat_id = clients_service.get_owner_chat_id()
    if not owner_chat_id:
        logger.warning("Чат владельца неизвестен — пропускаю еженедельный дайджест.")
        return

    try:
        stats = sheets_service.weekly_stats()
    except Exception:
        logger.exception("Не удалось собрать статистику для еженедельного дайджеста")
        return

    lines = [f"📊 Еженедельный дайджест\n\nЗаказов за последние 7 дней: {stats['total']}"]
    if stats["revenue"] or stats["cost"]:
        lines.append(
            f"\n💰 Продажи: {_money(stats['revenue'])}"
            f"\n💸 Закупка: {_money(stats['cost'])}"
            f"\n📈 Прибыль: {_money(stats['profit'])}"
        )
    if stats["top_products"]:
        lines.append("\nПопулярные товары:")
        for product, count in stats["top_products"]:
            lines.append(f"• {product} — {count}")
    await _bot.send_message(owner_chat_id, "\n".join(lines))


async def _check_stuck_orders() -> None:
    """Раз в день проверяет, не застряли ли заказы на одном этапе."""
    owner_chat_id = clients_service.get_owner_chat_id()
    if not owner_chat_id:
        return

    try:
        orders = sheets_service.stuck_orders(config.STUCK_ORDER_DAYS)
    except Exception:
        logger.exception("Не удалось проверить зависшие заказы")
        return

    if not orders:
        return  # молчим, когда всё в порядке — лишние уведомления только мешают

    lines = [f"⏳ Заказы без движения дольше {config.STUCK_ORDER_DAYS} дн.: {len(orders)}\n"]
    for order in orders[:10]:
        who = order["username"] or order["full_name"] or "клиент не указан"
        status_index = order["status"] - 1
        label = (
            config.ORDER_STATUSES[status_index]
            if 0 <= status_index < len(config.ORDER_STATUSES)
            else "?"
        )
        lines.append(
            f"📦 {order['order_number']} — {order['product'] or 'товар не указан'}\n"
            f"   {who} · {label} · стоит {order['idle_days']} дн."
        )
    if len(orders) > 10:
        lines.append(f"\n…и ещё {len(orders) - 10}. Все: /stuck")

    await _bot.send_message(owner_chat_id, "\n".join(lines))
