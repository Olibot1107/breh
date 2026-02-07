#!/usr/bin/env python3
"""
Capture webcam frames and stream pixel data to a terminal pixel server.
Sends a downscaled frame as per-cell RGB values.
"""

import json
import time
import sys
from typing import Tuple
from threading import Event

try:
    import cv2  # type: ignore
except Exception as exc:
    print("OpenCV (cv2) is required. Install with: pip install opencv-python", file=sys.stderr)
    raise

try:
    import numpy as np  # type: ignore
except Exception:
    print("numpy is required. Install with: pip install numpy", file=sys.stderr)
    raise

try:
    import requests  # type: ignore
except Exception:
    print("requests is required. Install with: pip install requests", file=sys.stderr)
    raise

try:
    from PIL import Image, ImageTk  # type: ignore
except Exception:
    print("Pillow is required for the preview window. Install with: pip install pillow", file=sys.stderr)
    raise

try:
    import tkinter as tk  # type: ignore
except Exception:
    print("tkinter is required for the preview window.", file=sys.stderr)
    raise

SERVER = "http://192.168.1.100:3000"
PIXEL_ENDPOINT = SERVER + "/pixel"
DRAW_ENDPOINT = SERVER + "/draw"
SIZE_ENDPOINT = SERVER + "/size"
CLEAR_ENDPOINT = SERVER + "/clear"

# Throttle to avoid overwhelming the server.
FRAME_DELAY_SEC = 0.10
BATCH_SIZE = 10000

# Quality controls
CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 720
GAMMA = 1.0
SHARPEN = False
WHITE_BALANCE = True
USE_SIMPLE_WB = True
USE_CLAHE = False
USE_DENOISE = False
COLOR_GAINS = (1.0, 1.0, 1.0)  # (B, G, R)
SHOW_PREVIEW = True
PREVIEW_WIDTH = 480


def get_grid_size() -> Tuple[int, int]:
    try:
        r = requests.get(SIZE_ENDPOINT, timeout=2)
        r.raise_for_status()
        data = r.json()
        return int(data.get("width", 80)), int(data.get("height", 24))
    except Exception:
        return 80, 24


def send_batch(pixels) -> None:
    payload = {"pixels": pixels}
    try:
        requests.post(DRAW_ENDPOINT, data=json.dumps(payload), headers={"Content-Type": "application/json"}, timeout=2)
    except Exception:
        pass


def clear_screen() -> None:
    try:
        requests.post(CLEAR_ENDPOINT, timeout=2)
    except Exception:
        pass


def main() -> int:
    stop_event = Event()

    root = None
    label = None
    if SHOW_PREVIEW:
        root = tk.Tk()
        root.title("Camera Preview")
        label = tk.Label(root)
        label.pack()

        def on_close():
            stop_event.set()
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", on_close)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Failed to open camera.", file=sys.stderr)
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)

    clear_screen()
    width, height = get_grid_size()

    if GAMMA != 1.0:
        inv = 1.0 / GAMMA
        lut = (np.linspace(0, 255, 256) / 255.0) ** inv
        gamma_lut = (lut * 255).astype("uint8")
    else:
        gamma_lut = None

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)) if USE_CLAHE else None
    simple_wb = None
    if USE_SIMPLE_WB and hasattr(cv2, "xphoto"):
        try:
            simple_wb = cv2.xphoto.createSimpleWB()
        except Exception:
            simple_wb = None

    try:
        while True:
            if stop_event.is_set():
                break
            ret, frame = cap.read()
            if not ret:
                time.sleep(FRAME_DELAY_SEC)
                continue

            if WHITE_BALANCE and simple_wb is not None:
                frame = simple_wb.balanceWhite(frame)
            elif WHITE_BALANCE:
                # Gray-world white balance in BGR space.
                b, g, r = cv2.split(frame)
                b_avg = float(b.mean()) or 1.0
                g_avg = float(g.mean()) or 1.0
                r_avg = float(r.mean()) or 1.0
                gray_avg = (b_avg + g_avg + r_avg) / 3.0
                b = np.clip(b * (gray_avg / b_avg), 0, 255).astype(np.uint8)
                g = np.clip(g * (gray_avg / g_avg), 0, 255).astype(np.uint8)
                r = np.clip(r * (gray_avg / r_avg), 0, 255).astype(np.uint8)
                frame = cv2.merge((b, g, r))

            if COLOR_GAINS != (1.0, 1.0, 1.0):
                b, g, r = cv2.split(frame)
                b = np.clip(b * COLOR_GAINS[0], 0, 255).astype(np.uint8)
                g = np.clip(g * COLOR_GAINS[1], 0, 255).astype(np.uint8)
                r = np.clip(r * COLOR_GAINS[2], 0, 255).astype(np.uint8)
                frame = cv2.merge((b, g, r))

            if USE_DENOISE:
                frame = cv2.bilateralFilter(frame, 5, 50, 50)

            if SHARPEN:
                blur = cv2.GaussianBlur(frame, (0, 0), 1.0)
                frame = cv2.addWeighted(frame, 1.5, blur, -0.5, 0)

            if gamma_lut is not None:
                frame = cv2.LUT(frame, gamma_lut)

            if clahe is not None:
                lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
                l, a, b = cv2.split(lab)
                l = clahe.apply(l)
                lab = cv2.merge((l, a, b))
                frame = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

            # Resize to terminal grid
            frame_small = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame_small, cv2.COLOR_BGR2RGB)

            if SHOW_PREVIEW and root is not None and label is not None:
                preview_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w = preview_rgb.shape[:2]
                scale = PREVIEW_WIDTH / float(w)
                preview_resized = cv2.resize(
                    preview_rgb, (PREVIEW_WIDTH, int(h * scale)), interpolation=cv2.INTER_AREA
                )
                image = Image.fromarray(preview_resized)
                photo = ImageTk.PhotoImage(image=image)
                label.configure(image=photo)
                label.image = photo
                root.update_idletasks()
                root.update()

            # Send in batches
            batch = []
            for y in range(height):
                row = frame_rgb[y]
                for x in range(width):
                    r, g, b = row[x]
                    batch.append({"x": x, "y": y, "r": int(r), "g": int(g), "b": int(b)})
                    if len(batch) >= BATCH_SIZE:
                        send_batch(batch)
                        batch.clear()
            if batch:
                send_batch(batch)

            time.sleep(FRAME_DELAY_SEC)
    except KeyboardInterrupt:
        return 0
    finally:
        cap.release()


if __name__ == "__main__":
    raise SystemExit(main())
