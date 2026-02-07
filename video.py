#!/usr/bin/env python3
"""
Play an MP4 video and stream pixel data to the terminal pixel server.
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
DRAW_ENDPOINT = SERVER + "/draw"
SIZE_ENDPOINT = SERVER + "/size"
CLEAR_ENDPOINT = SERVER + "/clear"

BATCH_SIZE = 100
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


def resize_linear(frame, width, height):
    f = frame.astype(np.float32) / 255.0
    f = np.power(f, RESIZE_GAMMA)
    f = cv2.resize(f, (width, height), interpolation=cv2.INTER_AREA)
    f = np.power(np.clip(f, 0, 1), 1.0 / RESIZE_GAMMA)
    return (f * 255.0).astype(np.uint8)


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

            if LINEARIZE_RESIZE:
                frame_small = resize_linear(frame, width, height)
            else:
                frame_small = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)

            frame_rgb = cv2.cvtColor(frame_small, cv2.COLOR_BGR2RGB)

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

            time.sleep(frame_delay)
    finally:
        cap.release()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
