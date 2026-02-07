#!/usr/bin/env python3
"""
Capture webcam frames and send a single photo when the Capture button is pressed.
Client chooses character + fg/bg colors per cell and sends to server.
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
DRAW_CELLS_ENDPOINT = SERVER + "/drawcells"
SIZE_ENDPOINT = SERVER + "/size"
CLEAR_ENDPOINT = SERVER + "/clear"

# Throttle to avoid overwhelming the server.
FRAME_DELAY_SEC = 0.02
BATCH_SIZE = 200

# Quality controls
CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 720
GAMMA = 1.0
SHARPEN = True
WHITE_BALANCE = True
USE_SIMPLE_WB = True
SATURATION = 1.0
BRIGHTNESS = 1.0
COLOR_GAINS = (1.0, 1.0, 1.0)  # (B, G, R)
LINEARIZE_RESIZE = True
RESIZE_GAMMA = 2.2

# Preview window
SHOW_PREVIEW = True
PREVIEW_WIDTH = 480

QUAD_CHARS = [
    " ",  # 0
    "▘",  # 1 TL
    "▝",  # 2 TR
    "▀",  # 3 TL+TR
    "▖",  # 4 BL
    "▌",  # 5 TL+BL
    "▞",  # 6 TR+BL
    "▛",  # 7 TL+TR+BL
    "▗",  # 8 BR
    "▚",  # 9 TL+BR
    "▐",  # 10 TR+BR
    "▜",  # 11 TL+TR+BR
    "▄",  # 12 BL+BR
    "▙",  # 13 TL+BL+BR
    "▟",  # 14 TR+BL+BR
    "■",  # 15 all
]


def get_grid_size() -> Tuple[int, int]:
    try:
        r = requests.get(SIZE_ENDPOINT, timeout=2)
        r.raise_for_status()
        data = r.json()
        return int(data.get("width", 80)), int(data.get("height", 24))
    except Exception:
        return 80, 24


def send_cells(cells) -> None:
    payload = {"cells": cells}
    try:
        requests.post(
            DRAW_CELLS_ENDPOINT,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
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


def to_yuv(c):
    r, g, b = c
    y = 0.299 * r + 0.587 * g + 0.114 * b
    u = -0.168736 * r - 0.331264 * g + 0.5 * b
    v = 0.5 * r - 0.418688 * g - 0.081312 * b
    return y, u, v


def color_dist2(a, b):
    ya, ua, va = to_yuv(a)
    yb, ub, vb = to_yuv(b)
    dy = ya - yb
    du = ua - ub
    dv = va - vb
    return dy * dy * 2.0 + du * du + dv * dv


def average_color(colors):
    if not colors:
        return (0, 0, 0)
    r = sum(c[0] for c in colors) / len(colors)
    g = sum(c[1] for c in colors) / len(colors)
    b = sum(c[2] for c in colors) / len(colors)
    return (int(r + 0.5), int(g + 0.5), int(b + 0.5))


def pick_best_mask(quads):
    best_mask = 0
    best_fg = quads[0]
    best_bg = quads[0]
    best_err = None

    for mask in range(16):
        fg_set = []
        bg_set = []
        for i in range(4):
            if mask & (1 << i):
                fg_set.append(quads[i])
            else:
                bg_set.append(quads[i])

        fg = average_color(fg_set) if fg_set else average_color(quads)
        bg = average_color(bg_set) if bg_set else average_color(quads)

        err = 0.0
        for i in range(4):
            target = fg if (mask & (1 << i)) else bg
            err += color_dist2(quads[i], target)

        if best_err is None or err < best_err:
            best_err = err
            best_mask = mask
            best_fg = fg
            best_bg = bg

    return best_mask, best_fg, best_bg


def build_cells_from_frame(frame_bgr, width, height):
    # Resize to subpixel grid (2x2 per cell)
    sub_w = width * 2
    sub_h = height * 2

    if LINEARIZE_RESIZE:
        f = frame_bgr.astype(np.float32) / 255.0
        f = np.power(f, RESIZE_GAMMA)
        f = cv2.resize(f, (sub_w, sub_h), interpolation=cv2.INTER_AREA)
        f = np.power(np.clip(f, 0, 1), 1.0 / RESIZE_GAMMA)
        frame_small = (f * 255.0).astype(np.uint8)
    else:
        frame_small = cv2.resize(frame_bgr, (sub_w, sub_h), interpolation=cv2.INTER_AREA)

    frame_rgb = cv2.cvtColor(frame_small, cv2.COLOR_BGR2RGB)

    cells = []
    for y in range(height):
        y0 = y * 2
        for x in range(width):
            x0 = x * 2
            tl = tuple(int(v) for v in frame_rgb[y0, x0])
            tr = tuple(int(v) for v in frame_rgb[y0, x0 + 1])
            bl = tuple(int(v) for v in frame_rgb[y0 + 1, x0])
            br = tuple(int(v) for v in frame_rgb[y0 + 1, x0 + 1])

            mask, fg, bg = pick_best_mask([tl, tr, bl, br])
            ch = QUAD_CHARS[mask]
            cells.append({"x": x, "y": y, "ch": ch, "fg": list(fg), "bg": list(bg)})

    return cells


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
    capture_btn = None
    capture_requested = False
    captured_frame = None

    if SHOW_PREVIEW:
        root = tk.Tk()
        root.title("Camera Preview")
        label = tk.Label(root)
        label.pack()

        def on_capture():
            nonlocal capture_requested
            capture_requested = True

        capture_btn = tk.Button(root, text="Capture", command=on_capture)
        capture_btn.pack(pady=6)

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

    try:
        while True:
            if stop_event.is_set():
                break
            ret, frame = cap.read()
            if not ret:
                time.sleep(FRAME_DELAY_SEC)
                continue

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

            if capture_requested:
                captured_frame = frame.copy()
                capture_requested = False

            if captured_frame is not None:
                frame_to_send = captured_frame

                if WHITE_BALANCE and simple_wb is not None:
                    frame_to_send = simple_wb.balanceWhite(frame_to_send)
                elif WHITE_BALANCE:
                    b, g, r = cv2.split(frame_to_send)
                    b_avg = float(b.mean()) or 1.0
                    g_avg = float(g.mean()) or 1.0
                    r_avg = float(r.mean()) or 1.0
                    gray_avg = (b_avg + g_avg + r_avg) / 3.0
                    b = np.clip(b * (gray_avg / b_avg), 0, 255).astype(np.uint8)
                    g = np.clip(g * (gray_avg / g_avg), 0, 255).astype(np.uint8)
                    r = np.clip(r * (gray_avg / r_avg), 0, 255).astype(np.uint8)
                    frame_to_send = cv2.merge((b, g, r))

                if COLOR_GAINS != (1.0, 1.0, 1.0):
                    b, g, r = cv2.split(frame_to_send)
                    b = np.clip(b * COLOR_GAINS[0], 0, 255).astype(np.uint8)
                    g = np.clip(g * COLOR_GAINS[1], 0, 255).astype(np.uint8)
                    r = np.clip(r * COLOR_GAINS[2], 0, 255).astype(np.uint8)
                    frame_to_send = cv2.merge((b, g, r))

                if gamma_lut is not None:
                    frame_to_send = cv2.LUT(frame_to_send, gamma_lut)

                frame_to_send = adjust_saturation_brightness(frame_to_send)

                if SHARPEN:
                    blur = cv2.GaussianBlur(frame_to_send, (0, 0), 0.8)
                    frame_to_send = cv2.addWeighted(frame_to_send, 1.3, blur, -0.3, 0)

                cells = build_cells_from_frame(frame_to_send, width, height)

                batch = []
                for cell in cells:
                    batch.append(cell)
                    if len(batch) >= BATCH_SIZE:
                        send_cells(batch)
                        batch.clear()
                if batch:
                    send_cells(batch)

                captured_frame = None

            time.sleep(FRAME_DELAY_SEC)
    except KeyboardInterrupt:
        return 0
    finally:
        cap.release()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
