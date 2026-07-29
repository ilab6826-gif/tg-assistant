"""
Веб-API трекера заказов + статика Mini App.

Работает в том же процессе, что и Telegram-бот (см. bot/main.py, который
поднимает uvicorn в отдельном потоке). Отдельный HTTP-сервис нужен, чтобы
Telegram Mini App (frontend в webapp/) мог получать статус заказа по номеру
без доступа к Google Таблице напрямую.
"""
import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from bot import config, sheets_service

logger = logging.getLogger(__name__)

app = FastAPI(title="Order Tracker API")

_WEBAPP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/status/{order_number}")
def get_status(order_number: str) -> dict:
    order_number = order_number.strip()
    if not order_number:
        raise HTTPException(status_code=400, detail="Не указан номер заказа")

    try:
        order = sheets_service.get_order_status(order_number)
    except Exception:
        logger.exception("Ошибка при получении статуса заказа %s", order_number)
        raise HTTPException(status_code=502, detail="Не удалось получить данные из таблицы")

    if order is None:
        raise HTTPException(status_code=404, detail="Заказ с таким номером не найден")

    status_index = order["status"] - 1
    status_label = (
        config.ORDER_STATUSES[status_index]
        if 0 <= status_index < len(config.ORDER_STATUSES)
        else ""
    )
    return {**order, "status_label": status_label, "statuses": config.ORDER_STATUSES}


if os.path.isdir(_WEBAPP_DIR):
    app.mount("/app", StaticFiles(directory=_WEBAPP_DIR, html=True), name="webapp")
else:
    logger.warning("Папка webapp/ не найдена — Mini App статика не смонтирована (%s)", _WEBAPP_DIR)
