import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject, CommandStart
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
        "🎙 Понимаю и голосовые сообщения — просто наговори то же самое голосом\n\n"
        "Команды:\n"
        "/reminders — список активных напоминаний\n"
        "/cancel <номер> — отменить напоминание из списка\n"
        "/orders_today — сколько заказов добавлено сегодня\n"
        "/stats — сводка заказов за последние 7 дней\n\n"
        f"Твой chat_id: {message.chat.id} — сохрани его в переменную OWNER_CHAT_ID, "
        "если хочешь получать напоминания и уведомления именно сюда."
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


@dp.message(Command("stats"))
async def on_stats(message: Message) -> None:
    try:
        stats = sheets_service.weekly_stats()
    except Exception:
        logger.exception("Ошибка при подсчёте статистики за неделю")
        await message.answer("⚠️ Не получилось посчитать статистику, попробуй позже.")
        return

    lines = [f"📊 За последние 7 дней: {stats['total']} заказ(ов)."]
    if stats["top_products"]:
        lines.append("\nТоп товаров:")
        for product, count in stats["top_products"]:
            lines.append(f"• {product} — {count}")
    await message.answer("\n".join(lines))


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


async def _handle_text(message: Message, text: str) -> None:
    """Общая обработка: напоминание/заказ/обычный ответ + запись в историю чата."""
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
    memory_service.add_message(message.chat.id, "user", text)
    memory_service.add_message(message.chat.id, "model", reply_text)


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


async def main() -> None:
    scheduler.init(bot)
    logger.info("Бот запущен, ожидаю сообщения...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
