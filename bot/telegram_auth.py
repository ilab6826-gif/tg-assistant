"""
Проверка подлинности Telegram WebApp initData.

Mini App открывается из клиентского бота — для проверки подписи используется
CLIENT_BOT_TOKEN (не токен ассистента).
"""
import hashlib
import hmac
import json
from typing import Optional
from urllib.parse import parse_qsl


class TelegramAuthError(ValueError):
    pass


def _build_data_check_string(init_data: str) -> str:
    pairs = parse_qsl(init_data, keep_blank_values=True)
    filtered = [(k, v) for k, v in pairs if k != "hash"]
    filtered.sort(key=lambda item: item[0])
    return "\n".join(f"{k}={v}" for k, v in filtered)


def validate_init_data(init_data: str, bot_token: str) -> dict:
    """
    Проверяет HMAC-подпись initData и возвращает данные пользователя:
    {"id": int, "username": str|None, "first_name": str, ...}
    """
    if not init_data or not init_data.strip():
        raise TelegramAuthError("Не переданы данные авторизации Telegram")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.get("hash")
    if not received_hash:
        raise TelegramAuthError("Некорректные данные авторизации")

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key,
        _build_data_check_string(init_data).encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise TelegramAuthError("Подпись Telegram не прошла проверку")

    user_raw = pairs.get("user")
    if not user_raw:
        raise TelegramAuthError("Не удалось определить пользователя Telegram")

    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise TelegramAuthError("Некорректный профиль пользователя") from exc

    if "id" not in user:
        raise TelegramAuthError("Не удалось определить пользователя Telegram")

    return user


def username_from_user(user: dict) -> Optional[str]:
    username = user.get("username")
    return username.strip().lstrip("@") if username else None
