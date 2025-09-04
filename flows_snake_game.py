# -*- coding: utf-8 -*-
"""
flows_snake_game.py — BẢN TEST PHÂN TÍCH (không điều khiển)
- Lưới cố định theo thông số bạn cung cấp:
    x0=123, y0=470, cell_w=cell_h=50; x+=50 mỗi cột; y+=50 mỗi hàng
- Nhận diện đầu rắn & mồi bằng TEMPLATE (head.png, baits.png) trong ROI lưới.
- Vật cản: phân loại tĩnh 1 lần bằng màu (nhẹ), lưu blocked_mask.
- Mỗi tick 0.1s:
    + tìm head/food quanh ô cũ ±2 ô (rất nhanh). Mất dấu N tick → quét ROI.
    + tính đường H→F (BFS 4 hướng), in first_step, vẽ overlay.
"""

from __future__ import annotations
import os, time, math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Optional, Literal, Deque
from collections import deque

import cv2
import numpy as np

from module import (
    grab_screen_np, find_on_frame, sleep_coop, free_img,
    log_wk as _log, resource_path
)

# ========= Lưới cố định =========
GRID_X0 = 123
GRID_Y0 = 470
CELL_W  = 50
CELL_H  = 50
# Nếu bạn biết chắc rows/cols, gán cứng; nếu không, đo theo nền:
LOCK_ROWS = None   # ví dụ 12
LOCK_COLS = None   # ví dụ 12

# ========= Ảnh mẫu =========
IMG_HEAD  = resource_path("images/snake/head.png")
IMG_BAIT  = resource_path("images/snake/baits.png")
# IMG_ICE   = resource_path("images/snake/ice.png")  # không dùng mặc định

# ========= Thông số quét =========
THR_HEAD  = 0.86
THR_BAIT  = 0.86
SCAN_INTERVAL = 0.10     # 10Hz
DUMP_EVERY   = 1.0       # lưu overlay mỗi 1s
DEBUG_DIR    = "debug"

# Khi có last-cell, chỉ quét vùng ±R ô (nhẹ). Mất dấu liên tiếp -> mở rộng.
SEARCH_RADIUS_CELLS = 2
HEAD_LOST_LIMIT = 6      # 6 tick (≈0.6s) không thấy → quét cả ROI
BAIT_LOST_LIMIT = 10     # 10 tick (≈1.0s) không thấy → quét cả ROI

Label = Literal["E", "O", "H", "F"]
def _rc1(rc: tuple[int, int] | None) -> str:
    """Hiển thị (row,col) theo 1-based để khớp mắt thường."""
    if not rc:
        return "None"
    return f"({rc[0]+1}, {rc[1]+1})"

def L(wk, msg: str) -> None:
    _log(wk, f"[SNAKE] {msg}")

@dataclass
class Grid:
    x0: int
    y0: int
    rows: int
    cols: int
    cw: int
    ch: int

# ---------- Grid helpers ----------
def _is_board_color(h: float, s: float, v: float) -> bool:
    # nền sân xanh/cyan nhạt
    return (75.0 <= h <= 140.0) and (s >= 30.0)

def _measure_rows_cols(frame: np.ndarray, x0: int, y0: int, cw: int, ch: int) -> Tuple[int, int]:
    h, w = frame.shape[:2]
    def center_hsv(cx: int, cy: int) -> Tuple[float,float,float]:
        x1=max(0,cx-4); x2=min(w,cx+4); y1=max(0,cy-4); y2=min(h,cy+4)
        patch = frame[y1:y2, x1:x2]
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        med = np.median(hsv.reshape(-1,3), axis=0).astype(float)
        return float(med[0]), float(med[1]), float(med[2])

    # cols
    cy = y0 + ch//2
    cols = 0
    for c in range(1, 50):  # safe bound
        cx = x0 + c*cw - cw//2
        if cx >= w: break
        h_,s_,v_ = center_hsv(cx, cy)
        if _is_board_color(h_, s_, v_): cols += 1
        else: break
    cols = max(1, cols)

    # rows
    cx = x0 + cw//2
    rows = 0
    for r in range(1, 50):
        cy = y0 + r*ch - ch//2
        if cy >= h: break
        h_,s_,v_ = center_hsv(cx, cy)
        if _is_board_color(h_, s_, v_): rows += 1
        else: break
    rows = max(1, rows)
    return rows, cols

def _grid_roi(grid: Grid) -> Tuple[int,int,int,int]:
    return (grid.x0, grid.y0, grid.x0 + grid.cols*grid.cw, grid.y0 + grid.rows*grid.ch)

def _clamp(v:int, lo:int, hi:int)->int:
    return lo if v<lo else hi if v>hi else v

def cell_of_xy(grid: Grid, x: int, y: int) -> Tuple[int,int]:
    r = (y - grid.y0) // grid.ch
    c = (x - grid.x0) // grid.cw
    return (_clamp(int(r), 0, grid.rows-1), _clamp(int(c), 0, grid.cols-1))

def region_of_cell_band(grid: Grid, rc: Tuple[int,int], radius: int) -> Tuple[int,int,int,int]:
    r,c = rc
    r1 = _clamp(r - radius, 0, grid.rows-1)
    c1 = _clamp(c - radius, 0, grid.cols-1)
    r2 = _clamp(r + radius + 1, 0, grid.rows)
    c2 = _clamp(c + radius + 1, 0, grid.cols)
    x1 = grid.x0 + c1*grid.cw
    y1 = grid.y0 + r1*grid.ch
    x2 = grid.x0 + c2*grid.cw
    y2 = grid.y0 + r2*grid.ch
    return (x1,y1,x2,y2)

# ---------- Static obstacle detection (1 lần) ----------
def _estimate_bg_hsv(roi_bgr: np.ndarray) -> Tuple[float,float,float]:
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    med = np.median(hsv.reshape(-1,3), axis=0).astype(float)
    return float(med[0]), float(med[1]), float(med[2])

def _classify_obstacles_once(frame: np.ndarray, grid: Grid) -> np.ndarray:
    """Phân loại O/E tĩnh dựa nền (nhẹ) cho TẤT CẢ ô. Không tìm head/food ở đây."""
    labels = np.full((grid.rows, grid.cols), "E", dtype=object)
    x1,y1,x2,y2 = _grid_roi(grid)
    bg = _estimate_bg_hsv(frame[y1:y2, x1:x2])

    for r in range(grid.rows):
        for c in range(grid.cols):
            cx1 = grid.x0 + c*grid.cw; cy1 = grid.y0 + r*grid.ch
            cx2 = cx1 + grid.cw;       cy2 = cy1 + grid.ch
            cell = frame[cy1:cy2, cx1:cx2]
            hsv  = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
            H = float(np.mean(hsv[:,:,0])); S = float(np.mean(hsv[:,:,1])); V = float(np.mean(hsv[:,:,2]))
            dh = abs(H - bg[0]); ds = abs(S - bg[1]); dv = abs(V - bg[2])
            if ds >= 25 or dh >= 25 or dv >= 35:
                labels[r,c] = "O"
    return labels

# ---------- Template search ----------
def _find_obj_cell_by_tpl(frame: np.ndarray, tpl_path: str, grid: Grid,
                          last_cell: Optional[Tuple[int,int]],
                          lost_count: int,
                          thr: float) -> Tuple[Optional[Tuple[int,int]], int, Optional[Tuple[int,int]], float]:
    """
    Tìm (head/food) theo template:
    - Nếu còn dấu (lost_count < LIMIT) & có last_cell -> chỉ quét vùng ±SEARCH_RADIUS_CELLS ô
    - Ngược lại quét cả ROI lưới
    Trả: (cell_rc | None, lost_count_new, pos_xy | None, score)
    """
    if last_cell is not None and lost_count < (HEAD_LOST_LIMIT if "head" in tpl_path.lower() else BAIT_LOST_LIMIT):
        region = region_of_cell_band(grid, last_cell, SEARCH_RADIUS_CELLS)
    else:
        region = _grid_roi(grid)

    ok, pos, score = find_on_frame(frame, tpl_path, region=region, threshold=thr)
    if ok and pos:
        rc = cell_of_xy(grid, pos[0], pos[1])
        return rc, 0, pos, float(score or 0.0)
    return None, lost_count+1, None, float(score or 0.0)

# ---------- BFS ----------
def _bfs_path(blocked: np.ndarray, start: Tuple[int, int], goal: Tuple[int, int]) -> List[Tuple[int, int]]:
    """BFS 4 hướng, dùng queue popleft() để tránh 'deque mutated during iteration'."""
    rows, cols = blocked.shape

    def passable(r: int, c: int) -> bool:
        return 0 <= r < rows and 0 <= c < cols and not blocked[r, c]

    # Nếu start/goal không đi được thì trả rỗng
    if not passable(*start) or not passable(*goal):
        return []

    q: Deque[Tuple[int, int]] = deque()
    q.append(start)
    parent: dict[Tuple[int, int], Optional[Tuple[int, int]]] = {start: None}

    # BFS chuẩn
    while q:
        r, c = q.popleft()
        if (r, c) == goal:
            break
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = r + dr, c + dc
            if passable(nr, nc) and (nr, nc) not in parent:
                parent[(nr, nc)] = (r, c)
                q.append((nr, nc))

    # Không tới được goal
    if goal not in parent:
        return []

    # Lần ngược để dựng đường đi
    path: List[Tuple[int, int]] = []
    cur: Optional[Tuple[int, int]] = goal
    while cur is not None:
        path.append(cur)
        cur = parent[cur]
    path.reverse()
    return path


# ---------- Overlay ----------
def _draw_overlay(frame: np.ndarray, grid: Grid, blocked: np.ndarray,
                  head: Optional[Tuple[int,int]], food: Optional[Tuple[int,int]],
                  path: Optional[List[Tuple[int,int]]]) -> np.ndarray:
    out = frame.copy()
    x1,y1,x2,y2 = _grid_roi(grid)
    cv2.rectangle(out, (x1,y1), (x2,y2), (0,255,255), 2)
    for r in range(grid.rows):
        for c in range(grid.cols):
            cx1 = grid.x0 + c*grid.cw; cy1 = grid.y0 + r*grid.ch
            cx2 = cx1 + grid.cw;       cy2 = cy1 + grid.ch
            color = (0,255,0)
            if blocked[r,c]: color = (128,0,128)
            cv2.rectangle(out, (cx1,cy1), (cx2,cy2), color, 1)
    if food:
        cx1 = grid.x0 + food[1]*grid.cw; cy1 = grid.y0 + food[0]*grid.ch
        cx2 = cx1 + grid.cw;             cy2 = cy1 + grid.ch
        cv2.rectangle(out, (cx1,cy1), (cx2,cy2), (0,165,255), 2)
    if head:
        cx1 = grid.x0 + head[1]*grid.cw; cy1 = grid.y0 + head[0]*grid.ch
        cx2 = cx1 + grid.cw;             cy2 = cy1 + grid.ch
        cv2.rectangle(out, (cx1,cy1), (cx2,cy2), (0,0,255), 2)
    if path:
        for (r,c) in path:
            cx1 = grid.x0 + c*grid.cw; cy1 = grid.y0 + r*grid.ch
            cx2 = cx1 + grid.cw;       cy2 = cy1 + grid.ch
            cv2.rectangle(out, (cx1,cy1), (cx2,cy2), (0,255,255), 2)
    return out

# ---------- ENTRY: phân tích ----------
def run_snake_analyze(wk, seconds: float = 20.0, save_overlay: bool = True) -> bool:
    os.makedirs(DEBUG_DIR, exist_ok=True)
    L(wk, f"Start analyze @ tick={SCAN_INTERVAL:.2f}s")

    t_end = time.time() + max(0.5, seconds)
    t_last_dump = 0.0

    # 1) đo rows/cols 1 lần (hoặc dùng LOCK_*)
    img0 = grab_screen_np(wk)
    try:
        if LOCK_ROWS and LOCK_COLS:
            rows, cols = int(LOCK_ROWS), int(LOCK_COLS)
        else:
            rows, cols = _measure_rows_cols(img0, GRID_X0, GRID_Y0, CELL_W, CELL_H)
        grid = Grid(GRID_X0, GRID_Y0, rows, cols, CELL_W, CELL_H)
        L(wk, f"Grid = {rows}x{cols} origin=({GRID_X0},{GRID_Y0}) cell={CELL_W}x{CELL_H}")

        # 2) blocked mask tĩnh 1 lần cho nhẹ
        blocked = (_classify_obstacles_once(img0, grid) == "O")
        L(wk, f"Obstacles = {int(blocked.sum())} ô")
    finally:
        free_img(img0)

    # Track head/food
    head_cell: Optional[Tuple[int,int]] = None
    food_cell: Optional[Tuple[int,int]] = None
    head_lost = HEAD_LOST_LIMIT   # ép quét ROI ở frame đầu
    food_lost = BAIT_LOST_LIMIT

    while time.time() < t_end:
        img = grab_screen_np(wk)
        try:
            # 3) tìm head theo template (ưu tiên vùng quanh last_cell)
            head_cell, head_lost, head_xy, head_sc = _find_obj_cell_by_tpl(
                img, IMG_HEAD, grid, head_cell, head_lost, THR_HEAD
            )
            # 4) tìm bait theo template
            food_cell, food_lost, food_xy, food_sc = _find_obj_cell_by_tpl(
                img, IMG_BAIT, grid, food_cell, food_lost, THR_BAIT
            )

            L(wk, f"HEAD={_rc1(head_cell)} (0b={head_cell}, lost={head_lost}) | "
                  f"FOOD={_rc1(food_cell)} (0b={food_cell}, lost={food_lost}) | ROI={_grid_roi(grid)}")

            path: List[Tuple[int, int]] = []
            if head_cell and food_cell:
                # Bản sao mask chặn: luôn cho phép đi qua ô HEAD/FOOD
                blocked_now = blocked.copy()
                blocked_now[head_cell] = False
                blocked_now[food_cell] = False

                path = _bfs_path(blocked_now, head_cell, food_cell)
                if path:
                    if len(path) >= 2:
                        (r0, c0), (r1, c1) = path[0], path[1]
                        if r1 < r0:
                            step = "UP"
                        elif r1 > r0:
                            step = "DOWN"
                        elif c1 < c0:
                            step = "LEFT"
                        else:
                            step = "RIGHT"
                    else:
                        step = "STAY"
                    L(wk, f"PATH len={len(path)} first={step} — HEAD→FOOD (1b) {_rc1(head_cell)}→{_rc1(food_cell)}")
                else:
                    L(wk, f"PATH: không tìm được (bị chặn). Kiểm tra mask quanh {_rc1(head_cell)} và {_rc1(food_cell)}")

            # 5) overlay mỗi 1s
            now = time.time()
            if save_overlay and (now - t_last_dump >= DUMP_EVERY):
                ov = _draw_overlay(img, grid, blocked_now if (head_cell and food_cell) else blocked,
                                   head_cell, food_cell, path)
                out = Path(DEBUG_DIR) / f"snake_overlay_{int(now)}.png"
                try:
                    cv2.imwrite(str(out), ov)
                    L(wk, f"→ Lưu overlay: {out}")
                except Exception as e:
                    L(wk, f"⚠ Không lưu overlay: {e}")
                t_last_dump = now

            if not sleep_coop(wk, SCAN_INTERVAL):  # 0.1s/tick
                return False
        finally:
            free_img(img)

    L(wk, "Finish analyze.")
    return True

# ---------- Chạy độc lập (dev) ----------
if __name__ == "__main__":
    import sys, argparse
    from checkbox_actions import SimpleNoxWorker
    from module import resource_path

    ap = argparse.ArgumentParser()
    ap.add_argument("--serial",  default=os.environ.get("ANDROID_SERIAL", "emulator-5554"))
    ap.add_argument("--seconds", type=float, default=30.0)
    args = ap.parse_args()

    adb_path = resource_path(os.path.join("vendor", "adb.exe"))
    if not adb_path or not os.path.exists(adb_path):
        adb_path = os.path.join("vendor", "adb.exe")

    def _console_log(msg: str):
        try: print(msg)
        except Exception: pass

    print(f"ADB: {adb_path}")
    try:
        wk = SimpleNoxWorker(adb_path, args.serial, _console_log)
    except Exception as e:
        print("Không tự khởi tạo được worker. Hãy gọi run_snake_analyze(wk) từ UI.", e)
        sys.exit(1)

    ok = run_snake_analyze(wk, seconds=args.seconds)
    print("done =", ok)
