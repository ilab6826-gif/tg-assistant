"""
Загрузка последних постов ПУБЛИЧНОГО Telegram-канала через веб-превью
(t.me/s/<username>) - не требует авторизации и токенов Telegram API.

Ограничения:
- Работает только для публичных каналов (не для приватных/закрытых)
- Показывает примерно последние ~20 постов (столько отдаёт превью-страница)
"""
import re

import requests
from bs4 import BeautifulSoup

_USERNAME_RE = re.compile(r"(?:t\.me/(?:s/)?|@)([A-Za-z0-9_]{4,})")


def extract_username(text_or_link: str) -> "str | None":
    """Достаёт username канала из ссылки вида t.me/name, t.me/s/name или @name."""
    match = _USERNAME_RE.search(text_or_link)
    return match.group(1) if match else None


def fetch_channel_posts(username: str, limit: int = 15) -> str:
    """
    Возвращает текст последних постов канала одной строкой (посты разделены "---").
    Бросает ValueError, если канал не найден или закрыт.
    """
    url = f"https://t.me/s/{username}"
    response = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    if response.status_code != 200:
        raise ValueError(f"Не удалось загрузить канал @{username} (код {response.status_code})")

    soup = BeautifulSoup(response.text, "html.parser")
    message_blocks = soup.select(".tgme_widget_message_text")

    if not message_blocks:
        raise ValueError(
            f"Не нашёл постов у @{username} — возможно, канал приватный или не существует."
        )

    texts = [block.get_text(separator=" ", strip=True) for block in message_blocks[-limit:]]
    return "\n---\n".join(texts)
