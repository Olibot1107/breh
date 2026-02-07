#!/usr/bin/env python3
"""Network Tetris: renders to server.js via /drawcells."""

import curses
import time
import random
import json
import sys
from typing import Tuple

try:
    import requests  # type: ignore
except Exception:
    print("requests is required. Install with: pip install requests", file=sys.stderr)
    raise

SERVER = "http://192.168.1.100:3000"
DRAW_CELLS_ENDPOINT = SERVER + "/drawcells"
SIZE_ENDPOINT = SERVER + "/size"
CLEAR_ENDPOINT = SERVER + "/clear"

WIDTH = 12
HEIGHT = 22
BLOCK_W = 2
BLOCK_H = 2
TICK_START = 0.5
TICK_MIN = 0.08
TICK_DECAY = 0.995
BATCH_SIZE = 300

# Tetromino shapes and colors (RGB)
SHAPES = [
    ([[1, 1, 1, 1]], (0, 255, 255)),     # I
    ([[1, 1], [1, 1]], (255, 255, 0)),    # O
    ([[0, 1, 0], [1, 1, 1]], (160, 0, 240)),  # T
    ([[1, 0, 0], [1, 1, 1]], (0, 0, 255)),    # J
    ([[0, 0, 1], [1, 1, 1]], (255, 165, 0)),  # L
    ([[0, 1, 1], [1, 1, 0]], (0, 255, 0)),    # S
    ([[1, 1, 0], [0, 1, 1]], (255, 0, 0)),    # Z
]

BG_COLOR = (0, 0, 0)
BORDER_COLOR = (90, 90, 90)
TEXT_COLOR = (220, 220, 220)
GHOST_COLOR = (120, 120, 120)


def random_piece():
    shape, color = random.choice(SHAPES)
    return shape, color


def send_cells(cells):
    payload = {"cells": cells}
    try:
        requests.post(
            DRAW_CELLS_ENDPOINT,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=3,
        )
    except Exception:
        pass


def clear_screen():
    try:
        requests.post(CLEAR_ENDPOINT, timeout=2)
    except Exception:
        pass


def get_grid_size() -> Tuple[int, int]:
    try:
        r = requests.get(SIZE_ENDPOINT, timeout=2)
        r.raise_for_status()
        data = r.json()
        return int(data.get("width", 80)), int(data.get("height", 24))
    except Exception:
        return 80, 24


def rotate(shape):
    return [list(row) for row in zip(*shape[::-1])]


def new_piece(next_queue):
    shape, color = next_queue.pop(0)
    next_queue.append(random_piece())
    return shape, color, WIDTH // 2 - len(shape[0]) // 2, 0


def collision(board, shape, ox, oy):
    for y, row in enumerate(shape):
        for x, cell in enumerate(row):
            if cell:
                nx = ox + x
                ny = oy + y
                if nx < 0 or nx >= WIDTH or ny >= HEIGHT:
                    return True
                if ny >= 0 and board[ny][nx]:
                    return True
    return False


def lock_piece(board, shape, color, ox, oy):
    for y, row in enumerate(shape):
        for x, cell in enumerate(row):
            if cell:
                nx = ox + x
                ny = oy + y
                if 0 <= ny < HEIGHT:
                    board[ny][nx] = color


def clear_lines(board):
    new_board = [row for row in board if not all(row)]
    cleared = HEIGHT - len(new_board)
    for _ in range(cleared):
        new_board.insert(0, [None] * WIDTH)
    return new_board, cleared


def draw_block(cells, x, y, color):
    for dy in range(BLOCK_H):
        for dx in range(BLOCK_W):
            cells.append({
                "x": x + dx,
                "y": y + dy,
                "ch": "■",
                "fg": list(color),
                "bg": list(BG_COLOR),
            })


def draw_frame(board, shape, color, ox, oy, score, level, term_w, term_h, next_queue):
    # Compute offsets to center the playfield in terminal
    field_w = WIDTH * BLOCK_W + 2
    field_h = HEIGHT * BLOCK_H + 2
    off_x = max(0, (term_w - field_w) // 2)
    off_y = max(0, (term_h - field_h) // 2)

    cells = []

    # Border
    for x in range(field_w):
        cells.append({"x": off_x + x, "y": off_y, "ch": "■", "fg": list(BORDER_COLOR), "bg": list(BG_COLOR)})
        cells.append({"x": off_x + x, "y": off_y + field_h - 1, "ch": "■", "fg": list(BORDER_COLOR), "bg": list(BG_COLOR)})
    for y in range(1, field_h - 1):
        cells.append({"x": off_x, "y": off_y + y, "ch": "■", "fg": list(BORDER_COLOR), "bg": list(BG_COLOR)})
        cells.append({"x": off_x + field_w - 1, "y": off_y + y, "ch": "■", "fg": list(BORDER_COLOR), "bg": list(BG_COLOR)})

    # Compute ghost (landing) position
    ghost_y = oy
    while not collision(board, shape, ox, ghost_y + 1):
        ghost_y += 1

    # Board + ghost + active piece
    for y in range(HEIGHT):
        for x in range(WIDTH):
            cell_color = board[y][x]
            # Overlay active piece
            px = x - ox
            py = y - oy
            if 0 <= py < len(shape) and 0 <= px < len(shape[0]) and shape[py][px]:
                cell_color = color
            else:
                # Ghost piece (only if cell empty)
                gpx = x - ox
                gpy = y - ghost_y
                if 0 <= gpy < len(shape) and 0 <= gpx < len(shape[0]) and shape[gpy][gpx]:
                    if cell_color is None:
                        cell_color = GHOST_COLOR

            if cell_color:
                draw_block(cells, off_x + 1 + x * BLOCK_W, off_y + 1 + y * BLOCK_H, cell_color)
            else:
                # Clear empty area
                for dy in range(BLOCK_H):
                    for dx in range(BLOCK_W):
                        cells.append({
                            "x": off_x + 1 + x * BLOCK_W + dx,
                            "y": off_y + 1 + y * BLOCK_H + dy,
                            "ch": " ",
                            "fg": list(TEXT_COLOR),
                            "bg": list(BG_COLOR),
                        })

    # HUD (top-left corner)
    hud_x = max(0, off_x + field_w + 2)
    hud_y = off_y
    hud = [
        f"Score: {score}",
        f"Level: {level}",
        "Q: Quit",
        "Arrows/WASD",
        "Space: Rotate",
        "F: Drop",
    ]
    for i, line in enumerate(hud):
        for j, ch in enumerate(line[: max(0, term_w - hud_x - 1)]):
            cells.append({"x": hud_x + j, "y": hud_y + i, "ch": ch, "fg": list(TEXT_COLOR), "bg": list(BG_COLOR)})

    # Next 3 preview (as shapes)
    preview_x = hud_x
    preview_y = hud_y + len(hud) + 1
    for i in range(3):
        shape_i, color_i = next_queue[i]
        # label
        label = "Next:" if i == 0 else ""
        for j, ch in enumerate(label):
            cells.append({"x": preview_x + j, "y": preview_y - 1 if i == 0 else preview_y, "ch": ch, "fg": list(TEXT_COLOR), "bg": list(BG_COLOR)})

        # draw shape
        for sy, row in enumerate(shape_i):
            for sx, cell in enumerate(row):
                if cell:
                    draw_block(cells, preview_x + sx * BLOCK_W, preview_y + sy * BLOCK_H, color_i)
                else:
                    for dy in range(BLOCK_H):
                        for dx in range(BLOCK_W):
                            cells.append({
                                "x": preview_x + sx * BLOCK_W + dx,
                                "y": preview_y + sy * BLOCK_H + dy,
                                "ch": " ",
                                "fg": list(TEXT_COLOR),
                                "bg": list(BG_COLOR),
                            })
        preview_y += (len(shape_i) * BLOCK_H) + 2

    # Send in batches
    batch = []
    for c in cells:
        batch.append(c)
        if len(batch) >= BATCH_SIZE:
            send_cells(batch)
            batch.clear()
    if batch:
        send_cells(batch)


def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(0)

    term_w, term_h = get_grid_size()
    clear_screen()

    board = [[None] * WIDTH for _ in range(HEIGHT)]
    next_queue = [random_piece(), random_piece(), random_piece()]
    shape, color, ox, oy = new_piece(next_queue)
    score = 0
    level = 1
    tick = TICK_START
    last = time.time()

    while True:
        now = time.time()
        if now - last >= tick:
            last = now
            if not collision(board, shape, ox, oy + 1):
                oy += 1
            else:
                lock_piece(board, shape, color, ox, oy)
                board, cleared = clear_lines(board)
                if cleared:
                    score += (cleared ** 2) * 100
                    level = 1 + score // 1000
                    tick = max(TICK_MIN, tick * (TICK_DECAY ** cleared))
                shape, color, ox, oy = new_piece(next_queue)
                if collision(board, shape, ox, oy):
                    draw_frame(board, shape, color, ox, oy, score, level, term_w, term_h, next_queue)
                    return

        ch = stdscr.getch()
        if ch != -1:
            if ch in (ord("q"), ord("Q")):
                return
            elif ch in (curses.KEY_LEFT, ord("a")):
                if not collision(board, shape, ox - 1, oy):
                    ox -= 1
            elif ch in (curses.KEY_RIGHT, ord("d")):
                if not collision(board, shape, ox + 1, oy):
                    ox += 1
            elif ch in (curses.KEY_DOWN, ord("s")):
                if not collision(board, shape, ox, oy + 1):
                    oy += 1
            elif ch in (curses.KEY_UP, ord("w"), ord(" ")):
                rotated = rotate(shape)
                if not collision(board, rotated, ox, oy):
                    shape = rotated
            elif ch in (ord("f"),):
                while not collision(board, shape, ox, oy + 1):
                    oy += 1

        draw_frame(board, shape, color, ox, oy, score, level, term_w, term_h, next_queue)
        time.sleep(0.01)


def run():
    curses.wrapper(main)


if __name__ == "__main__":
    run()
