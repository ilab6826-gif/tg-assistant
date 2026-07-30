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


# Папка для файлов, которые должны переживать передеплой (базы SQLite).
# На Railway сюда монтируется постоянный диск (volume), локально — корень проекта.
DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)


def data_path(filename: str) -> str:
    """Путь к файлу внутри постоянного хранилища."""
    return os.path.join(DATA_DIR, filename)


TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = _require("GEMINI_API_KEY")

# Клиентский бот — только Mini App для отслеживания заказов (отдельный от ассистента).
CLIENT_BOT_TOKEN = os.getenv("CLIENT_BOT_TOKEN", "")

OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")  # может быть пустым при первом запуске

GOOGLE_SHEET_ID = _require("GOOGLE_SHEET_ID")
GOOGLE_SHEET_WORKSHEET = os.getenv("GOOGLE_SHEET_WORKSHEET", "Заказы")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

# На хостинге (Railway и т.п.) сам credentials.json обычно не деплоится (он в
# .gitignore). Если задана переменная GOOGLE_CREDENTIALS_JSON с полным
# содержимым файла — материализуем его на диск при старте.
_google_credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
if _google_credentials_json and not os.path.exists(GOOGLE_CREDENTIALS_FILE):
    with open(GOOGLE_CREDENTIALS_FILE, "w") as _f:
        _f.write(_google_credentials_json)

TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")

# Порт для встроенного API трекера заказов (Railway сам подставляет $PORT).
PORT = os.getenv("PORT", "8080")

OWN_CHANNEL_DESCRIPTION = os.getenv(
    "OWN_CHANNEL_DESCRIPTION",
    "Сервис доставки товаров из Китая.",
)

# Жёстко зашит в код (а не в .env), чтобы бот всегда знал свой канал,
# даже если переменная окружения потеряется.
OWN_CHANNEL_USERNAME = "www_pr0ject"

GEMINI_MODEL = "gemini-flash-latest"

# Ссылка на Telegram Mini App (страница трекера заказов), открывается кнопкой
# в клиентском боте. Должна быть https-ссылкой (требование Telegram WebApp).
MINI_APP_URL = os.getenv("MINI_APP_URL", "")

# Название бренда в Mini App.
BRAND_NAME = os.getenv("BRAND_NAME", "PR0JECT")

# Через сколько дней без смены статуса заказ считается зависшим.
STUCK_ORDER_DAYS = int(os.getenv("STUCK_ORDER_DAYS", "10"))

# Этапы трекера заказа, индекс списка + 1 = число в колонке "Статус".
# Если меняешь список — не забудь про уже записанные заказы: вставка пункта
# в середину сдвигает смысл всех номеров после него.
ORDER_STATUSES = [
    "Товар выкуплен",
    "Прибыл на склад в Китае",
    "Едет Китай → Москва",
    "Проходит таможенный досмотр",
    "Прибыл в Москву",
    "Передан в доставку",
    "Доставлен",
]
