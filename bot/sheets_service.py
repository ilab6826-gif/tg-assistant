"""
Запись заказов в Google Таблицу.

Одна строка листа — один товар. Заказ может состоять из нескольких товаров:
тогда в таблице лежит несколько строк с одним и тем же номером заказа, и они
склеиваются в один заказ при чтении. Статус и клиент у таких строк общие.

Колонки листа "Заказы" (в этом порядке):
1.  Юзернейм в ТГ
2.  Товар
3.  Размер
4.  Цвет
5.  ФИО
6.  Дата и время добавления (YYYY-MM-DD HH:MM:SS, в часовом поясе TIMEZONE)
7.  Номер заказа (уникальный, вида A1042 - генерируется автоматически)
8.  Статус (число от 1 до len(config.ORDER_STATUSES))
9.  Дата смены статуса (нужна, чтобы находить зависшие заказы)
10. Закупка (сколько потрачено на этот товар)
11. Продажа (сколько заплатил клиент за этот товар)
12. Фото (сколько фото приложено к заказу, сами файлы лежат в хранилище)
13. Трек (номер последней мили: «СДЭК 1234567890»)

Новые колонки дописываются автоматически при первом обращении, ручная
миграция таблицы не нужна.
"""
import random
import string
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

from bot import config, photo_service, tracking

_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_USERNAME_COL = 1
_PRODUCT_COL = 2
_SIZE_COL = 3
_COLOR_COL = 4
_FULL_NAME_COL = 5
_CREATED_AT_COL = 6
_ORDER_NUMBER_COL = 7
_STATUS_COL = 8
_STATUS_CHANGED_COL = 9
_COST_COL = 10
_SALE_COL = 11
_PHOTO_COL = 12
_TRACKING_COL = 13

_HEADER_ROW = [
    "Юзернейм в ТГ", "Товар", "Размер", "Цвет", "ФИО", "Дата и время добавления",
    "Номер заказа", "Статус", "Дата смены статуса", "Закупка", "Продажа", "Фото",
    "Трек",
]
_LAST_COL_LETTER = "M"

_worksheet = None


def _get_worksheet():
    global _worksheet
    if _worksheet is None:
        creds = Credentials.from_service_account_file(
            config.GOOGLE_CREDENTIALS_FILE, scopes=_SCOPES
        )
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(config.GOOGLE_SHEET_ID)
        worksheet = spreadsheet.worksheet(config.GOOGLE_SHEET_WORKSHEET)
        _ensure_headers(worksheet)
        _worksheet = worksheet
    return _worksheet


def _ensure_headers(worksheet) -> None:
    """Дописывает недостающие заголовки, сохраняя уже введённые вручную названия."""
    current = worksheet.row_values(1)
    if len(current) >= len(_HEADER_ROW) and all(cell.strip() for cell in current[:len(_HEADER_ROW)]):
        return

    merged = list(current) + [""] * (len(_HEADER_ROW) - len(current))
    merged = merged[:len(_HEADER_ROW)]
    for i, default in enumerate(_HEADER_ROW):
        if not merged[i].strip():
            merged[i] = default

    worksheet.update(
        range_name=f"A1:{_LAST_COL_LETTER}1",
        values=[merged],
        value_input_option="USER_ENTERED",
    )


def _now() -> str:
    return datetime.now(ZoneInfo(config.TIMEZONE)).strftime(_DATE_FORMAT)


def _cell(row: list, col: int) -> str:
    """Значение колонки (1-based) или пустая строка, если строка короче."""
    return row[col - 1] if len(row) >= col else ""


def _parse_money(raw: str) -> float:
    """Читает сумму из ячейки, прощая пробелы, ₽ и запятую вместо точки."""
    if not raw:
        return 0.0
    cleaned = "".join(ch for ch in str(raw).replace(",", ".") if ch.isdigit() or ch == ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _money_cell(value) -> str:
    """Пустая ячейка вместо нуля — чтобы таблица не пестрела нулями."""
    amount = float(value or 0)
    return str(amount) if amount else ""


def _parse_date(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, _DATE_FORMAT).replace(tzinfo=ZoneInfo(config.TIMEZONE))
    except ValueError:
        return None


def _normalize_username(username: str) -> str:
    return (username or "").strip().lstrip("@").lower()


def _parse_status(raw_status: str) -> int:
    try:
        return int(raw_status)
    except (TypeError, ValueError):
        return 1


def _item_from_row(row: list, row_index: Optional[int] = None) -> dict:
    cost = _parse_money(_cell(row, _COST_COL))
    sale = _parse_money(_cell(row, _SALE_COL))
    return {
        "product": _cell(row, _PRODUCT_COL),
        "size": _cell(row, _SIZE_COL),
        "color": _cell(row, _COLOR_COL),
        "cost_price": cost,
        "sale_price": sale,
        "profit": sale - cost,
        "row_index": row_index,
    }


def _summary(items: list) -> str:
    """Короткое название заказа для сообщений: «Nike Air Force + ещё 2 товара»."""
    names = [item["product"] for item in items if item["product"]]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]

    rest = len(names) - 1
    if rest % 10 == 1 and rest % 100 != 11:
        word = "товар"
    elif rest % 10 in (2, 3, 4) and rest % 100 not in (12, 13, 14):
        word = "товара"
    else:
        word = "товаров"
    return f"{names[0]} + ещё {rest} {word}"


def _merge_rows(rows: list) -> dict:
    """Строки одного заказа → единый заказ со списком товаров."""
    first_row, first_index = rows[0]
    items = [_item_from_row(row, index) for row, index in rows]

    created = [_cell(row, _CREATED_AT_COL) for row, _ in rows if _cell(row, _CREATED_AT_COL)]
    changed = [_cell(row, _STATUS_CHANGED_COL) for row, _ in rows if _cell(row, _STATUS_CHANGED_COL)]
    created_at = min(created) if created else ""

    cost = sum(item["cost_price"] for item in items)
    sale = sum(item["sale_price"] for item in items)

    return {
        "order_number": _cell(first_row, _ORDER_NUMBER_COL).strip().upper(),
        "username": next((_cell(row, _USERNAME_COL) for row, _ in rows if _cell(row, _USERNAME_COL)), ""),
        "full_name": next((_cell(row, _FULL_NAME_COL) for row, _ in rows if _cell(row, _FULL_NAME_COL)), ""),
        "created_at": created_at,
        "status": _parse_status(_cell(first_row, _STATUS_COL)),
        "status_changed_at": max(changed) if changed else created_at,
        "items": items,
        "product": _summary(items),
        "cost_price": cost,
        "sale_price": sale,
        "profit": sale - cost,
        "photo_count": int(_parse_money(_cell(first_row, _PHOTO_COL))),
        "tracking": next(
            (
                parsed for parsed in (
                    tracking.parse_cell(_cell(row, _TRACKING_COL)) for row, _ in rows
                )
                if parsed["number"]
            ),
            tracking.empty(),
        ),
        "row_indexes": [index for _, index in rows],
        "row_index": first_index,
    }


def _group(rows: list) -> list:
    """
    Строки листа (без заголовка) → список заказов.
    Порядок заказов — как в таблице, товары внутри заказа тоже.
    """
    grouped = {}
    for index, row in enumerate(rows, start=2):
        number = _cell(row, _ORDER_NUMBER_COL).strip().upper()
        if not number:
            continue
        grouped.setdefault(number, []).append((row, index))
    return [_merge_rows(order_rows) for order_rows in grouped.values()]


def _all_orders() -> list:
    """Все заказы таблицы (товары уже сгруппированы по номеру заказа)."""
    return _group(_get_worksheet().get_all_values()[1:])


def _by_created_desc(orders: list) -> list:
    orders.sort(key=lambda order: order.get("created_at") or "", reverse=True)
    return orders


def _existing_order_numbers(worksheet) -> set:
    values = worksheet.col_values(_ORDER_NUMBER_COL)[1:]  # без заголовка
    return {v.strip().upper() for v in values if v.strip()}


def generate_order_number() -> str:
    """
    Генерирует короткий уникальный номер заказа вида 'A1042'.
    Номера с фото в хранилище тоже пропускаем: если заказ удалили из таблицы,
    а его фото остались, новый заказ с тем же номером показал бы чужие снимки.
    """
    worksheet = _get_worksheet()
    existing = _existing_order_numbers(worksheet)
    for _ in range(100):
        candidate = f"{random.choice(string.ascii_uppercase)}{random.randint(1000, 9999)}"
        if candidate not in existing and not photo_service.count(candidate):
            return candidate
    raise RuntimeError("Не удалось сгенерировать уникальный номер заказа")


def _item_row(item: dict, username: str, full_name: str, order_number: str,
              status: int, now: str, photo: str = "", track: str = "") -> list:
    return [
        username or "", item.get("product", "") or "", item.get("size", "") or "",
        item.get("color", "") or "", full_name or "", now, order_number or "",
        str(status), now,
        _money_cell(item.get("cost_price")), _money_cell(item.get("sale_price")),
        photo, track,
    ]


def append_order(username: str = "", full_name: str = "", order_number: str = "",
                 items: Optional[list] = None, status: int = 1) -> None:
    """
    Добавляет заказ в таблицу: по строке на каждый товар, номер заказа общий.
    items: [{"product": ..., "size": ..., "color": ..., "cost_price": ..., "sale_price": ...}]
    """
    items = [item for item in (items or []) if item.get("product")]
    if not items:
        raise ValueError("В заказе нет ни одного товара")

    now = _now()
    rows = [
        _item_row(item, username, full_name, order_number, status, now)
        for item in items
    ]
    _get_worksheet().append_rows(rows, value_input_option="USER_ENTERED")


def add_items(order_number: str, items: Optional[list] = None) -> dict:
    """
    Дописывает товары в уже существующий заказ (клиент и статус берутся из него).
    Возвращает заказ целиком — вместе с только что добавленными товарами.
    """
    items = [item for item in (items or []) if item.get("product")]
    if not items:
        raise ValueError("Не понял, какие товары добавить в заказ")

    order = get_order(order_number)
    if order is None:
        raise ValueError(f"Заказ с номером {order_number} не найден")

    now = _now()
    track = tracking.format_cell(order.get("tracking") or tracking.empty())
    rows = [
        _item_row(item, order["username"], order["full_name"],
                  order["order_number"], order["status"], now, track=track)
        for item in items
    ]
    _get_worksheet().append_rows(rows, value_input_option="USER_ENTERED")

    added = [_item_from_row(row) for row in rows]
    order["items"] = order["items"] + added
    order["product"] = _summary(order["items"])
    order["cost_price"] += sum(item["cost_price"] for item in added)
    order["sale_price"] += sum(item["sale_price"] for item in added)
    order["profit"] = order["sale_price"] - order["cost_price"]
    return order


def _find_order_rows(worksheet, order_number: str) -> list:
    """Все строки заказа: [(row_index (1-based, с учётом заголовка), row_values)]."""
    target = order_number.strip().upper()
    rows = worksheet.get_all_values()
    return [
        (i, row) for i, row in enumerate(rows[1:], start=2)
        if _cell(row, _ORDER_NUMBER_COL).strip().upper() == target
    ]


def get_order(order_number: str) -> Optional[dict]:
    """Заказ целиком по номеру, либо None, если такого нет."""
    found = _find_order_rows(_get_worksheet(), order_number)
    if not found:
        return None
    return _merge_rows([(row, index) for index, row in found])


def get_orders_by_username(username: str) -> list:
    """
    Все заказы клиента по его Telegram @username (колонка «Юзернейм в ТГ»).
    Сравнение без учёта регистра и символа @. Новые заказы — первыми.
    """
    target = _normalize_username(username)
    if not target:
        return []

    return _by_created_desc([
        order for order in _all_orders()
        if _normalize_username(order["username"]) == target
    ])


def find_orders(query: str, limit: int = 15) -> list:
    """
    Поиск заказов по номеру, юзернейму, ФИО или названию товара.
    Нужен для вопросов вида «что там с A1042» или «покажи заказы @ivanov».
    """
    needle = (query or "").strip().lower().lstrip("@")
    if not needle:
        return []

    matches = []
    for order in _all_orders():
        haystack = " ".join([
            order["order_number"],
            _normalize_username(order["username"]),
            order["full_name"],
            (order.get("tracking") or {}).get("number") or "",
            (order.get("tracking") or {}).get("raw") or "",
            *(item["product"] for item in order["items"]),
        ]).lower()
        if needle in haystack:
            matches.append(order)

    return _by_created_desc(matches)[:limit]


def get_order_status(order_number: str) -> Optional[dict]:
    """Данные заказа по номеру для мини-приложения, либо None, если не найден."""
    return get_order(order_number)


def _validate_status(new_status) -> int:
    new_status = int(new_status)
    if new_status not in range(1, len(config.ORDER_STATUSES) + 1):
        raise ValueError(f"Статус должен быть числом от 1 до {len(config.ORDER_STATUSES)}")
    return new_status


def _status_updates(order: dict, new_status: int, now: str) -> list:
    """Ячейки статуса и даты смены для всех товаров заказа."""
    updates = []
    for row_index in order["row_indexes"]:
        updates.append({
            "range": gspread.utils.rowcol_to_a1(row_index, _STATUS_COL),
            "values": [[str(new_status)]],
        })
        updates.append({
            "range": gspread.utils.rowcol_to_a1(row_index, _STATUS_CHANGED_COL),
            "values": [[now]],
        })
    order["status"] = new_status
    order["status_changed_at"] = now
    return updates


def change_order_status(order_number: str, new_status: int) -> dict:
    """
    Обновляет статус заказа по номеру — сразу у всех его товаров. Возвращает
    данные заказа: username нужен, чтобы отправить клиенту пуш о новом статусе.
    Бросает ValueError, если статус вне допустимого диапазона или заказ не найден.
    """
    new_status = _validate_status(new_status)

    order = get_order(order_number)
    if order is None:
        raise ValueError(f"Заказ с номером {order_number} не найден")

    now = _now()
    _get_worksheet().batch_update(
        _status_updates(order, new_status, now), value_input_option="USER_ENTERED"
    )
    return order


def set_tracking(order_number: str, tracking_number: str, carrier: str = "") -> dict:
    """
    Записывает трек последней мили во все строки заказа.

    Если заказ ещё не на этапе «Передан в доставку», поднимает его туда —
    трек без этого этапа клиенту всё равно не нужен. Статус «Доставлен»
    и выше не трогаем.
    """
    parsed = tracking.parse(tracking_number, carrier)
    if not parsed["number"]:
        raise ValueError("Не указан трек-номер")

    order = get_order(order_number)
    if order is None:
        raise ValueError(f"Заказ с номером {order_number} не найден")

    cell = tracking.format_cell(parsed)
    updates = []
    for row_index in order["row_indexes"]:
        updates.append({
            "range": gspread.utils.rowcol_to_a1(row_index, _TRACKING_COL),
            "values": [[cell]],
        })

    status_changed = False
    if order["status"] < config.LAST_MILE_STATUS:
        updates.extend(_status_updates(order, config.LAST_MILE_STATUS, _now()))
        status_changed = True

    _get_worksheet().batch_update(updates, value_input_option="USER_ENTERED")
    order["tracking"] = parsed
    order["status_changed"] = status_changed
    return order


def change_orders_status_bulk(new_status: int, from_status: Optional[int] = None,
                              order_numbers: Optional[list] = None) -> list:
    """
    Меняет статус сразу у пачки заказов — либо у всех с определённым текущим
    статусом (from_status), либо у перечисленных номеров (order_numbers).
    Возвращает список обновлённых заказов, чтобы разослать клиентам уведомления.
    """
    new_status = _validate_status(new_status)
    if from_status is None and not order_numbers:
        raise ValueError("Укажи, какие заказы менять: текущий статус или список номеров")

    wanted_numbers = {n.strip().upper() for n in (order_numbers or []) if n and n.strip()}
    targets = []
    for order in _all_orders():
        if wanted_numbers and order["order_number"] not in wanted_numbers:
            continue
        if from_status is not None and order["status"] != int(from_status):
            continue
        if order["status"] == new_status:
            continue  # уже на этом этапе, зря клиента не дёргаем
        targets.append(order)

    if not targets:
        return []

    now = _now()
    updates = []
    for order in targets:
        updates.extend(_status_updates(order, new_status, now))

    _get_worksheet().batch_update(updates, value_input_option="USER_ENTERED")
    return targets


def set_photo_count(order_number: str, photos: int) -> None:
    """
    Отмечает в таблице, сколько фото приложено к заказу (сами файлы — в хранилище).
    Читает только колонку с номерами: фото приходят пачками, полное чтение листа
    на каждое было бы слишком дорогим.
    """
    worksheet = _get_worksheet()
    target = order_number.strip().upper()
    for index, value in enumerate(worksheet.col_values(_ORDER_NUMBER_COL)[1:], start=2):
        if value.strip().upper() == target:
            worksheet.update_cell(index, _PHOTO_COL, str(photos))
            return
    raise ValueError(f"Заказ с номером {order_number} не найден")


def stuck_orders(days: int = 10) -> list:
    """
    Заказы, которые дольше `days` дней висят на одном этапе и ещё не доставлены.
    Нужны, чтобы бот сам напоминал о том, что где-то застряло.
    """
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    last_status = len(config.ORDER_STATUSES)
    result = []

    for order in _all_orders():
        if order["status"] >= last_status:
            continue
        changed_at = _parse_date(order["status_changed_at"])
        if changed_at is None:
            continue
        idle_days = (now - changed_at).days
        if idle_days >= days:
            result.append({**order, "idle_days": idle_days})

    result.sort(key=lambda item: item["idle_days"], reverse=True)
    return result


def count_orders_today() -> int:
    """Считает, сколько заказов добавлено сегодня (по текущей дате)."""
    today = datetime.now(ZoneInfo(config.TIMEZONE)).date()
    count = 0
    for order in _all_orders():
        created = _parse_date(order["created_at"])
        if created and created.date() == today:
            count += 1
    return count


def active_orders_stats() -> dict:
    """
    Сколько заказов сейчас в работе (ещё не доставлены) и расклад по этапам.
    Доставленные считаются отдельно — чтобы было видно общую картину.
    """
    last_status = len(config.ORDER_STATUSES)
    by_status = Counter()
    active = 0
    delivered = 0

    for order in _all_orders():
        status = order["status"]
        if status >= last_status:
            delivered += 1
            continue
        active += 1
        by_status[status] += 1

    breakdown = []
    for status in range(1, last_status):
        count = by_status.get(status, 0)
        if not count:
            continue
        label = config.ORDER_STATUSES[status - 1]
        breakdown.append({"status": status, "label": label, "count": count})

    return {
        "active": active,
        "delivered": delivered,
        "total": active + delivered,
        "by_status": breakdown,
    }


def period_stats(days: int = 7) -> dict:
    """
    Сводка заказов за последние `days` дней:
    {"total": N, "top_products": [...], "revenue": ..., "cost": ..., "profit": ...}
    """
    cutoff = datetime.now(ZoneInfo(config.TIMEZONE)) - timedelta(days=days)

    recent = []
    for order in _all_orders():
        created = _parse_date(order["created_at"])
        if created and created >= cutoff:
            recent.append(order)

    revenue = sum(order["sale_price"] for order in recent)
    cost = sum(order["cost_price"] for order in recent)
    top_products = Counter(
        item["product"] for order in recent for item in order["items"] if item["product"]
    ).most_common(5)

    return {
        "total": len(recent),
        "top_products": top_products,
        "revenue": revenue,
        "cost": cost,
        "profit": revenue - cost,
        "with_money": sum(1 for order in recent if order["sale_price"] or order["cost_price"]),
    }


def weekly_stats() -> dict:
    """Сводка за последние 7 дней (используется в /stats и еженедельном дайджесте)."""
    return period_stats(7)


def _self_test() -> None:
    """Ручная проверка подключения к таблице (запусти файл напрямую)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    order_number = generate_order_number()
    append_order(
        username="@test_user",
        full_name="Тест Тестов",
        order_number=order_number,
        items=[
            {"product": f"Тестовая запись ({ts})", "size": "42", "color": "чёрный"},
            {"product": "Второй товар в том же заказе", "size": "M", "color": "синий"},
        ],
    )
    print(f"Тестовая строка успешно добавлена в таблицу. Номер заказа: {order_number}")


if __name__ == "__main__":
    _self_test()
