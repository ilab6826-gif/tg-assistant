"""
Хранилище истории переписки. Хранит последние сообщения по каждому chat_id
в SQLite (аналогично reminders.sqlite), чтобы Gemini видел контекст предыдущих
сообщений и чтобы история не терялась при перезапуске бота.
"""
import sqlite3
from contextlib import closing

from bot import config

DB_PATH = config.data_path("conversation_history.sqlite")
HISTORY_LIMIT = 10


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id, id)")
    return conn


def get_history(chat_id: int) -> list:
    """
    Возвращает последние сообщения чата в хронологическом порядке (от старых к новым):
    [{"role": "user"|"model", "text": "..."}, ...]
    """
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT role, text FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, HISTORY_LIMIT),
        ).fetchall()
    return [{"role": role, "text": text} for role, text in reversed(rows)]


def add_message(chat_id: int, role: str, text: str) -> None:
    """Сохраняет сообщение и обрезает историю чата до последних HISTORY_LIMIT записей."""
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO messages (chat_id, role, text) VALUES (?, ?, ?)",
            (chat_id, role, text),
        )
        conn.execute(
            """
            DELETE FROM messages
            WHERE chat_id = ? AND id NOT IN (
                SELECT id FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?
            )
            """,
            (chat_id, chat_id, HISTORY_LIMIT),
        )
        conn.commit()
