"""
Реферальная программа: клиент приглашает друга своей ссылкой и оба получают
бонус, когда друг оформляет первый заказ (SQLite в постоянной папке DATA_DIR).

Приглашение привязано к @username друга, потому что связь с заказом идёт только
через него: в таблице заказов записан username, а не chat_id. Бонус начисляется
один раз и только за первый заказ — сам факт перехода по ссылке ничего не даёт,
иначе программу можно было бы накрутить пустыми регистрациями.
"""
import secrets
import sqlite3
from contextlib import closing
from typing import Optional

from bot import config

DB_PATH = config.data_path("referrals.sqlite")

# Без похожих друг на друга символов: код диктуют голосом и вводят руками.
_CODE_ALPHABET = "ACDEFGHJKLMNPQRTUVWXY34679"
_CODE_LENGTH = 6


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS codes (
            username TEXT PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            chat_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS invites (
            invitee_username TEXT PRIMARY KEY,
            invitee_chat_id INTEGER,
            invitee_name TEXT NOT NULL DEFAULT '',
            referrer_username TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            rewarded_at TEXT,
            order_number TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_invites_referrer ON invites(referrer_username)")
    return conn


def _normalize(username: str) -> str:
    return (username or "").strip().lstrip("@").lower()


def _generate_code(conn) -> str:
    """Свободный код. Коллизия на 26^6 маловероятна, но проверяем — код уникален в схеме."""
    for _ in range(20):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
        exists = conn.execute("SELECT 1 FROM codes WHERE code = ?", (code,)).fetchone()
        if not exists:
            return code
    raise RuntimeError("Не удалось подобрать свободный реферальный код")


def code_for(username: str, chat_id: Optional[int] = None) -> str:
    """Персональный код клиента: отдаёт существующий или создаёт новый."""
    key = _normalize(username)
    if not key:
        return ""
    with closing(_connect()) as conn:
        row = conn.execute("SELECT code FROM codes WHERE username = ?", (key,)).fetchone()
        if row:
            if chat_id is not None:
                conn.execute("UPDATE codes SET chat_id = ? WHERE username = ?", (chat_id, key))
                conn.commit()
            return row[0]

        code = _generate_code(conn)
        conn.execute(
            "INSERT INTO codes (username, code, chat_id) VALUES (?, ?, ?)",
            (key, code, chat_id),
        )
        conn.commit()
    return code


def username_by_code(code: str) -> Optional[str]:
    cleaned = (code or "").strip().upper()
    if not cleaned:
        return None
    with closing(_connect()) as conn:
        row = conn.execute("SELECT username FROM codes WHERE code = ?", (cleaned,)).fetchone()
    return row[0] if row else None


def get_invite(invitee_username: str) -> Optional[dict]:
    key = _normalize(invitee_username)
    if not key:
        return None
    with closing(_connect()) as conn:
        row = conn.execute(
            """
            SELECT invitee_username, invitee_chat_id, invitee_name,
                   referrer_username, rewarded_at, order_number
              FROM invites WHERE invitee_username = ?
            """,
            (key,),
        ).fetchone()
    if not row:
        return None
    return {
        "invitee_username": row[0],
        "invitee_chat_id": row[1],
        "invitee_name": row[2],
        "referrer_username": row[3],
        "rewarded_at": row[4],
        "order_number": row[5],
    }


def record_invite(
    code: str,
    invitee_username: str,
    invitee_chat_id: Optional[int] = None,
    invitee_name: str = "",
) -> Optional[str]:
    """
    Запоминает, что друг пришёл по коду. Возвращает @username пригласившего
    либо None, если приглашение не засчитано: код не найден, ссылка своя же
    или этого человека уже пригласили раньше.
    """
    invitee = _normalize(invitee_username)
    if not invitee:
        return None

    referrer = username_by_code(code)
    if not referrer or referrer == invitee:
        return None

    with closing(_connect()) as conn:
        cursor = conn.execute(
            """
            INSERT INTO invites (invitee_username, invitee_chat_id, invitee_name, referrer_username)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(invitee_username) DO NOTHING
            """,
            (invitee, invitee_chat_id, invitee_name or "", referrer),
        )
        conn.commit()
    return referrer if cursor.rowcount > 0 else None


def reward_for_order(invitee_username: str, order_number: str = "") -> Optional[dict]:
    """
    Начисляет бонус за первый заказ приглашённого. Возвращает
    {"referrer_username", "invitee_username", "invitee_name"} либо None,
    если этот клиент не приглашён или бонус уже был начислен.
    """
    invite = get_invite(invitee_username)
    if not invite or invite["rewarded_at"]:
        return None

    with closing(_connect()) as conn:
        cursor = conn.execute(
            """
            UPDATE invites
               SET rewarded_at = datetime('now'), order_number = ?
             WHERE invitee_username = ? AND rewarded_at IS NULL
            """,
            ((order_number or "").strip().upper(), invite["invitee_username"]),
        )
        conn.commit()

    if cursor.rowcount == 0:
        return None
    return {
        "referrer_username": invite["referrer_username"],
        "invitee_username": invite["invitee_username"],
        "invitee_name": invite["invitee_name"],
    }


def summary(username: str, chat_id: Optional[int] = None) -> dict:
    """
    Статистика для мини-аппа:
    {"code", "invited": перешли по ссылке, "rewarded": сделали первый заказ, "bonus": ₽}
    """
    key = _normalize(username)
    if not key:
        return {"code": "", "invited": 0, "rewarded": 0, "bonus": 0}

    code = code_for(key, chat_id)
    with closing(_connect()) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*), COUNT(rewarded_at)
              FROM invites WHERE referrer_username = ?
            """,
            (key,),
        ).fetchone()

    rewarded = row[1] or 0
    return {
        "code": code,
        "invited": row[0] or 0,
        "rewarded": rewarded,
        "bonus": rewarded * config.REFERRAL_BONUS,
    }


def invited_by(username: str) -> list:
    """Кого привёл клиент — для отчёта владельцу."""
    key = _normalize(username)
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT invitee_username, invitee_name, rewarded_at, order_number
              FROM invites WHERE referrer_username = ?
             ORDER BY created_at DESC
            """,
            (key,),
        ).fetchall()
    return [
        {
            "invitee_username": row[0],
            "invitee_name": row[1],
            "rewarded_at": row[2],
            "order_number": row[3],
        }
        for row in rows
    ]


def top_referrers(limit: int = 10) -> list:
    """Кто привёл больше всех клиентов, с оплаченными бонусами."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT referrer_username, COUNT(*), COUNT(rewarded_at)
              FROM invites
             GROUP BY referrer_username
             ORDER BY COUNT(rewarded_at) DESC, COUNT(*) DESC
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "username": row[0],
            "invited": row[1],
            "rewarded": row[2],
            "bonus": (row[2] or 0) * config.REFERRAL_BONUS,
        }
        for row in rows
    ]


def totals() -> dict:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT COUNT(*), COUNT(rewarded_at) FROM invites").fetchone()
    rewarded = row[1] or 0
    return {
        "invited": row[0] or 0,
        "rewarded": rewarded,
        "bonus": rewarded * config.REFERRAL_BONUS,
    }
