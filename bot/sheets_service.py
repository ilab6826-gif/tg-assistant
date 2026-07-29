"""
Запись заказов в Google Таблицу.

Колонки листа "Заказы" (в этом порядке):
1. Юзернейм в ТГ
2. Товар
3. Размер
4. Цвет
5. ФИО
6. Дата и время добавления (YYYY-MM-DD HH:MM:SS, в часовом поясе TIMEZONE)
7. Номер заказа (уникальный, вида A1042 - генерируется автоматически)
8. Статус (число 1-6, см. config.ORDER_STATUSES)
"""
import random
import string
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

from bot import config

_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_ORDER_NUMBER_COL = 7  # "Номер заказа"
_STATUS_COL = 8  # "Статус"
_HEADER_ROW = ["Юзернейм в ТГ", "Товар", "Размер", "Цвет", "ФИО", "Дата и время добавления",
               "Номер заказа", "Статус"]

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
    """
    Гарантирует, что в таблице есть колонки "Номер заказа" и "Статус" (7 и 8).
    Дописывает заголовки, если их ещё нет - чтобы не требовать ручной миграции таблицы.
    """
    current_header = worksheet.row_values(1)
    if len(current_header) >= _STATUS_COL and current_header[_ORDER_NUMBER_COL - 1] and current_header[_STATUS_COL - 1]:
        return
    worksheet.update(range_name="A1:H1", values=[_HEADER_ROW], value_input_option="USER_ENTERED")


def _existing_order_numbers(worksheet) -> set:
    values = worksheet.col_values(_ORDER_NUMBER_COL)[1:]  # без заголовка
    return {v.strip().upper() for v in values if v.strip()}


def generate_order_number() -> str:
    """Генерирует короткий уникальный номер заказа вида 'A1042'."""
    worksheet = _get_worksheet()
    existing = _existing_order_numbers(worksheet)
    for _ in range(100):
        candidate = f"{random.choice(string.ascii_uppercase)}{random.randint(1000, 9999)}"
        if candidate not in existing:
            return candidate
    raise RuntimeError("Не удалось сгенерировать уникальный номер заказа")


def append_order(
    username: str = "",
    product: str = "",
    size: str = "",
    color: str = "",
    full_name: str = "",
    order_number: str = "",
    status: int = 1,
) -> None:
    """Добавляет новую строку с заказом в конец таблицы."""
    worksheet = _get_worksheet()
    created_at = datetime.now(ZoneInfo(config.TIMEZONE)).strftime(_DATE_FORMAT)
    row = [
        username or "", product or "", size or "", color or "", full_name or "",
        created_at, order_number or "", str(status),
    ]
    worksheet.append_row(row, value_input_option="USER_ENTERED")


def _find_order_row(worksheet, order_number: str):
    """
    Ищет строку заказа по номеру (без учёта регистра/пробелов).
    Возвращает (row_index (1-based, с учётом заголовка), row_values) или (None, None).
    """
    target = order_number.strip().upper()
    rows = worksheet.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        cell = row[_ORDER_NUMBER_COL - 1].strip().upper() if len(row) >= _ORDER_NUMBER_COL else ""
        if cell == target:
            return i, row
    return None, None


def get_order_status(order_number: str) -> Optional[dict]:
    """
    Возвращает {"order_number": ..., "product": ..., "status": int} для заказа
    по его номеру, либо None, если заказ не найден.
    """
    worksheet = _get_worksheet()
    _, row = _find_order_row(worksheet, order_number)
    if row is None:
        return None
    product = row[1] if len(row) > 1 else ""
    raw_status = row[_STATUS_COL - 1] if len(row) >= _STATUS_COL else ""
    try:
        status = int(raw_status)
    except ValueError:
        status = 1
    return {"order_number": order_number.strip().upper(), "product": product, "status": status}


def change_order_status(order_number: str, new_status: int) -> str:
    """
    Обновляет статус заказа по номеру. Возвращает название товара (для ответа боту).
    Бросает ValueError, если статус вне диапазона 1-6 или заказ не найден.
    """
    new_status = int(new_status)
    if new_status not in range(1, len(config.ORDER_STATUSES) + 1):
        raise ValueError(f"Статус должен быть числом от 1 до {len(config.ORDER_STATUSES)}")

    worksheet = _get_worksheet()
    row_index, row = _find_order_row(worksheet, order_number)
    if row_index is None:
        raise ValueError(f"Заказ с номером {order_number} не найден")

    worksheet.update_cell(row_index, _STATUS_COL, str(new_status))
    return row[1] if len(row) > 1 else ""


def _all_orders() -> list:
    """
    Возвращает все заказы с распознанной датой добавления:
    [{"product": ..., "created_at": datetime}, ...]
    Строки без даты или с некорректным форматом (например, старые записи без
    6-й колонки) пропускаются - по ним нельзя посчитать статистику за период.
    """
    worksheet = _get_worksheet()
    rows = worksheet.get_all_values()[1:]  # первая строка - заголовок
    tz = ZoneInfo(config.TIMEZONE)

    orders = []
    for row in rows:
        if len(row) < 6 or not row[5]:
            continue
        try:
            created_at = datetime.strptime(row[5], _DATE_FORMAT).replace(tzinfo=tz)
        except ValueError:
            continue
        orders.append({"product": row[1] if len(row) > 1 else "", "created_at": created_at})
    return orders


def count_orders_today() -> int:
    """Считает, сколько заказов добавлено сегодня (по текущей дате)."""
    today = datetime.now(ZoneInfo(config.TIMEZONE)).date()
    return sum(1 for order in _all_orders() if order["created_at"].date() == today)


def weekly_stats() -> dict:
    """
    Сводка заказов за последние 7 дней:
    {"total": N, "top_products": [(товар, количество), ...]}
    """
    cutoff = datetime.now(ZoneInfo(config.TIMEZONE)) - timedelta(days=7)
    recent = [order for order in _all_orders() if order["created_at"] >= cutoff]
    top_products = Counter(order["product"] for order in recent if order["product"]).most_common(5)
    return {"total": len(recent), "top_products": top_products}


def _self_test() -> None:
    """Ручная проверка подключения к таблице (запусти файл напрямую)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    order_number = generate_order_number()
    append_order(
        username="@test_user",
        product=f"Тестовая запись ({ts})",
        size="-",
        color="-",
        full_name="Тест Тестов",
        order_number=order_number,
        status=1,
    )
    print(f"Тестовая строка успешно добавлена в таблицу. Номер заказа: {order_number}")


if __name__ == "__main__":
    _self_test()
