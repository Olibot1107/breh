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
DRAW_ENDPOINT = SERVER + "/draw"
SIZE_ENDPOINT = SERVER + "/size"
CLEAR_ENDPOINT = SERVER + "/clear"

# Throttle to avoid overwhelming the server.
FRAME_DELAY_SEC = 0.08
BATCH_SIZE = 100

# Quality controls
CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 720
GAMMA = 1.0
SHARPEN = True
WHITE_BALANCE = True
USE_SIMPLE_WB = True
USE_DENOISE = False
SATURATION = 1.0
BRIGHTNESS = 1.0
COLOR_GAINS = (1.0, 1.0, 1.0)  # (B, G, R)
LINEARIZE_RESIZE = True
RESIZE_GAMMA = 2.2
TEMPORAL_SMOOTHING = 0.25  # 0 disables, 0.1-0.3 reduces noise/flicker

# Preview window
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


def adjust_saturation_brightness(frame_bgr):
    if SATURATION == 1.0 and BRIGHTNESS == 1.0:
        return frame_bgr
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    h, s, v = cv2.split(hsv)
    s = np.clip(s * SATURATION, 0, 255)
    v = np.clip(v * BRIGHTNESS, 0, 255)
    hsv = cv2.merge((h, s, v)).astype(np.uint8)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def get_source_from_args():
    if len(sys.argv) <= 1:
        return 0
    arg = sys.argv[1]
    if arg in ("--camera", "camera"):
        return 0
    return arg


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

    source = get_source_from_args()
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print("Failed to open camera/video source.", file=sys.stderr)
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
    if hasattr(cv2, "CAP_PROP_AUTO_WB"):
        cap.set(cv2.CAP_PROP_AUTO_WB, 1)

    clear_screen()
    width, height = get_grid_size()

    if GAMMA != 1.0:
        inv = 1.0 / GAMMA
        lut = (np.linspace(0, 255, 256) / 255.0) ** inv
        gamma_lut = (lut * 255).astype("uint8")
    else:
        gamma_lut = None

    simple_wb = None
    if USE_SIMPLE_WB and hasattr(cv2, "xphoto"):
        try:
            simple_wb = cv2.xphoto.createSimpleWB()
        except Exception:
            simple_wb = None

    prev_frame = None

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

            if gamma_lut is not None:
                frame = cv2.LUT(frame, gamma_lut)

            frame = adjust_saturation_brightness(frame)

            if TEMPORAL_SMOOTHING > 0:
                if prev_frame is None:
                    prev_frame = frame.astype(np.float32)
                else:
                    prev_frame = prev_frame * (1.0 - TEMPORAL_SMOOTHING) + frame.astype(np.float32) * TEMPORAL_SMOOTHING
                frame = prev_frame.astype(np.uint8)

            if USE_DENOISE:
                frame = cv2.bilateralFilter(frame, 5, 50, 50)

            if SHARPEN:
                blur = cv2.GaussianBlur(frame, (0, 0), 0.8)
                frame = cv2.addWeighted(frame, 1.3, blur, -0.3, 0)

            # Resize to terminal subpixel grid (linearized to preserve detail)
            if LINEARIZE_RESIZE:
                f = frame.astype(np.float32) / 255.0
                f = np.power(f, RESIZE_GAMMA)
                f = cv2.resize(f, (width, height), interpolation=cv2.INTER_AREA)
                f = np.power(np.clip(f, 0, 1), 1.0 / RESIZE_GAMMA)
                frame_small = (f * 255.0).astype(np.uint8)
            else:
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
