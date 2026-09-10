"""Локальный сервер для съёмки промо-ролика.

Отдаёт настоящий Mini App из webapp/ на /app/, сцену ролика на /promo/
и подменяет боевой API демо-заказами. Всё с одного origin, иначе сцена
не сможет управлять приложением внутри iframe.
"""

import argparse
import json
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STATUSES = [
    "Товар выкуплен",
    "Прибыл на склад в Китае",
    "Едет Китай → Москва",
    "Проходит таможенный досмотр",
    "Прибыл в Москву",
    "Передан в доставку",
    "Доставлен",
]

SNEAKER = "/promo/assets/promo-sneaker.png"
JACKET = "/promo/assets/promo-jacket.png"
BAG = "/promo/assets/promo-bag.png"


def _order(number, status, product, items, photos, created_at):
    return {
        "order_number": number,
        "product": product,
        "status": status,
        "status_label": STATUSES[status - 1],
        "statuses": STATUSES,
        "photos": photos,
        "items": items,
        "created_at": created_at,
    }


ORDERS = [
    _order(
        "A1042",
        3,
        "Кроссовки, белая кожа + куртка утеплённая",
        [
            {"product": "Кроссовки, белая кожа", "size": "42", "color": "Белый"},
            {"product": "Куртка утеплённая", "size": "M", "color": "Олива"},
            {"product": "Сумка дорожная, кожа", "size": "", "color": "Коньяк"},
        ],
        [SNEAKER, JACKET, BAG],
        "2026-08-21 12:30:00",
    ),
    _order(
        "B2287",
        5,
        "Куртка утеплённая",
        [{"product": "Куртка утеплённая", "size": "L", "color": "Олива"}],
        [JACKET],
        "2026-08-14 09:05:00",
    ),
    _order(
        "C3310",
        7,
        "Сумка дорожная, кожа",
        [{"product": "Сумка дорожная, кожа", "size": "", "color": "Коньяк"}],
        [BAG],
        "2026-07-29 17:40:00",
    ),
    _order(
        "D5518",
        1,
        "Кроссовки, белая кожа",
        [{"product": "Кроссовки, белая кожа", "size": "44", "color": "Белый"}],
        [SNEAKER],
        "2026-08-28 20:15:00",
    ),
]

PAYLOAD = {"user": {"first_name": "Артур"}, "orders": ORDERS, "needs_username": False}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *args):
        pass

    def _json(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/api/my-orders":
            return self._json(PAYLOAD)

        match = re.fullmatch(r"/api/status/(.+)", path)
        if match:
            wanted = match.group(1).upper()
            for order in ORDERS:
                if order["order_number"].upper() == wanted:
                    return self._json(order)
            return self._json({"detail": "not found"}, code=404)

        return super().do_GET()

    def translate_path(self, path):
        # Приложение грузит style.css и logo.png относительными путями,
        # поэтому оно должно жить в собственной папке /app/.
        if path.startswith("/app"):
            path = "/webapp" + path[len("/app"):]
        return super().translate_path(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8899)
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Сцена: http://127.0.0.1:{args.port}/promo/scene.html")
    server.serve_forever()


if __name__ == "__main__":
    main()
