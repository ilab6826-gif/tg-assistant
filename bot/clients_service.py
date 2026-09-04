"""
Локальное хранилище бота (SQLite в постоянной папке DATA_DIR):

- clients   — реестр клиентов: @username → chat_id
- settings  — мелкие настройки, например chat_id владельца
- forwarded — какому клиенту принадлежит пересланное владельцу сообщение

Telegram позволяет боту писать только тем, кто сам открыл с ним диалог, поэтому
chat_id сохраняется в момент, когда клиент нажимает /start в клиентском боте.
По этой связке ассистент отправляет пуш о смене статуса заказа: в таблице
записан только @username клиента.
"""
import sqlite3
from contextlib import closing
from typing import Optional

from bot import config

DB_PATH = config.data_path("clients.sqlite")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS clients (
            username TEXT PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            first_name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS forwarded (
            owner_message_id INTEGER PRIMARY KEY,
            client_chat_id INTEGER NOT NULL,
            client_username TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    return conn


def normalize_username(username: str) -> str:
    return (username or "").strip().lstrip("@").lower()


def register(username: str, chat_id: int, first_name: str = "") -> None:
    """Запоминает клиента (или обновляет chat_id, если он сменился)."""
    key = normalize_username(username)
    if not key:
        return
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO clients (username, chat_id, first_name, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(username) DO UPDATE SET
                chat_id = excluded.chat_id,
                first_name = excluded.first_name,
                updated_at = excluded.updated_at
            """,
            (key, chat_id, first_name or ""),
        )
        conn.commit()


def exists(username: str) -> bool:
    """Знаем ли мы этого клиента. Проверять нужно до register(), иначе всегда True."""
    key = normalize_username(username)
    if not key:
        return False
    with closing(_connect()) as conn:
        row = conn.execute("SELECT 1 FROM clients WHERE username = ?", (key,)).fetchone()
    return row is not None


def get_chat_id(username: str) -> Optional[int]:
    """Возвращает chat_id клиента по @username, либо None, если он ещё не открыл бота."""
    key = normalize_username(username)
    if not key:
        return None
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT chat_id FROM clients WHERE username = ?", (key,)
        ).fetchone()
    return row[0] if row else None


def set_setting(key: str, value: str) -> None:
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        conn.commit()


def get_setting(key: str) -> Optional[str]:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


_OWNER_CHAT_KEY = "owner_chat_id"


def get_owner_chat_id() -> Optional[int]:
    """
    chat_id владельца: сначала из переменной окружения, иначе — сохранённый
    при первом обращении к ассистенту (бот приватный, пишет в него только владелец).
    """
    if config.OWNER_CHAT_ID:
        return int(config.OWNER_CHAT_ID)
    stored = get_setting(_OWNER_CHAT_KEY)
    return int(stored) if stored else None


def remember_owner_chat_id(chat_id: int) -> bool:
    """Запоминает чат владельца при первом обращении. True, если записали впервые."""
    if config.OWNER_CHAT_ID or get_setting(_OWNER_CHAT_KEY):
        return False
    set_setting(_OWNER_CHAT_KEY, str(chat_id))
    return True


_OWNER_USERNAME_KEY = "owner_username"


def get_owner_username() -> str:
    """@username владельца без @ — для кнопки «написать отзыв в личку»."""
    if config.OWNER_USERNAME:
        return config.OWNER_USERNAME.strip().lstrip("@")
    return (get_setting(_OWNER_USERNAME_KEY) or "").strip().lstrip("@")


def remember_owner_username(username: str) -> None:
    cleaned = (username or "").strip().lstrip("@")
    if cleaned:
        set_setting(_OWNER_USERNAME_KEY, cleaned)


_CLIENT_BOT_USERNAME_KEY = "client_bot_username"


def get_client_bot_username() -> str:
    """@username клиентского бота для реферальных ссылок (без @)."""
    if config.CLIENT_BOT_USERNAME:
        return config.CLIENT_BOT_USERNAME.strip().lstrip("@")
    return (get_setting(_CLIENT_BOT_USERNAME_KEY) or "").strip().lstrip("@")


def remember_client_bot_username(username: str) -> None:
    cleaned = (username or "").strip().lstrip("@")
    if cleaned:
        set_setting(_CLIENT_BOT_USERNAME_KEY, cleaned)


def remember_forwarded(owner_message_id: int, client_chat_id: int, client_username: str = "") -> None:
    """
    Запоминает, какому клиенту принадлежит пересланное владельцу сообщение,
    чтобы ответ реплаем ушёл именно этому человеку.
    """
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO forwarded (owner_message_id, client_chat_id, client_username)
            VALUES (?, ?, ?)
            ON CONFLICT(owner_message_id) DO UPDATE SET
                client_chat_id = excluded.client_chat_id,
                client_username = excluded.client_username
            """,
            (owner_message_id, client_chat_id, client_username or ""),
        )
        conn.commit()


def get_forwarded(owner_message_id: int) -> Optional[dict]:
    """Кому отвечать на реплай владельца. None, если сообщение не из пересланных."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT client_chat_id, client_username FROM forwarded WHERE owner_message_id = ?",
            (owner_message_id,),
        ).fetchone()
    if not row:
        return None
    return {"chat_id": row[0], "username": row[1]}
