#!/usr/bin/env python3
"""
Capture webcam frames and stream pixel data to a terminal pixel server.
Sends a downscaled frame as per-cell RGB values.
"""

import json
import time
import sys
from typing import Tuple

try:
    import cv2  # type: ignore
except Exception as exc:
    print("OpenCV (cv2) is required. Install with: pip install opencv-python", file=sys.stderr)
    raise

try:
    import requests  # type: ignore
except Exception:
    print("requests is required. Install with: pip install requests", file=sys.stderr)
    raise

SERVER = "http://192.168.1.100:3000"
PIXEL_ENDPOINT = SERVER + "/pixel"
DRAW_ENDPOINT = SERVER + "/draw"
SIZE_ENDPOINT = SERVER + "/size"
CLEAR_ENDPOINT = SERVER + "/clear"

# Throttle to avoid overwhelming the server.
FRAME_DELAY_SEC = 0.10
BATCH_SIZE = 100


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
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Failed to open camera.", file=sys.stderr)
        return 1

    clear_screen()
    width, height = get_grid_size()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                time.sleep(FRAME_DELAY_SEC)
                continue

            # Resize to terminal grid
            frame_small = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame_small, cv2.COLOR_BGR2RGB)

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
