#!/usr/bin/env python3
"""
Play an MP4 video and stream cells (ch + fg/bg) to the terminal pixel server.
Usage: python3 video.py /path/to/video.mp4
"""

import json
import sys
import time
from typing import Tuple

try:
    import cv2  # type: ignore
except Exception:
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

SERVER = "http://192.168.1.100:3000"
DRAW_CELLS_ENDPOINT = SERVER + "/drawcells"
SIZE_ENDPOINT = SERVER + "/size"
CLEAR_ENDPOINT = SERVER + "/clear"

BATCH_SIZE = 200
LINEARIZE_RESIZE = True
RESIZE_GAMMA = 2.2

QUAD_CHARS = [
    " ", "▘", "▝", "▀", "▖", "▌", "▞", "▛",
    "▗", "▚", "▐", "▜", "▄", "▙", "▟", "■",
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


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python3 video.py /path/to/video.mp4", file=sys.stderr)
        return 1

    path = sys.argv[1]
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        print("Failed to open video.", file=sys.stderr)
        return 1

    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    frame_delay = 1.0 / max(fps, 1.0)

    clear_screen()
    width, height = get_grid_size()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            cells = build_cells_from_frame(frame, width, height)
            batch = []
            for cell in cells:
                batch.append(cell)
                if len(batch) >= BATCH_SIZE:
                    send_cells(batch)
                    batch.clear()
            if batch:
                send_cells(batch)

            time.sleep(frame_delay)
    finally:
        cap.release()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
