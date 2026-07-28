"""
Планировщик напоминаний. Использует SQLite-хранилище задач, чтобы
напоминания не терялись при перезапуске бота (например, при деплое на Railway).
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from bot import config

_jobstores = {"default": SQLAlchemyJobStore(url="sqlite:///reminders.sqlite")}
scheduler = AsyncIOScheduler(jobstores=_jobstores, timezone=ZoneInfo(config.TIMEZONE))

_bot = None  # инициализируется в main.py через init()


def init(bot_instance) -> None:
    global _bot
    _bot = bot_instance
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
