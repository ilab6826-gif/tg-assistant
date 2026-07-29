"""
Планировщик напоминаний. Использует SQLite-хранилище задач, чтобы
напоминания не терялись при перезапуске бота (например, при деплое на Railway).
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from bot import config, sheets_service

logger = logging.getLogger(__name__)

_jobstores = {"default": SQLAlchemyJobStore(url="sqlite:///reminders.sqlite")}
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


async def _send_weekly_digest() -> None:
    """Раз в неделю присылает владельцу сводку заказов из Google Таблицы."""
    if not config.OWNER_CHAT_ID:
        logger.warning("OWNER_CHAT_ID не задан — пропускаю еженедельный дайджест.")
        return

    try:
        stats = sheets_service.weekly_stats()
    except Exception:
        logger.exception("Не удалось собрать статистику для еженедельного дайджеста")
        return

    lines = [f"📊 Еженедельный дайджест\n\nЗаказов за последние 7 дней: {stats['total']}"]
    if stats["top_products"]:
        lines.append("\nПопулярные товары:")
        for product, count in stats["top_products"]:
            lines.append(f"• {product} — {count}")
    await _bot.send_message(int(config.OWNER_CHAT_ID), "\n".join(lines))
