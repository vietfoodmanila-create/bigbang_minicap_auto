# -*- coding: utf-8 -*-
"""
rook_solver_standalone.py
---------------------------------
Standalone như pick_coords_standalone.py:
- Chỉ chụp ảnh qua ADB (exec-out screencap -p) theo config.py
- Nhấn R: chụp & phân tích; C: hiệu chỉnh 2 giao điểm lưới 10x9
- Đánh dấu "chân" của quân xanh; gợi ý nước đi cho quân XE đỏ (biến thể như mô tả)

Phím:
  R = Refresh ảnh & phân tích
  C = Hiệu chỉnh lưới (click 2 lần: góc trên-trái, rồi góc dưới-phải)
  Click trái lên quân xanh = đổi loại quân (tốt→mã→xe→pháo→tượng→sĩ→tướng)
  Q/ESC = thoát
"""
import os, sys, time, math, subprocess
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional, Set
import numpy as np
import cv2

# ====== PHẦN ADB & CẤU HÌNH — giống pick_coords_standalone.py ======
try:
    # dùng đúng các biến trong config.py
    from config import LDPLAYER_ADB_PATH, SCREEN_W, SCREEN_H  # noqa: F401
    ADB_PATH = LDPLAYER_ADB_PATH
except Exception:
    # fallback nhẹ nếu thiếu config.py (giữ đúng tinh thần file gốc)
    ADB_PATH = r"D:\LDPlayer\LDPlayer9\adb.exe"
    SCREEN_W, SCREEN_H = 900, 1600

# !!! THAY Device ID tại đây nếu cần (giống file gốc) !!!
DEVICE_ID = "emulator-5554"

DEBUG = True
SHOT_DIR = "test/shots"  # giống pick_coords_standalone.py

def _run(args, text=True):
    """Chạy 1 lệnh hệ thống, ẩn cửa sổ trên Windows."""
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return subprocess.run(args, capture_output=True, text=text, startupinfo=startupinfo)

def adb(*args, text=True):
    """Gửi lệnh ADB tới thiết bị chỉ định."""
    cmd = [ADB_PATH, "-s", DEVICE_ID] + list(args)
    if DEBUG:
        print("→ ADB:", " ".join(str(x) for x in cmd))
    return _run(cmd, text=text)

def ensure_connected():
    """Đảm bảo ADB thấy device (giống logic file gốc)."""
    if not os.path.exists(ADB_PATH):
        raise FileNotFoundError(f"Không tìm thấy ADB: {ADB_PATH}")
    out = _run([ADB_PATH, "devices"]).stdout
    if (DEVICE_ID not in out) or ("device" not in out):
        raise RuntimeError(f"ADB chưa thấy thiết bị '{DEVICE_ID}'. Hãy mở LDPlayer/Nox rồi chạy lại.")
    print(f"✅ ADB OK — {DEVICE_ID}")

def screencap_cv() -> Optional[np.ndarray]:
    """Chụp màn hình bằng exec-out screencap -p (y hệt file gốc)."""
    try:
        p = adb("exec-out", "screencap", "-p", text=False)
        if p.returncode != 0 or not p.stdout:
            raise RuntimeError("Không chụp được màn hình qua ADB.")
        data = np.frombuffer(p.stdout, np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("Giải mã ảnh thất bại.")
        if DEBUG:
            os.makedirs(SHOT_DIR, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(SHOT_DIR, f"screen_{ts}.png")
            cv2.imwrite(path, img)
            print(f"Đã lưu ảnh: {path} size={img.shape}")
        return img
    except Exception as e:
        print("Lỗi screencap:", e)
        return None

# ====== Pixel <-> Lưới ======
ROWS, COLS = 10, 9
@dataclass
class BoardCalib:
    top_left: Tuple[int, int]
    bottom_right: Tuple[int, int]
    rows: int = ROWS
    cols: int = COLS
    @property
    def step(self) -> Tuple[float, float]:
        dx = (self.bottom_right[0] - self.top_left[0]) / (self.cols - 1)
        dy = (self.bottom_right[1] - self.top_left[1]) / (self.rows - 1)
        return dx, dy
    def grid_to_px(self, r: int, c: int) -> Tuple[int, int]:
        dx, dy = self.step
        return (int(round(self.top_left[0] + c * dx)),
                int(round(self.top_left[1] + r * dy)))
    def px_to_grid(self, x: int, y: int) -> Tuple[int, int]:
        dx, dy = self.step
        return (int(round((y - self.top_left[1]) / dy)),
                int(round((x - self.top_left[0]) / dx)))
    def is_inside_grid_px(self, x: int, y: int, margin: int = 10) -> bool:
        x1, y1 = self.top_left; x2, y2 = self.bottom_right
        return (x1 - margin <= x <= x2 + margin) and (y1 - margin <= y <= y2 + margin)
    def draw_grid(self, img: np.ndarray, color=(40, 200, 255)) -> None:
        for r in range(self.rows):
            for c in range(self.cols):
                cx, cy = self.grid_to_px(r, c)
                cv2.circle(img, (cx, cy), 3, color, -1)

CALIB_PATH = 'board_calib_xiangqi.json'

def load_calib(path=CALIB_PATH) -> Optional[BoardCalib]:
    if not os.path.exists(path): return None
    try:
        data = eval(open(path, 'r', encoding='utf-8').read())
        return BoardCalib(tuple(data['top_left']), tuple(data['bottom_right']),
                          data.get('rows', ROWS), data.get('cols', COLS))
    except Exception:
        import json
        try:
            data = json.load(open(path, 'r', encoding='utf-8'))
            return BoardCalib(tuple(data['top_left']), tuple(data['bottom_right']),
                              data.get('rows', ROWS), data.get('cols', COLS))
        except Exception:
            return None

def save_calib(calib: BoardCalib, path=CALIB_PATH):
    import json
    json.dump(dict(top_left=list(calib.top_left), bottom_right=list(calib.bottom_right),
                   rows=calib.rows, cols=calib.cols), open(path, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

# ====== Logic cờ & tính “chân” ======
DIRS_ORTH = [(1,0),(-1,0),(0,1),(0,-1)]
DIRS_DIAG = [(1,1),(1,-1),(-1,1),(-1,-1)]

@dataclass
class BoardState:
    red_rook: Tuple[int,int]
    greens: List[Dict]  # {'rc':(r,c), 'type':'pawn'|...}
    red_others: Set[Tuple[int,int]] = field(default_factory=set)
    def occupied(self) -> Dict[Tuple[int,int], str]:
        occ = {}
        if self.red_rook: occ[self.red_rook] = 'R'
        for g in self.greens: occ[g['rc']] = 'G'
        for r in self.red_others: occ[r] = 'R'
        return occ

def in_board(rc): r,c = rc; return 0 <= r < ROWS and 0 <= c < COLS

def rook_moves_from(pos, occ):
    res=[]
    for dr,dc in DIRS_ORTH:
        r,c = pos
        while True:
            r += dr; c += dc
            if not in_board((r,c)): break
            if (r,c) in occ:
                if occ[(r,c)]=='G': res.append((r,c))
                break
            res.append((r,c))
    return res

def knight_moves_from(pos, occ):
    r,c = pos; res=[]
    for (dr_block, dc_block, dr, dc) in [
        (1,0,2,1),(1,0,2,-1),(-1,0,-2,1),(-1,0,-2,-1),
        (0,1,1,2),(0,1,-1,2),(0,-1,1,-2),(0,-1,-1,-2)
    ]:
        br,bc=r+dr_block,c+dc_block
        if not in_board((br,bc)) or (br,bc) in occ: continue
        tr,tc=r+dr,c+dc
        if in_board((tr,tc)): res.append((tr,tc))
    return res

def advisor_moves_from(pos, occ):
    r,c=pos; res=[]
    for dr,dc in DIRS_DIAG:
        tr,tc=r+dr,c+dc
        if in_board((tr,tc)): res.append((tr,tc))
    return res

def elephant_moves_from(pos, occ):
    r,c=pos; res=[]
    for dr,dc in DIRS_DIAG:
        eye=(r+dr, c+dc); tr,tc=r+2*dr, c+2*dc
        if not in_board(eye) or not in_board((tr,tc)): continue
        if eye in occ: continue
        res.append((tr,tc))
    return res

def general_moves_from(pos, occ):
    r,c=pos; res=[]
    for dr,dc in DIRS_ORTH:
        tr,tc=r+dr,c+dc
        if in_board((tr,tc)): res.append((tr,tc))
    return res

def pawn_moves_from(pos, occ):
    r,c=pos; res=[]
    for dr,dc in DIRS_ORTH:
        tr,tc=r+dr,c+dc
        if in_board((tr,tc)): res.append((tr,tc))
    return res

def cannon_attack_squares(pos, occ):
    r,c = pos; res=[]
    for dr,dc in DIRS_ORTH:
        r1,c1=r+dr,c+dc
        while in_board((r1,c1)) and (r1,c1) not in occ:
            r1 += dr; c1 += dc
        if not in_board((r1,c1)): continue
        r2,c2=r1+dr,c1+dc
        while in_board((r2,c2)):
            if (r2,c2) in occ:
                res.append((r2,c2)); break
            r2 += dr; c2 += dc
    return res

def attack_squares_of_piece(ptype, pos, occ) -> Set[Tuple[int,int]]:
    t = ptype.lower()
    if t=='pawn': return set(pawn_moves_from(pos, occ))
    if t in ('horse','knight'): return set(knight_moves_from(pos, occ))
    if t in ('advisor','shi'): return set(advisor_moves_from(pos, occ))
    if t in ('elephant','xiang','bishop'): return set(elephant_moves_from(pos, occ))
    if t in ('general','king'): return set(general_moves_from(pos, occ))
    if t in ('rook','car'): return set(rook_moves_from(pos, occ))
    if t in ('cannon','pao'): return set(cannon_attack_squares(pos, occ))
    return set(pawn_moves_from(pos, occ))

def union_green_attack_squares(state: BoardState) -> Set[Tuple[int,int]]:
    occ = state.occupied(); res=set()
    for g in state.greens:
        res |= attack_squares_of_piece(g.get('type','pawn'), g['rc'], occ)
    return res

@dataclass
class Suggestion:
    to: Tuple[int,int]; score: float; details: Dict

def count_threats_if_rook_at(dest: Tuple[int,int], state: BoardState) -> Tuple[int,int]:
    occ = state.occupied().copy()
    occ.pop(state.red_rook, None); occ[dest] = 'R'
    visible=0; chain=0
    for dr,dc in DIRS_ORTH:
        r,c = dest; seen=False
        r+=dr; c+=dc
        while in_board((r,c)):
            if (r,c) in occ:
                if occ[(r,c)]=='G':
                    if not seen: visible+=1; seen=True
                    else: chain+=1
                break
            r+=dr; c+=dc
    return visible, chain

def is_safe_square_for_rook(dest, state: BoardState, captured=None) -> bool:
    greens = [g for g in state.greens if not (captured and g['rc']==captured)]
    st2 = BoardState(dest, greens, state.red_others)
    danger = union_green_attack_squares(st2)
    return dest not in danger

def generate_rook_suggestions(state: BoardState, topk=5) -> List[Suggestion]:
    occ = state.occupied(); sugs=[]
    for d in rook_moves_from(state.red_rook, occ):
        cap = d if d in occ and occ[d]=='G' else None
        if not is_safe_square_for_rook(d, state, captured=cap): continue
        th, chain = count_threats_if_rook_at(d, state)
        score = th + 0.5*chain + (0.25 if cap else 0.0)
        sugs.append(Suggestion(d, score, {'threat_now': th, 'chain_bonus': chain, 'captured': cap}))
    sugs.sort(key=lambda s:(-s.score, s.to[0], s.to[1]))
    return sugs[:topk]

# ====== Nhận diện quân (màu + hình tròn, đơn giản & đủ dùng) ======
def detect_pieces(img_bgr: np.ndarray, calib: BoardCalib):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    mask_green = cv2.inRange(hsv, (35,70,60), (85,255,255))
    mask_red   = cv2.inRange(hsv, (0,70,60), (10,255,255)) | cv2.inRange(hsv, (160,70,60), (179,255,255))

    components=[]
    def add_from_contours(mask, label):
        m = cv2.medianBlur(mask, 5)
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            area = cv2.contourArea(c)
            if area < 150 or area > 2500: continue
            (x,y), r = cv2.minEnclosingCircle(c)
            x,y,r = int(x), int(y), int(r)
            if r < 10 or r > 30: continue
            if not calib.is_inside_grid_px(x,y, 80): continue
            components.append((x,y,r,label))
    add_from_contours(mask_green, 'green')
    add_from_contours(mask_red, 'red')

    # map vào lưới (snap)
    occ = {}; red_rook=None; greens=[]
    for (x,y,r,col) in components:
        r_grid, c_grid = calib.px_to_grid(x,y)
        if 0<=r_grid<ROWS and 0<=c_grid<COLS:
            cx,cy = calib.grid_to_px(r_grid,c_grid)
            if math.hypot(x-cx,y-cy) <= max(calib.step)*0.7:
                if col=='red':
                    red_rook = (r_grid,c_grid)
                elif col=='green':
                    greens.append({'rc':(r_grid,c_grid), 'color':'green', 'type':'pawn'})
    return red_rook, greens

# ====== Vẽ overlay ======
def draw_state_overlay(img: np.ndarray, calib: BoardCalib, state: Optional[BoardState],
                       suggestions: Optional[List[Suggestion]]=None):
    draw = img.copy()
    calib.draw_grid(draw, color=(0,255,255))
    if state:
        occ = state.occupied()
        # chân từng quân xanh
        for idx,g in enumerate(state.greens):
            feet = attack_squares_of_piece(g.get('type','pawn'), g['rc'], occ)
            for (r,c) in feet:
                x,y = calib.grid_to_px(r,c); cv2.circle(draw, (x,y), 6, (0,200,0), 1)
        # vẽ quân
        for idx,g in enumerate(state.greens):
            x,y = calib.grid_to_px(*g['rc'])
            cv2.circle(draw, (x,y), 14, (0,200,0), 2)
            cv2.putText(draw, f"{idx}:{g['type'][:1]}", (x+10,y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1, cv2.LINE_AA)
        if state.red_rook:
            x,y = calib.grid_to_px(*state.red_rook)
            cv2.circle(draw, (x,y), 16, (0,0,255), 2)
            cv2.putText(draw, "Xe", (x-12,y+5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255), 1, cv2.LINE_AA)
    if suggestions and state and state.red_rook:
        for i,sug in enumerate(suggestions):
            x1,y1 = calib.grid_to_px(*state.red_rook)
            x2,y2 = calib.grid_to_px(*sug.to)
            cv2.arrowedLine(draw, (x1,y1), (x2,y2), (255,0,0) if i==0 else (255,180,0), 2, tipLength=0.06)
            txt = f"#{i+1} -> ({sug.to[0]+1},{sug.to[1]+1})  sc={sug.score:.2f}  now={sug.details['threat_now']} chain={sug.details['chain_bonus']} {'CAP' if sug.details['captured'] else ''}"
            cv2.putText(draw, txt, (20, 30+22*i), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 2, cv2.LINE_AA)
            cv2.putText(draw, txt, (20, 30+22*i), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (240,240,240), 1, cv2.LINE_AA)
    return draw

# ====== Main (nhấn R là có ảnh ngay — giống pick_coords) ======
WINDOW = 'Rook Helper — BBTK'
def run():
    ensure_connected()
    calib = load_calib()
    click_points=[]; last_img=None; state=None; suggestions=None

    def on_mouse(event, x, y, flags, userdata):
        nonlocal click_points, calib, last_img, state, suggestions
        if event == cv2.EVENT_LBUTTONDOWN:
            if calib is None:
                click_points.append((x,y))
                print('[CALIB] Click:', x,y)
                if len(click_points)==2:
                    tl = click_points[0]; br = click_points[1]
                    if br[0] < tl[0]: tl, br = (br[0], tl[1]), (tl[0], br[1])
                    calib = BoardCalib(tl, br); save_calib(calib); print('[CALIB] Saved.')
            else:
                if state is None: return
                # đổi loại quân xanh gần nhất
                best_idx=None; best_dist=1e9
                for i,g in enumerate(state.greens):
                    px = calib.grid_to_px(*g['rc'])
                    d = math.hypot(px[0]-x, px[1]-y)
                    if d<best_dist: best_dist=d; best_idx=i
                if best_idx is not None and best_dist<=20:
                    order = ['pawn','knight','rook','cannon','elephant','advisor','general']
                    g = state.greens[best_idx]
                    g['type'] = order[(order.index(g['type'])+1)%len(order)]
                    print(f'[TYPE] Green #{best_idx} -> {g["type"]}')
                    suggestions = generate_rook_suggestions(state)
        elif event == cv2.EVENT_RBUTTONDOWN:
            print('[CALIB] Reset. Bấm C để set lại 2 điểm.')
            if os.path.exists(CALIB_PATH): os.remove(CALIB_PATH)
            calib = None; click_points.clear()

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW, 560, 1000)
    cv2.setMouseCallback(WINDOW, on_mouse)

    print("[HELP] R: chụp & phân tích | C: calibrate (2 giao điểm) | Click quân xanh để đổi loại | Q/ESC: thoát")
    if calib is None:
        print("[NOTE] Chưa có calibration. Nhấn C rồi click 2 giao điểm (góc trên‑trái, góc dưới‑phải).")

    while True:
        base = last_img if last_img is not None else np.zeros((800, 450, 3), np.uint8)
        overlay = draw_state_overlay(base, calib, state, suggestions) if (calib and state) else base.copy()
        if calib and last_img is None:
            calib.draw_grid(overlay)
        cv2.imshow(WINDOW, overlay)
        k = cv2.waitKey(20) & 0xFF
        if k in (ord('q'), 27): break
        if k == ord('c'):
            print('[CALIB] Click 2 giao điểm (góc trên‑trái → góc dưới‑phải).')
            calib=None; click_points.clear()
        if k == ord('r'):
            img = screencap_cv()
            if img is None:
                print('[ERR] Không chụp được ảnh.')
                continue
            last_img = img
            if calib is None:
                print('[WARN] Chưa có calibration. Nhấn C để set 2 điểm.')
                continue
            # nhận diện quân
            red_rook, greens = detect_pieces(last_img, calib)
            if not red_rook:
                print('[WARN] Không tìm thấy Xe đỏ (hãy chỉnh calib hoặc zoom).')
            state = BoardState(red_rook=red_rook, greens=greens)
            suggestions = generate_rook_suggestions(state)
            if suggestions:
                print('[SUGGEST]')
                for i,s in enumerate(suggestions):
                    print(f"  #{i+1} -> {s.to}  score={s.score:.2f}  now={s.details['threat_now']} chain={s.details['chain_bonus']} {'CAP' if s.details['captured'] else ''}")
            else:
                print('[SUGGEST] Chưa có nước an toàn phù hợp.')

    cv2.destroyAllWindows()

if __name__ == "__main__":
    run()
