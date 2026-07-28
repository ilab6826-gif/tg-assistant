"""
Загрузка настроек проекта из переменных окружения (.env локально, Variables на Railway).
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Не задана обязательная переменная окружения: {name}. "
            f"Проверь файл .env (локально) или Variables (на Railway)."
        )
    return value


TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = _require("GEMINI_API_KEY")

OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")  # может быть пустым при первом запуске

GOOGLE_SHEET_ID = _require("GOOGLE_SHEET_ID")
GOOGLE_SHEET_WORKSHEET = os.getenv("GOOGLE_SHEET_WORKSHEET", "Заказы")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")

OWN_CHANNEL_DESCRIPTION = os.getenv(
    "OWN_CHANNEL_DESCRIPTION",
    "Сервис доставки товаров из Китая.",
)

GEMINI_MODEL = "gemini-flash-latest"
