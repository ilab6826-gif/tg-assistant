"""
Хранение фото товаров.

На один заказ можно приложить сколько угодно фото — они лежат в постоянной
папке DATA_DIR/photos/<НОМЕР ЗАКАЗА>/1.jpg, 2.jpg ... и отдаются мини-приложению
через /api/photo/{номер заказа}/{номер фото}. Telegram-овский file_id для этого
не годится: браузер клиента не может скачать файл по нему напрямую.
"""
import logging
import os
import re

from bot import config

logger = logging.getLogger(__name__)

PHOTO_DIR = config.data_path("photos")
_SAFE_ORDER_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _clean(order_number: str) -> str:
    """Номер заказа, пригодный для имени папки, либо пустая строка."""
    cleaned = (order_number or "").strip().upper()
    return cleaned if _SAFE_ORDER_RE.match(cleaned) else ""


def _order_dir(order_number: str) -> str:
    cleaned = _clean(order_number)
    return os.path.join(PHOTO_DIR, cleaned) if cleaned else ""


def list_photos(order_number: str) -> list:
    """
    Имена файлов фото заказа по порядку добавления.
    Учитывает и старый формат, когда фото было одно и лежало как <ЗАКАЗ>.jpg.
    """
    cleaned = _clean(order_number)
    if not cleaned:
        return []

    names = []
    legacy = os.path.join(PHOTO_DIR, f"{cleaned}.jpg")
    if os.path.isfile(legacy):
        names.append(f"{cleaned}.jpg")

    folder = _order_dir(cleaned)
    if os.path.isdir(folder):
        indexed = []
        for entry in os.listdir(folder):
            stem, ext = os.path.splitext(entry)
            if ext.lower() == ".jpg" and stem.isdigit():
                indexed.append((int(stem), f"{cleaned}/{entry}"))
        names.extend(name for _, name in sorted(indexed))

    return names


def count(order_number: str) -> int:
    return len(list_photos(order_number))


def add(order_number: str, data: bytes) -> int:
    """Сохраняет ещё одно фото заказа и возвращает общее число фото."""
    folder = _order_dir(order_number)
    if not folder:
        raise ValueError(f"Некорректный номер заказа: {order_number}")

    os.makedirs(folder, exist_ok=True)
    used = [
        int(os.path.splitext(entry)[0])
        for entry in os.listdir(folder)
        if os.path.splitext(entry)[0].isdigit()
    ]
    next_index = max(used, default=0) + 1

    with open(os.path.join(folder, f"{next_index}.jpg"), "wb") as f:
        f.write(data)
    return count(order_number)


def path_for(order_number: str, index: int) -> str:
    """
    Путь к N-му фото заказа (нумерация с 1), либо пустая строка, если такого нет.
    Имя файла собирается из проверенного номера заказа, выйти из папки нельзя.
    """
    names = list_photos(order_number)
    if index < 1 or index > len(names):
        return ""
    full_path = os.path.join(PHOTO_DIR, names[index - 1])
    return full_path if os.path.isfile(full_path) else ""
