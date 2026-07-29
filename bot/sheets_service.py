"""
Запись заказов в Google Таблицу.

Колонки листа "Заказы" (в этом порядке):
1. Юзернейм в ТГ
2. Товар
3. Размер
4. Цвет
5. ФИО
6. Дата и время добавления (YYYY-MM-DD HH:MM:SS, в часовом поясе TIMEZONE)
"""
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

from bot import config

_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_worksheet = None


def _get_worksheet():
    global _worksheet
    if _worksheet is None:
        creds = Credentials.from_service_account_file(
            config.GOOGLE_CREDENTIALS_FILE, scopes=_SCOPES
        )
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(config.GOOGLE_SHEET_ID)
        _worksheet = spreadsheet.worksheet(config.GOOGLE_SHEET_WORKSHEET)
    return _worksheet


def append_order(
    username: str = "",
    product: str = "",
    size: str = "",
    color: str = "",
    full_name: str = "",
) -> None:
    """Добавляет новую строку с заказом в конец таблицы."""
    worksheet = _get_worksheet()
    created_at = datetime.now(ZoneInfo(config.TIMEZONE)).strftime(_DATE_FORMAT)
    row = [username or "", product or "", size or "", color or "", full_name or "", created_at]
    worksheet.append_row(row, value_input_option="USER_ENTERED")


def _all_orders() -> list:
    """
    Возвращает все заказы с распознанной датой добавления:
    [{"product": ..., "created_at": datetime}, ...]
    Строки без даты или с некорректным форматом (например, старые записи без
    6-й колонки) пропускаются — по ним нельзя посчитать статистику за период.
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
    append_order(
        username="@test_user",
        product=f"Тестовая запись ({ts})",
        size="-",
        color="-",
        full_name="Тест Тестов",
    )
    print("Тестовая строка успешно добавлена в таблицу.")


if __name__ == "__main__":
    _self_test()
