"""
Трек последней мили: СДЭК, Яндекс, Почта и остальные.

В таблице хранится одной ячейкой, например «СДЭК 1234567890». Отсюда же
собирается ссылка «Отследить» для Mini App и пуша клиенту.
"""
from typing import Optional

# key, подпись в UI, алиасы (нижний регистр), шаблон ссылки.
_CARRIERS = (
    (
        "cdek",
        "СДЭК",
        ("сдэк", "cdek", "сдек", "сдэком", "сдеком"),
        "https://www.cdek.ru/ru/tracking?order_id={number}",
    ),
    (
        "yandex",
        "Яндекс Доставка",
        ("яндекс", "yandex", "янд", "яндексом"),
        "https://dostavka.yandex.ru/tracking?track_id={number}",
    ),
    (
        "pochta",
        "Почта России",
        ("почта", "pochta", "russianpost", "russian post"),
        "https://www.pochta.ru/tracking#{number}",
    ),
    (
        "dpd",
        "DPD",
        ("dpd",),
        "https://tracking.dpd.ru/?parcelNumber={number}",
    ),
    (
        "boxberry",
        "Boxberry",
        ("boxberry", "боксберри", "boxbery"),
        "https://boxberry.ru/tracking-page?id={number}",
    ),
    (
        "fivepost",
        "5Post",
        ("5post", "fivepost", "пятьпост", "5 пост"),
        "https://fivepost.ru/?tracking={number}",
    ),
    (
        "magictrans",
        "Magic Trans",
        (
            "magic trans", "magic-trans", "magictrans", "magic",
            "мейджик транс", "мейджик-транс", "мейджик",
            "меджик транс", "меджик", "мэджик транс", "мэджик",
        ),
        "https://magic-trans.ru/otsledit-gruz/?act-no={number}",
    ),
)


def _match_carrier(raw: str) -> Optional[tuple]:
    needle = (raw or "").strip().lower().replace("ё", "е")
    if not needle:
        return None
    first = needle.split()[0].rstrip(".:")
    for carrier in _CARRIERS:
        key, label, aliases, url = carrier
        if first in aliases:
            return carrier
        for alias in aliases:
            if needle == alias or needle.startswith(alias + " ") or needle.startswith(alias + ":"):
                return carrier
    return None


def carrier_key(raw: str) -> str:
    found = _match_carrier(raw)
    return found[0] if found else ""


def carrier_label(key_or_raw: str) -> str:
    found = _match_carrier(key_or_raw)
    if found:
        return found[1]
    by_key = next((item for item in _CARRIERS if item[0] == (key_or_raw or "").strip().lower()), None)
    return by_key[1] if by_key else (key_or_raw or "").strip()


def tracking_url(number: str, carrier: str) -> str:
    if not number:
        return ""
    found = _match_carrier(carrier) or next(
        (item for item in _CARRIERS if item[0] == (carrier or "").strip().lower()),
        None,
    )
    if not found:
        return ""
    return found[3].format(number=number)


def _strip_carrier_prefix(text: str, carrier: tuple) -> str:
    """Срезает название службы с начала строки, начиная с самой длинной формы."""
    _key, label, aliases, _url = carrier
    rest = (text or "").strip()
    prefixes = (label, *aliases)
    for prefix in sorted(prefixes, key=len, reverse=True):
        if not prefix:
            continue
        lowered = rest.lower().replace("ё", "е")
        needle = prefix.lower().replace("ё", "е")
        if lowered.startswith(needle):
            return rest[len(prefix):].lstrip(" :.-")
    return rest


def _clean_number(raw: str) -> str:
    """Оставляет буквы, цифры и дефис — остальное (пробелы, №) выкидываем."""
    return "".join(ch for ch in (raw or "") if ch.isalnum() or ch in "-_")


def parse(tracking_number: str = "", carrier: str = "") -> dict:
    """
    Разбирает то, что написал владелец, в структуру для таблицы и клиента.

    «СДЭК 1234567890», отдельно carrier='СДЭК' и номер, или просто номер.
    """
    number_raw = (tracking_number or "").strip()
    carrier_raw = (carrier or "").strip()

    matched = _match_carrier(number_raw) or _match_carrier(carrier_raw)
    if matched:
        if not carrier_raw:
            carrier_raw = matched[1]
        number_raw = _strip_carrier_prefix(number_raw, matched)

    key = carrier_key(carrier_raw) or (matched[0] if matched else "")
    label = carrier_label(key or carrier_raw)
    number = _clean_number(number_raw)

    raw = f"{label} {number}".strip() if label and number else number
    return {
        "raw": raw,
        "number": number,
        "carrier": key,
        "carrier_label": label if key else (label if carrier_raw else ""),
        "url": tracking_url(number, key),
    }


def empty() -> dict:
    return {"raw": "", "number": "", "carrier": "", "carrier_label": "", "url": ""}


def parse_cell(raw: str) -> dict:
    value = (raw or "").strip()
    if not value:
        return empty()
    return parse(value)


def format_cell(parsed: dict) -> str:
    number = (parsed or {}).get("number") or ""
    if not number:
        return ""
    label = (parsed or {}).get("carrier_label") or ""
    if label:
        return f"{label} {number}"
    return number
