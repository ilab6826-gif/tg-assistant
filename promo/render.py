"""Покадровый рендер промо-ролика.

Поднимает локальный сервер с демо-данными, открывает сцену в Chromium и
для каждого кадра вызывает seek(t) — сцена детерминирована, поэтому съёмка
может идти медленнее реального времени без потери плавности.

    venv/bin/python promo/render.py                    # собрать MP4
    venv/bin/python promo/render.py --stills 0,4,9     # кадры на проверку
    venv/bin/python promo/render.py --scene homescreen --format vertical
"""

import argparse
import io
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "promo" / "out"

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".pw-browsers"))

from PIL import Image  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def wait_for_port(port, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def start_server(port):
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "promo" / "mock_server.py"), "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not wait_for_port(port):
        proc.terminate()
        raise RuntimeError("мок-сервер не поднялся")
    return proc


SCENES = {
    "tracker": {
        "page": "scene.html",
        "formats": {
            "wide": {"size": (1280, 720), "out": "pr0ject-miniapp.mp4"},
            "vertical": {"size": (720, 1280), "out": "pr0ject-miniapp-9x16.mp4"},
        },
    },
    "homescreen": {
        "page": "homescreen.html",
        "formats": {
            "wide": {"size": (1280, 720), "out": "pr0ject-homescreen.mp4"},
            "vertical": {"size": (720, 1280), "out": "pr0ject-homescreen-9x16.mp4"},
        },
    },
}


def open_scene(playwright, port, width, height, scale, layout, page_name):
    browser = playwright.chromium.launch(args=["--force-color-profile=srgb", "--font-render-hinting=none"])
    page = browser.new_page(
        viewport={"width": width, "height": height},
        device_scale_factor=scale,
        reduced_motion="reduce",
    )
    page.goto(
        f"http://127.0.0.1:{port}/promo/{page_name}?format={layout}",
        wait_until="networkidle",
    )

    page.wait_for_function("window.promoReady && window.promoReady()", timeout=20000)
    page.wait_for_function(
        "document.getElementById('screen').contentDocument"
        ".querySelectorAll('.order-item').length >= 4",
        timeout=20000,
    )
    page.evaluate("document.fonts.ready")
    page.evaluate(
        "document.getElementById('screen').contentWindow.document.fonts.ready"
    )
    # Фото из галереи должны лежать в кэше до съёмки, иначе они «всплывут»
    # посреди сцены и один-два кадра выйдут пустыми.
    page.evaluate(
        """() => Promise.all(
            ['/promo/assets/promo-sneaker.png',
             '/promo/assets/promo-jacket.png',
             '/promo/assets/promo-bag.png'].map(src => new Promise(res => {
                const img = new Image();
                img.onload = img.onerror = res;
                img.src = src;
             }))
        )"""
    )
    time.sleep(0.6)
    return browser, page


def frame_bytes(page, t):
    page.evaluate(
        """t => { window.seek(t);
                  return new Promise(r => requestAnimationFrame(
                      () => requestAnimationFrame(r))); }""",
        t,
    )
    return page.screenshot(type="png")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--scale", type=float, default=1.5, help="1.5 => 1920x1080")
    parser.add_argument("--stills", default="", help="секунды через запятую вместо видео")
    parser.add_argument("--format", default="wide", choices=("wide", "vertical"))
    parser.add_argument("--scene", default="tracker", choices=sorted(SCENES))
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    scene = SCENES[args.scene]
    layout = scene["formats"][args.format]
    width, height = layout["size"]
    out_name = args.out or layout["out"]
    out_w, out_h = int(width * args.scale), int(height * args.scale)

    server = start_server(args.port)
    try:
        with sync_playwright() as playwright:
            browser, page = open_scene(
                playwright, args.port, width, height, args.scale, args.format, scene["page"]
            )
            total = page.evaluate("window.promoTotal")
            scenes = page.evaluate("window.promoScenes")

            if args.stills:
                stamps = [float(x) for x in args.stills.split(",") if x.strip()]
                for stamp in stamps:
                    data = frame_bytes(page, stamp)
                    path = OUT / f"still-{args.scene}-{args.format}-{stamp:06.2f}.png"
                    path.write_bytes(data)
                    print(f"кадр {stamp:5.2f}s -> {path.name}")
                browser.close()
                return

            import imageio_ffmpeg

            frames = int(round(total * args.fps))
            print(f"хронометраж {total:.1f}s, кадров {frames}, {out_w}x{out_h}")
            for scene in scenes:
                print(f"  {scene['start']:5.1f}s  {scene['name']}")

            # Пишем в отдельный файл и переименовываем в конце: прерванный
            # рендер иначе оставляет вместо готового ролика битый огрызок.
            target = OUT / out_name
            partial = OUT / (out_name + ".part.mp4")

            writer = imageio_ffmpeg.write_frames(
                str(partial),
                size=(out_w, out_h),
                fps=args.fps,
                codec="libx264",
                quality=None,
                macro_block_size=1,
                pix_fmt_in="rgb24",
                pix_fmt_out="yuv420p",
                ffmpeg_log_level="error",
                output_params=["-crf", "17", "-preset", "slow", "-movflags", "+faststart"],
            )
            writer.send(None)

            started = time.time()
            for i in range(frames):
                data = frame_bytes(page, i / args.fps)
                img = Image.open(io.BytesIO(data)).convert("RGB")
                if img.size != (out_w, out_h):
                    img = img.resize((out_w, out_h), Image.LANCZOS)
                writer.send(img.tobytes())

                if i % 60 == 0 and i:
                    done = i / frames
                    left = (time.time() - started) / done * (1 - done)
                    print(f"  {done * 100:5.1f}%  осталось ~{left / 60:.1f} мин", flush=True)

            writer.close()
            browser.close()
            partial.replace(target)

        size_mb = target.stat().st_size / 1024 / 1024
        print(f"готово: {target} ({size_mb:.1f} МБ)")
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
