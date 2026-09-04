"""
Отзывы клиентов о доставленных заказах (SQLite в постоянной папке DATA_DIR).

Когда заказ переходит в последний статус, клиентский бот просит оценку, а затем
фото заказа с комментарием в подписи. Запись создаётся в момент запроса — по ней
же проверяется, что мы уже спрашивали, иначе массовая смена статуса разослала бы
просьбу повторно.
"""
import os
import sqlite3
from contextlib import closing
from typing import Optional

from bot import config

DB_PATH = config.data_path("reviews.sqlite")
PHOTO_DIR = config.data_path("review_photos")

# Оценка, ниже которой отзыв считается жалобой и уходит владельцу как проблема.
LOW_RATING = 3


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reviews (
            order_number TEXT PRIMARY KEY,
            username TEXT NOT NULL DEFAULT '',
            chat_id INTEGER,
            rating INTEGER,
            comment TEXT NOT NULL DEFAULT '',
            photo_path TEXT NOT NULL DEFAULT '',
            asked_at TEXT NOT NULL DEFAULT (datetime('now')),
            rated_at TEXT
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(reviews)")}
    if "photo_path" not in columns:
        conn.execute("ALTER TABLE reviews ADD COLUMN photo_path TEXT NOT NULL DEFAULT ''")
    # Ждём фото/комментарий: пока запись здесь есть, следующее сообщение клиента
    # — это отзыв, а не вопрос менеджеру.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS awaiting_comment (
            chat_id INTEGER PRIMARY KEY,
            order_number TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    return conn


def _row_to_review(row) -> dict:
    return {
        "order_number": row[0],
        "username": row[1],
        "chat_id": row[2],
        "rating": row[3],
        "comment": row[4],
        "photo_path": row[5],
        "rated_at": row[6],
    }


def mark_asked(order_number: str, username: str = "", chat_id: Optional[int] = None) -> bool:
    """Регистрирует запрос отзыва. False, если по этому заказу уже спрашивали."""
    number = (order_number or "").strip().upper()
    if not number:
        return False
    with closing(_connect()) as conn:
        cursor = conn.execute(
            """
            INSERT INTO reviews (order_number, username, chat_id)
            VALUES (?, ?, ?)
            ON CONFLICT(order_number) DO NOTHING
            """,
            (number, username or "", chat_id),
        )
        conn.commit()
    return cursor.rowcount > 0


def save_rating(order_number: str, rating: int) -> None:
    number = (order_number or "").strip().upper()
    with closing(_connect()) as conn:
        conn.execute(
            """
            UPDATE reviews
               SET rating = ?, rated_at = datetime('now')
             WHERE order_number = ?
            """,
            (int(rating), number),
        )
        conn.commit()


def save_comment(order_number: str, comment: str) -> None:
    number = (order_number or "").strip().upper()
    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE reviews SET comment = ? WHERE order_number = ?",
            (comment or "", number),
        )
        conn.commit()


def save_photo(order_number: str, data: bytes) -> str:
    """Сохраняет фото отзыва и возвращает путь к файлу."""
    number = (order_number or "").strip().upper()
    if not number:
        raise ValueError("Некорректный номер заказа")
    os.makedirs(PHOTO_DIR, exist_ok=True)
    path = os.path.join(PHOTO_DIR, f"{number}.jpg")
    with open(path, "wb") as handle:
        handle.write(data)
    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE reviews SET photo_path = ? WHERE order_number = ?",
            (path, number),
        )
        conn.commit()
    return path


def get(order_number: str) -> Optional[dict]:
    number = (order_number or "").strip().upper()
    with closing(_connect()) as conn:
        row = conn.execute(
            """
            SELECT order_number, username, chat_id, rating, comment, photo_path, rated_at
              FROM reviews WHERE order_number = ?
            """,
            (number,),
        ).fetchone()
    return _row_to_review(row) if row else None


def expected_order(chat_id: int) -> Optional[str]:
    """Номер заказа, к которому сейчас ждём фото/комментарий. Не снимает ожидание."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT order_number FROM awaiting_comment WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return row[0] if row else None


def expect_comment(chat_id: int, order_number: str) -> None:
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO awaiting_comment (chat_id, order_number) VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                order_number = excluded.order_number,
                created_at = excluded.created_at
            """,
            (chat_id, (order_number or "").strip().upper()),
        )
        conn.commit()


def cancel_expected_comment(chat_id: int) -> None:
    with closing(_connect()) as conn:
        conn.execute("DELETE FROM awaiting_comment WHERE chat_id = ?", (chat_id,))
        conn.commit()


def recent(limit: int = 10) -> list:
    """Оценённые отзывы, новые первыми."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT order_number, username, chat_id, rating, comment, photo_path, rated_at
              FROM reviews
             WHERE rating IS NOT NULL
             ORDER BY rated_at DESC
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_review(row) for row in rows]


def stats() -> dict:
    """{"asked": сколько раз спросили, "rated": сколько ответили, "with_photo": ..., "average": средняя}"""
    with closing(_connect()) as conn:
        asked = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        row = conn.execute(
            "SELECT COUNT(*), AVG(rating) FROM reviews WHERE rating IS NOT NULL"
        ).fetchone()
        with_photo = conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE photo_path != ''"
        ).fetchone()[0]
    return {
        "asked": asked,
        "rated": row[0],
        "with_photo": with_photo,
        "average": row[1] or 0.0,
    }
