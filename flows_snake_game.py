# -*- coding: utf-8 -*-
"""
flows_snake_game.py — Dynamic replan: Ăn hết mồi (vòng CW) -> ra cửa gần nhất
- Giữ style & util của file gốc (OpenCV + BFS 4 hướng, template-matching).
- Log giống file gốc: HEAD/BAITS (1-based + 0-based), ROI, PATH len, first_step.
- Không đi lùi: cấm U-turn ở bước ĐẦU (dựa vào hướng di chuyển tick trước).
- Bộ ảnh theo "số ải": đọc ROI (446,273)-(501,330) -> chọn set 1-5 / 6-10 / (mở rộng).
"""

from __future__ import annotations
import os, time, math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Optional, Literal, Deque, Dict
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
LOCK_ROWS = None
LOCK_COLS = None

# ========= ROI đọc số ẢI =========
LEVEL_RECT = (446, 273, 501, 330)  # (x1,y1,x2,y2)

# ========= Mapping bộ ảnh theo dải ẢI =========
ASSET_SETS: List[Tuple[int, int, Dict[str, str]]] = [
    (1, 5,  dict(head="images/snake/head-1-5.png",
                 bait="images/snake/bait-1-5.png",
                 ice ="images/snake/ice-1-5.png")),
    (6, 10, dict(head="images/snake/head-6-10.png",
                 bait="images/snake/bait-6-10.png",
                 ice ="images/snake/ice-6-10.png")),
    # (11, 15, dict(head="images/snake/head-11-15.png",
    #               bait="images/snake/bait-11-15.png",
    #               ice ="images/snake/ice-11-15.png")),
]

# ========= Ngưỡng template =========
THR_HEAD  = 0.86
THR_BAIT  = 0.86
THR_ICE   = 0.85

SCAN_INTERVAL = 0.10     # 10Hz
DUMP_EVERY   = 1.0       # lưu overlay mỗi 1s
DEBUG_DIR    = "debug"

# Khi có last-cell, chỉ quét vùng ±R ô (nhẹ). Mất dấu liên tiếp -> mở rộng.
SEARCH_RADIUS_CELLS = 2
HEAD_LOST_LIMIT = 6
BAIT_LOST_LIMIT = 10

Label = Literal["E", "O", "H", "F"]

# 4 cửa cố định (1-based) — theo yêu cầu
GATES_RC_1B = [(7, 1), (7, 13), (1, 7), (13, 7)]

# ================== LOG tiện ích ==================
def _rc1(rc: tuple[int, int] | None) -> str:
    """Hiển thị (row,col) theo 1-based để khớp mắt thường."""
    if not rc:
        return "None"
    return f"({rc[0]+1}, {rc[1]+1})"

def L(wk, msg: str) -> None:
    _log(wk, f"[SNAKE] {msg}")

# ================== GRID ==================
@dataclass
class Grid:
    x0: int
    y0: int
    rows: int
    cols: int
    cw: int
    ch: int

def _is_board_color(h: float, s: float, v: float) -> bool:
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
    for c in range(1, 50):
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

# ================== OBSTACLES ==================
def _estimate_bg_hsv(roi_bgr: np.ndarray) -> Tuple[float,float,float]:
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    med = np.median(hsv.reshape(-1,3), axis=0).astype(float)
    return float(med[0]), float(med[1]), float(med[2])

def _classify_obstacles_once(frame: np.ndarray, grid: Grid) -> np.ndarray:
    """Phân loại O/E tĩnh dựa nền (nhẹ) cho TẤT CẢ ô."""
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

# ================== TEMPLATE FIND ==================
def _tpl_read(path: str) -> Optional[np.ndarray]:
    if not path: return None
    p = resource_path(path) if not os.path.isabs(path) else path
    if not p or not os.path.exists(p): return None
    return cv2.imread(p, cv2.IMREAD_COLOR)

def _find_obj_cell_by_tpl(frame: np.ndarray, tpl_path: str, grid: Grid,
                          last_cell: Optional[Tuple[int,int]],
                          lost_count: int,
                          thr: float) -> Tuple[Optional[Tuple[int,int]], int, Optional[Tuple[int,int]], float]:
    """Tìm head theo template; ưu tiên quét vùng quanh last_cell."""
    if last_cell is not None and lost_count < (HEAD_LOST_LIMIT if "head" in tpl_path.lower() else BAIT_LOST_LIMIT):
        region = region_of_cell_band(grid, last_cell, SEARCH_RADIUS_CELLS)
    else:
        region = _grid_roi(grid)
    ok, pos, score = find_on_frame(frame, resource_path(tpl_path), region=region, threshold=thr)
    if ok and pos:
        rc = cell_of_xy(grid, pos[0], pos[1])
        return rc, 0, pos, float(score or 0.0)
    return None, lost_count+1, None, float(score or 0.0)

def _find_all_cells_by_tpl(frame: np.ndarray, tpl_path: str,
                           grid: Grid, thr: float) -> List[Tuple[int,int]]:
    """Quét toàn ROI lưới, trả về TẤT CẢ cell match (không trùng)."""
    tpl_img = _tpl_read(tpl_path)
    if tpl_img is None:
        return []
    x1,y1,x2,y2 = _grid_roi(grid)
    roi = frame[y1:y2, x1:x2]
    res = cv2.matchTemplate(roi, tpl_img, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= thr)
    seen = set()
    cells: List[Tuple[int,int]] = []
    th_h, th_w = tpl_img.shape[:2]
    for (yy, xx) in zip(ys, xs):
        fx = x1 + int(xx + th_w//2)
        fy = y1 + int(yy + th_h//2)
        rc = cell_of_xy(grid, fx, fy)
        if rc not in seen:
            seen.add(rc)
            cells.append(rc)
    return cells

# ================== BFS ==================
def _bfs_path(blocked: np.ndarray, start: Tuple[int, int], goal: Tuple[int, int]) -> List[Tuple[int, int]]:
    rows, cols = blocked.shape
    def passable(r: int, c: int) -> bool:
        return 0 <= r < rows and 0 <= c < cols and not blocked[r, c]
    if not passable(*start) or not passable(*goal):
        return []
    q: Deque[Tuple[int, int]] = deque()
    q.append(start)
    parent: dict[Tuple[int, int], Optional[Tuple[int, int]]] = {start: None}
    while q:
        r, c = q.popleft()
        if (r, c) == goal:
            break
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = r + dr, c + dc
            if passable(nr, nc) and (nr, nc) not in parent:
                parent[(nr, nc)] = (r, c)
                q.append((nr, nc))
    if goal not in parent:
        return []
    path: List[Tuple[int, int]] = []
    cur: Optional[Tuple[int, int]] = goal
    while cur is not None:
        path.append(cur)
        cur = parent[cur]
    path.reverse()
    return path

# ================== OCR SỐ ẢI ==================
_DIG_W, _DIG_H = 18, 28
def _build_digit_templates() -> Dict[int, np.ndarray]:
    tmps: Dict[int, np.ndarray] = {}
    for d in range(10):
        canvas = np.zeros((_DIG_H, _DIG_W), np.uint8)
        cv2.putText(canvas, str(d), (1, _DIG_H-4), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 255, 2, cv2.LINE_AA)
        tmps[d] = canvas
    return tmps
_DIG_TPL = _build_digit_templates()

def _read_level_number(frame: np.ndarray) -> Optional[int]:
    x1,y1,x2,y2 = LEVEL_RECT
    x1, y1 = max(0,x1), max(0,y1)
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return None
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3,3), 0)
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY, 21, 2)
    if np.mean(bw) > 128:
        bw = cv2.bitwise_not(bw)
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((2,2), np.uint8), iterations=1)
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in cnts:
        x,y,w,h = cv2.boundingRect(c)
        if h >= 12 and w >= 6:
            boxes.append((x,y,w,h))
    if not boxes:
        return None
    boxes.sort(key=lambda b: b[0])  # trái→phải
    digits: List[int] = []
    for (x,y,w,h) in boxes:
        patch = bw[y:y+h, x:x+w]
        patch = cv2.resize(patch, (_DIG_W, _DIG_H), interpolation=cv2.INTER_AREA)
        best, best_sc = None, -1.0
        for d, tpl in _DIG_TPL.items():
            res = cv2.matchTemplate(patch, tpl, cv2.TM_CCOEFF_NORMED)
            sc  = float(res.max())
            if sc > best_sc:
                best_sc, best = sc, d
        if best is not None:
            digits.append(int(best))
    if not digits:
        return None
    try:
        return int("".join(str(x) for x in digits))
    except Exception:
        return None

def _choose_assets_by_level(level: Optional[int]) -> Dict[str, Optional[str]]:
    if level is None:
        return ASSET_SETS[0][2]
    for lo, hi, paths in ASSET_SETS:
        if lo <= level <= hi:
            return paths
    return ASSET_SETS[-1][2]

# ================== Sắp mồi vòng CW ==================
def _angle_cw_from_up(center: tuple[float,float], p: tuple[int,int]) -> float:
    cy, cx = center
    y, x = float(p[0]), float(p[1])
    ang = math.atan2(x - cx, cy - y)   # 0° hướng lên, CW tăng
    if ang < 0: ang += 2*math.pi
    return ang

def _order_baits_clockwise(baits: list[tuple[int,int]], grid: Grid,
                           start_from: tuple[int,int]) -> list[tuple[int,int]]:
    if not baits:
        return []
    center = ((grid.rows-1)/2.0, (grid.cols-1)/2.0)
    base = _angle_cw_from_up(center, start_from)
    items = []
    for rc in baits:
        ang = _angle_cw_from_up(center, rc)
        items.append(((ang - base) % (2*math.pi), rc))
    items.sort(key=lambda x: x[0])
    return [rc for _, rc in items]

# ================== Planner: Ăn hết mồi -> Gate gần nhất ==================
def _plan_full_route(blocked: np.ndarray, grid: Grid,
                     head: tuple[int,int],
                     baits: list[tuple[int,int]]) -> list[tuple[int,int]]:
    """
    H -> ăn hết mồi (vòng CW, bỏ qua mồi 'không tới được') -> gate gần nhất.
    """
    route: list[tuple[int,int]] = []
    cur = head
    ordered = _order_baits_clockwise(baits, grid, head)
    # ăn từng mồi
    for target in ordered:
        mask = blocked.copy()
        mask[cur] = False
        mask[target] = False
        p = _bfs_path(mask, cur, target)
        if not p:
            continue
        route.extend(p if not route else p[1:])
        cur = target
    # đi gate gần nhất
    gates0 = [(r-1, c-1) for (r, c) in GATES_RC_1B
              if 0 <= r-1 < grid.rows and 0 <= c-1 < grid.cols]
    best: list[tuple[int,int]] = []
    for g in gates0:
        mask = blocked.copy()
        mask[cur] = False
        mask[g] = False
        p = _bfs_path(mask, cur, g)
        if p and (not best or len(p) < len(best)):
            best = p
    if best:
        route.extend(best if not route else best[1:])
    return route

# ================== No-U-Turn helper ==================
def _sign(v: int) -> int:
    return -1 if v < 0 else 1 if v > 0 else 0

def _vec_to_step(dr: int, dc: int) -> str:
    if dr < 0: return "UP"
    if dr > 0: return "DOWN"
    if dc < 0: return "LEFT"
    if dc > 0: return "RIGHT"
    return "STAY"

def _avoid_uturn_if_needed(blocked: np.ndarray, grid: Grid,
                           head: Tuple[int,int],
                           prev_dir: Tuple[int,int] | None,
                           baits: List[Tuple[int,int]]) -> Tuple[List[Tuple[int,int]], str]:
    """
    Replan full-route. Nếu first_step là U-turn so với prev_dir -> chặn ô 'sau lưng' & replan.
    Trả: (path, note)
    """
    path = _plan_full_route(blocked, grid, head, baits)
    if not path or len(path) < 2 or not prev_dir or prev_dir == (0,0):
        return path, "NO_UTURN_CHECK"
    drp, dcp = prev_dir
    dr1 = path[1][0] - path[0][0]
    dc1 = path[1][1] - path[0][1]
    if (dr1, dc1) != (-drp, -dcp):
        return path, "NO_UTURN_OK"
    # Thử tránh bằng cách khóa ô phía sau đầu
    behind = (head[0] - drp, head[1] - dcp)
    if not (0 <= behind[0] < grid.rows and 0 <= behind[1] < grid.cols):
        return path, "UTURN_UNAVOIDABLE"
    blocked2 = blocked.copy()
    blocked2[behind] = True
    path2 = _plan_full_route(blocked2, grid, head, baits)
    if path2 and len(path2) >= 2:
        dr2 = path2[1][0] - path2[0][0]
        dc2 = path2[1][1] - path2[0][1]
        if (dr2, dc2) != (-drp, -dcp):
            return path2, "UTURN_AVOIDED"
    return path, "UTURN_UNAVOIDABLE"

# ================== Overlay ==================
def _draw_overlay(frame: np.ndarray, grid: Grid, blocked: np.ndarray,
                  head: Optional[Tuple[int,int]], foods: List[Tuple[int,int]],
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
    for food in foods:
        cx1 = grid.x0 + food[1]*grid.cw; cy1 = grid.y0 + food[0]*grid.ch
        cx2 = cx1 + grid.cw;             cy2 = cy1 + grid.ch
        cv2.rectangle(out, (cx1,cy1), (cx2,cy2), (0,165,255), 2)  # cam
    if head:
        cx1 = grid.x0 + head[1]*grid.cw; cy1 = grid.y0 + head[0]*grid.ch
        cx2 = cx1 + grid.cw;             cy2 = cy1 + grid.ch
        cv2.rectangle(out, (cx1,cy1), (cx2,cy2), (0,0,255), 2)    # đỏ
    if path:
        for (r,c) in path:
            cx1 = grid.x0 + c*grid.cw; cy1 = grid.y0 + r*grid.ch
            cx2 = cx1 + grid.cw;       cy2 = cy1 + grid.ch
            cv2.rectangle(out, (cx1,cy1), (cx2,cy2), (0,255,255), 2)  # vàng
    # 4 cửa (xanh lam)
    for (r1b,c1b) in GATES_RC_1B:
        r0, c0 = r1b-1, c1b-1
        if 0 <= r0 < grid.rows and 0 <= c0 < grid.cols:
            cx1 = grid.x0 + c0*grid.cw; cy1 = grid.y0 + r0*grid.ch
            cx2 = cx1 + grid.cw;        cy2 = cy1 + grid.ch
            cv2.rectangle(out, (cx1,cy1), (cx2,cy2), (255,255,0), 2)
    return out

# ================== ENTRY ==================
def run_snake_analyze(wk, seconds: float = 20.0, save_overlay: bool = True) -> bool:
    os.makedirs(DEBUG_DIR, exist_ok=True)
    L(wk, f"Start analyze (eat-all-then-gate, no-UTURN) @ tick={SCAN_INTERVAL:.2f}s")

    t_end = time.time() + max(0.5, seconds)
    t_last_dump = 0.0

    # 1) Đo grid 1 lần
    img0 = grab_screen_np(wk)
    try:
        if LOCK_ROWS and LOCK_COLS:
            rows, cols = int(LOCK_ROWS), int(LOCK_COLS)
        else:
            rows, cols = _measure_rows_cols(img0, GRID_X0, GRID_Y0, CELL_W, CELL_H)
        grid = Grid(GRID_X0, GRID_Y0, rows, cols, CELL_W, CELL_H)
        L(wk, f"Grid = {rows}x{cols} origin=({GRID_X0},{GRID_Y0}) cell={CELL_W}x{CELL_H}")

        # 2) Đọc số ải & chọn bộ ảnh
        level = _read_level_number(img0)
        assets = _choose_assets_by_level(level)
        head_img = assets.get("head") or resource_path("images/snake/head.png")
        bait_img = assets.get("bait") or resource_path("images/snake/baits.png")
        ice_img  = assets.get("ice")  or None
        L(wk, f"Level={level} → assets: head={head_img}, bait={bait_img}, ice={ice_img}")

        # 3) Mask chặn tĩnh + ICE (nếu có)
        blocked_label = _classify_obstacles_once(img0, grid)
        blocked = (blocked_label == "O")
        if ice_img:
            ices = _find_all_cells_by_tpl(img0, ice_img, grid, THR_ICE)
            for rc in ices:
                blocked[rc] = True
            if ices:
                L(wk, f"ICE via template: {len(ices)} ô")
        L(wk, f"Obstacles = {int(blocked.sum())} ô | ROI={_grid_roi(grid)}")
    finally:
        free_img(img0)

    # 4) Theo dõi động
    head_cell: Optional[Tuple[int,int]] = None
    prev_head_cell: Optional[Tuple[int,int]] = None
    head_lost = HEAD_LOST_LIMIT

    bait_cells: List[Tuple[int,int]] = []
    last_baits_scan = 0.0
    BAIT_RESCAN_COOLDOWN = 0.45  # quét lại mồi tối đa ~2.2 lần/giây

    dyn_path: List[Tuple[int,int]] = []

    while time.time() < t_end:
        img = grab_screen_np(wk)
        try:
            now = time.time()

            # 4.1) cập nhật vị trí đầu rắn
            prev_head_cell = head_cell
            head_cell, head_lost, head_xy, head_sc = _find_obj_cell_by_tpl(
                img, head_img, grid, head_cell, head_lost, THR_HEAD
            )

            # 4.2) (định kỳ) quét lại toàn bộ mồi
            need_scan = (now - last_baits_scan >= BAIT_RESCAN_COOLDOWN)
            if head_cell and (head_cell in bait_cells):
                need_scan = True  # vừa ăn 1 mồi -> cập nhật ngay
            if need_scan:
                bait_cells = _find_all_cells_by_tpl(img, bait_img, grid, THR_BAIT)
                bait_cells = [rc for rc in bait_cells
                              if 0 <= rc[0] < grid.rows and 0 <= rc[1] < grid.cols and not blocked[rc]]
                last_baits_scan = now

            # Log HEAD + BAITS giống style gốc
            L(wk, f"HEAD={_rc1(head_cell)} (0b={head_cell}, lost={head_lost}) | "
                  f"BAITS={len(bait_cells)} items: {[ _rc1(b) for b in bait_cells ]} | ROI={_grid_roi(grid)}")

            # 4.3) Tính lại tuyến: ăn hết mồi -> gate gần nhất, có kiểm U-turn bước đầu
            prev_dir = None
            if head_cell and prev_head_cell and head_cell != prev_head_cell:
                drp = _sign(head_cell[0] - prev_head_cell[0])
                dcp = _sign(head_cell[1] - prev_head_cell[1])
                prev_dir = (drp, dcp)

            if head_cell:
                dyn_path, ut_note = _avoid_uturn_if_needed(blocked, grid, head_cell, prev_dir, bait_cells)
            else:
                dyn_path, ut_note = [], "NO_HEAD"

            # 4.4) Log PATH + hướng bước đầu
            step = "NONE"
            if dyn_path and len(dyn_path) >= 2:
                (r0, c0), (r1, c1) = dyn_path[0], dyn_path[1]
                step = _vec_to_step(r1 - r0, c1 - c0)
            L(wk, f"PATH len={len(dyn_path)} first={step} ({ut_note})")

            # 4.5) Overlay
            ov = _draw_overlay(img, grid, blocked, head_cell, bait_cells, dyn_path)
            if save_overlay and (now - t_last_dump >= DUMP_EVERY):
                out = Path(DEBUG_DIR) / f"snake_overlay_{int(now)}.png"
                try:
                    cv2.imwrite(str(out), ov)
                    L(wk, f"→ Lưu overlay: {out}")
                except Exception as e:
                    L(wk, f"⚠ Không lưu overlay: {e}")
                t_last_dump = now

            # 4.6) Nhịp vòng
            if not sleep_coop(wk, SCAN_INTERVAL):
                return False
        finally:
            free_img(img)

    L(wk, "Finish analyze (eat-all-then-gate, no-UTURN).")
    return True

# ================== Chạy độc lập (dev) ==================
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
