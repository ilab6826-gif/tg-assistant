"""
Запись заказов в Google Таблицу.

Колонки листа "Заказы" (в этом порядке):
1. Юзернейм в ТГ
2. Товар
3. Размер
4. Цвет
5. ФИО
"""
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from bot import config

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
    row = [username or "", product or "", size or "", color or "", full_name or ""]
    worksheet.append_row(row, value_input_option="USER_ENTERED")


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
