import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot import config, scheduler, gemini_service, sheets_service, channel_analyzer, memory_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def on_start(message: Message) -> None:
    await message.answer(
        "Привет! Я твой личный ассистент. Умею:\n\n"
        "📌 Напоминать о задачах — просто напиши, например:\n"
        "«напомни завтра в 12:00 обработать заказ»\n\n"
        "📦 Записывать заказы в таблицу — опиши заказ свободным текстом:\n"
        "«@ivanov заказал кроссовки Nike, 42 размер, чёрные, Иванов Иван»\n\n"
        "🔍 Разбирать конкурентов/рекламные каналы — просто пришли ссылку на канал\n"
        "(например t.me/somechannel)\n\n"
        f"Твой chat_id: {message.chat.id} — сохрани его в переменную OWNER_CHAT_ID, "
        "если хочешь получать напоминания и уведомления именно сюда."
    )


@dp.message(F.text.contains("t.me/") | F.text.regexp(r"(?<!\S)@[A-Za-z0-9_]{4,}(?!\S)"))
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


@dp.message(F.text)
async def on_text(message: Message) -> None:
    history = memory_service.get_history(message.chat.id)
    result = gemini_service.process_message(message.text, conversation_history=history)

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
        sheets_service.append_order(
            username=result.get("username", ""),
            product=result.get("product", ""),
            size=result.get("size", ""),
            color=result.get("color", ""),
            full_name=result.get("full_name", ""),
        )
        reply_text = "✅ Заказ записан в таблицу."

    else:
        reply_text = result["text"]

    await message.answer(reply_text)
    memory_service.add_message(message.chat.id, "user", message.text)
    memory_service.add_message(message.chat.id, "model", reply_text)


async def main() -> None:
    scheduler.init(bot)
    logger.info("Бот запущен, ожидаю сообщения...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
