#!/usr/bin/env python3
"""
Capture the primary screen and stream whole frames to the terminal server.
"""

import json
import sys
import time
from typing import Tuple

try:
    import mss  # type: ignore
except Exception:
    print("mss is required. Install with: pip install mss", file=sys.stderr)
    raise

try:
    import numpy as np  # type: ignore
except Exception:
    print("numpy is required. Install with: pip install numpy", file=sys.stderr)
    raise

try:
    import cv2  # type: ignore
except Exception:
    print("opencv-python is required. Install with: pip install opencv-python", file=sys.stderr)
    raise

try:
    import requests  # type: ignore
except Exception:
    print("requests is required. Install with: pip install requests", file=sys.stderr)
    raise

SERVER = "http://192.168.1.100:3000"
FRAME_ENDPOINT = SERVER + "/frame"
SIZE_ENDPOINT = SERVER + "/size"
CLEAR_ENDPOINT = SERVER + "/clear"

FRAME_DELAY_SEC = 0.0
LINEARIZE_RESIZE = True
RESIZE_GAMMA = 2.2


def get_grid_size() -> Tuple[int, int]:
    try:
        r = requests.get(SIZE_ENDPOINT, timeout=2)
        r.raise_for_status()
        data = r.json()
        return int(data.get("width", 80)), int(data.get("height", 24))
    except Exception:
        return 80, 24


def send_frame(rows) -> None:
    payload = {"rows": rows}
    try:
        requests.post(
            FRAME_ENDPOINT,
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


def linear_resize(frame_bgr, width, height):
    if not LINEARIZE_RESIZE:
        return cv2.resize(frame_bgr, (width, height), interpolation=cv2.INTER_AREA)
    f = frame_bgr.astype(np.float32) / 255.0
    f = np.power(f, RESIZE_GAMMA)
    f = cv2.resize(f, (width, height), interpolation=cv2.INTER_AREA)
    f = np.power(np.clip(f, 0, 1), 1.0 / RESIZE_GAMMA)
    return (f * 255.0).astype(np.uint8)


def compress_row_rgb(row):
    # Run-length encode row: same RGB -> single run
    runs = []
    if row.size == 0:
        return runs
    prev = row[0]
    count = 1
    for px in row[1:]:
        if (px == prev).all():
            count += 1
        else:
            runs.append({"count": int(count), "ch": "■", "fg": [int(prev[0]), int(prev[1]), int(prev[2])], "bg": [0, 0, 0]})
            prev = px
            count = 1
    runs.append({"count": int(count), "ch": "■", "fg": [int(prev[0]), int(prev[1]), int(prev[2])], "bg": [0, 0, 0]})
    return runs


def main() -> int:
    clear_screen()
    width, height = get_grid_size()

    with mss.mss() as sct:
        monitor = sct.monitors[1]
        while True:
            img = np.array(sct.grab(monitor))  # BGRA
            frame_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            frame_small = linear_resize(frame_bgr, width, height)
            frame_rgb = cv2.cvtColor(frame_small, cv2.COLOR_BGR2RGB)

            rows = []
            for y in range(height):
                row = frame_rgb[y]
                rows.append({"runs": compress_row_rgb(row)})

            send_frame(rows)
            time.sleep(FRAME_DELAY_SEC)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
