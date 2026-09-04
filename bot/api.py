"""
Веб-API трекера заказов + статика Mini App.

Клиентский бот открывает Mini App — заказы подтягиваются по Telegram @username
из Google Таблицы (колонка «Юзернейм в ТГ»), куда ассистент записывает заказы.
"""
import logging
import os
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

from bot import client_bot, config, photo_service, referrals_service, sheets_service
from bot.telegram_auth import TelegramAuthError, username_from_user, validate_init_data

logger = logging.getLogger(__name__)

app = FastAPI(title="PR0JECT Order Tracker API")

_WEBAPP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp")


def _status_label(status: int) -> str:
    index = status - 1
    if 0 <= index < len(config.ORDER_STATUSES):
        return config.ORDER_STATUSES[index]
    return ""


def _enrich_order(order: dict) -> dict:
    """Заказ для мини-приложения: товары, ссылки на фото и подпись статуса."""
    number = order["order_number"]
    photos = [
        f"/api/photo/{number}/{index}"
        for index in range(1, photo_service.count(number) + 1)
    ]
    items = [
        {
            "product": item["product"],
            "size": item["size"],
            "color": item["color"],
        }
        for item in order.get("items", [])
    ]
    track = order.get("tracking") or {}
    return {
        "order_number": number,
        "created_at": order.get("created_at", ""),
        "status": order["status"],
        "status_label": _status_label(order["status"]),
        "statuses": config.ORDER_STATUSES,
        "items": items,
        "product": order.get("product", ""),
        "photos": photos,
        "tracking": track.get("number") or "",
        "carrier": track.get("carrier_label") or "",
        "tracking_url": track.get("url") or "",
    }


def _require_client_bot_token() -> str:
    if not config.CLIENT_BOT_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Клиентский бот не настроен (CLIENT_BOT_TOKEN)",
        )
    return config.CLIENT_BOT_TOKEN


def _referral_payload(username: str) -> dict:
    data = referrals_service.summary(username)
    return {
        "code": data["code"],
        "link": client_bot.referral_link(data["code"]),
        "invited": data["invited"],
        "rewarded": data["rewarded"],
        "bonus": data["bonus"],
        "your_bonus": config.REFERRAL_BONUS,
        "friend_bonus": config.REFERRAL_FRIEND_BONUS,
        "share_text": (
            f"Заказываю вещи из Китая через {config.BRAND_NAME} — все заказы видно в приложении. "
            f"По этой ссылке тебе дадут скидку {config.REFERRAL_FRIEND_BONUS} ₽ на первый заказ"
        ),
    }


def _user_from_init_data(x_telegram_init_data: Optional[str]) -> dict:
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="Требуется авторизация через Telegram")
    try:
        return validate_init_data(x_telegram_init_data, _require_client_bot_token())
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/my-orders")
def get_my_orders(x_telegram_init_data: Optional[str] = Header(default=None, alias="X-Telegram-Init-Data")) -> dict:
    user = _user_from_init_data(x_telegram_init_data)
    username = username_from_user(user)
    if not username:
        return {
            "orders": [],
            "needs_username": True,
            "user": {"first_name": user.get("first_name", "")},
            "statuses": config.ORDER_STATUSES,
            "referral": None,
        }

    try:
        orders = sheets_service.get_orders_by_username(username)
    except Exception:
        logger.exception("Ошибка при получении заказов для @%s", username)
        raise HTTPException(status_code=502, detail="Не удалось получить данные из таблицы")

    return {
        "orders": [_enrich_order(order) for order in orders],
        "needs_username": False,
        "user": {
            "first_name": user.get("first_name", ""),
            "username": username,
        },
        "statuses": config.ORDER_STATUSES,
        "referral": _referral_payload(username),
    }


@app.get("/api/photo/{order_number}/{index}")
def get_photo(order_number: str, index: int):
    path = photo_service.path_for(order_number, index)
    if not path:
        raise HTTPException(status_code=404, detail="Фото не найдено")
    return FileResponse(path, media_type="image/jpeg")


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

    return _enrich_order(order)


if os.path.isdir(_WEBAPP_DIR):
    from fastapi.staticfiles import StaticFiles

    app.mount("/app", StaticFiles(directory=_WEBAPP_DIR, html=True), name="webapp")
else:
    logger.warning("Папка webapp/ не найдена — Mini App статика не смонтирована (%s)", _WEBAPP_DIR)
