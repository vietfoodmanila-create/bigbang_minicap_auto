# -*- coding: utf-8 -*-
"""
flows_lien_minh.py
Gia nhập Liên minh + đảm bảo mở giao diện Liên minh (inside)

Đặc thù flow (giữ lại):
- Phán đoán FULL/CÒN SLOT bằng màu (HSV) trên vùng REG_JOIN_COLOR/PT_JOIN_COLOR.
- Chu trình mở UI Liên minh, kiểm tra OUTSIDE/JOIN/INSIDE.

Mọi hàm dùng chung (ADB, screencap, match, log, sleep coop, swipe…) lấy từ module.py
"""

from __future__ import annotations
import time

# ===== import helpers chung từ module.py =====
from module import (
    log_wk as _log,
    adb_safe as _adb_safe,
    tap as _tap,
    tap_center as _tap_center,
    swipe as _swipe,
    sleep_coop as _sleep_coop,
    aborted as _aborted,
    grab_screen_np as _grab_screen_np,
    find_on_frame as _find_on_frame,
    DEFAULT_THR as THR_DEFAULT,
    free_img as _free_img,         # NEW: bổ sung trong module.py (xem patch bên dưới)
    mem_relief as _mem_relief,     # NEW: bổ sung trong module.py (xem patch bên dưới)
    resource_path
)

# ================== REGIONS ==================
REG_OUTSIDE   = (581, 1485, 758, 1600)   # nút Liên minh ngoài map
REG_JOIN_BTN  = (628, 313, 825, 391)     # "Gia nhập liên minh"
REG_INSIDE    = (28, 3, 201, 75)         # header đã ở trong Liên minh

# ---- vùng/điểm kiểm tra màu enable/disable của nút xin vào ----
REG_JOIN_COLOR = (780, 345, 795, 368)    # vùng nhỏ để lấy màu
PT_JOIN_COLOR  = (790, 355)              # toạ độ điểm giữa vùng (fallback)

# ================== IMAGES ==================
IMG_OUTSIDE   = resource_path("images/lien_minh/lien-minh-outside.png")
IMG_JOIN      = resource_path("images/lien_minh/gia-nhap-lien-minh.png")
IMG_INSIDE    = resource_path("images/lien_minh/lien-minh-inside.png")

# ================== PARAMS ==================
ESC_DELAY     = 1.5
CLICK_DELAY   = 0.5

# ---- ngưỡng màu (có thể tinh chỉnh theo log) ----
# "xanh" (enable): hue ~ 35..85, S/V đủ cao
GREEN_H_LOW, GREEN_H_HIGH = 35, 85
GREEN_S_MIN, GREEN_V_MIN = 80, 80
# "xám" (disable): bão hoà thấp
GRAY_S_MAX = 35

def _sleep(s: float):
    time.sleep(s)

# ================== (ĐẶC THÙ) Kiểm tra màu enable/disable ==================
def _crop_np(img, reg):
    x1, y1, x2, y2 = reg
    return img[y1:y2, x1:x2].copy()

def _classify_join_color(wk) -> str | None:
    """
    Phân loại màu vùng nút xin vào:
      - trả 'ok'   nếu màu xanh (có thể xin vào)
      - trả 'full' nếu màu xám (đã đủ người)
      - None nếu không chắc (thiếu frame/ngoài range)
    """
    img = _grab_screen_np(wk)
    if img is None:
        return None
    try:
        import cv2, numpy as np
        # ưu tiên lấy trung bình trên ROI nhỏ
        roi = _crop_np(img, REG_JOIN_COLOR)
        if roi is None or roi.size == 0:
            # fallback: lấy 3x3 quanh điểm PT_JOIN_COLOR
            x, y = PT_JOIN_COLOR
            x1, y1, x2, y2 = max(0, x-1), max(0, y-1), x+2, y+2
            roi = img[y1:y2, x1:x2]

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        h = float(np.mean(hsv[...,0]))
        s = float(np.mean(hsv[...,1]))
        v = float(np.mean(hsv[...,2]))

        _log(wk, f"[COLOR] H={h:.1f} S={s:.1f} V={v:.1f}")

        # Xám: bão hoà thấp
        if s <= GRAY_S_MAX:
            _free_img(img, roi, hsv)
            return "full"

        # Xanh: hue nằm trong dải xanh + đủ S/V
        if (GREEN_H_LOW <= h <= GREEN_H_HIGH) and (s >= GREEN_S_MIN) and (v >= GREEN_V_MIN):
            _free_img(img, roi, hsv)
            return "ok"

        _free_img(img, roi, hsv)
        return None
    except Exception:
        _free_img(img)
        return None

# ------------------ Core: mở UI Liên minh ------------------
def _open_guild_ui(wk) -> str:
    """
    - Lặp: nếu chưa thấy OUTSIDE trong REG_OUTSIDE -> BACK + đợi -> thử lại
    - Khi thấy -> ESC -> đợi 1s -> TAP outside -> kiểm tra JOIN/INSIDE tối đa 5 lần
      * 'join'   -> return "join"
      * 'inside' -> return "inside"
      * 'abort'  -> khi bị hủy
    """
    while True:
        if _aborted(wk):
            _log(wk, "⛔ Hủy theo yêu cầu (open_guild_ui).")
            return "abort"

        # chờ OUTSIDE
        while True:
            if _aborted(wk):
                _log(wk, "⛔ Hủy theo yêu cầu (open_guild_ui/inner).")
                return "abort"
            img = _grab_screen_np(wk)
            ok_out, _, _ = _find_on_frame(img, IMG_OUTSIDE, region=REG_OUTSIDE, threshold=THR_DEFAULT)
            _free_img(img)
            if ok_out:
                break
            _log(wk, "🔎 Chưa thấy Liên minh (outside). BACK dọn UI rồi thử lại…")
            _adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)
            if not _sleep_coop(wk, ESC_DELAY):
                return "abort"

        _log(wk, "🟦 Thấy Liên minh (outside) → ESC, đợi 1s rồi TAP mở giao diện.")
        _adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)  # ESC trước khi mở
        if not _sleep_coop(wk, 1.0):
            return "abort"
        _tap_center(wk, REG_OUTSIDE)
        if not _sleep_coop(wk, CLICK_DELAY):
            return "abort"

        # kiểm tra join/inside
        tries = 0
        while tries < 5:
            if _aborted(wk):
                _log(wk, "⛔ Hủy theo yêu cầu (wait join/inside).")
                return "abort"
            img_now = _grab_screen_np(wk)
            ok_join, _, _ = _find_on_frame(img_now, IMG_JOIN, region=REG_JOIN_BTN, threshold=THR_DEFAULT)
            if ok_join:
                _free_img(img_now)
                _log(wk, "🟩 Đã hiển thị nút 'Gia nhập liên minh'.")
                return "join"
            ok_in, _, _ = _find_on_frame(img_now, IMG_INSIDE, region=REG_INSIDE, threshold=THR_DEFAULT)
            _free_img(img_now)
            if ok_in:
                _log(wk, "🟩 Đã ở giao diện Liên minh (inside).")
                return "inside"
            tries += 1
            if not _sleep_coop(wk, 0.6):
                return "abort"

        _log(wk, "↩️ 5 lần chưa thấy 'Gia nhập'/'Inside' → quay lại bấm Outside.")

# ------------------ Public: gia nhập liên minh ------------------
def join_guild_once(wk, log=print) -> bool:
    """
    Kịch bản:
    1) _open_guild_ui:
       - 'inside' -> xong (True)
       - 'join'   -> sang bước 2
    2) Ở trạng thái 'join':
       - Kiểm tra màu REG_JOIN_COLOR/điểm PT_JOIN_COLOR:
           * 'full' → ESC + ngủ 15s rồi làm lại
           * 'ok'   → tap JOIN → mở lại UI; nếu thấy 'inside' => True
           * None   → vẫn tap JOIN để thử, rồi mở lại UI kiểm tra
    """
    if _aborted(wk):
        _log(wk, "⛔ Hủy trước khi join guild.")
        _mem_relief()
        return False

    state = _open_guild_ui(wk)
    if state == "abort":
        _mem_relief()
        return False
    if state == "inside":
        _log(wk, "✅ Đã ở liên minh (inside) → bỏ qua gia nhập.")
        _mem_relief()
        return True

    # đang thấy JOIN
    while True:
        if _aborted(wk):
            _log(wk, "⛔ Hủy trong lúc xin gia nhập.")
            _mem_relief()
            return False

        img = _grab_screen_np(wk)
        ok_join, pt, _ = _find_on_frame(img, IMG_JOIN, region=REG_JOIN_BTN, threshold=THR_DEFAULT)
        _free_img(img)
        if not ok_join or not pt:
            _log(wk, "ℹ️ Không còn nút 'Gia nhập liên minh' → mở lại giao diện để kiểm tra.")
            state = _open_guild_ui(wk)
            if state == "abort":
                _mem_relief()
                return False
            if state == "inside":
                _log(wk, "🎉 Xác nhận đã vào liên minh (inside).")
                _mem_relief()
                return True
            continue  # state == "join" → lặp tiếp

        # ==== Kiểm tra màu trước khi nhấn JOIN ====
        if not _sleep_coop(wk, 0.2):
            _mem_relief()
            return False  # nhịp nhỏ để UI ổn định
        join_state = _classify_join_color(wk)  # 'ok' | 'full' | None
        if join_state == "full":
            _log(wk, "🚧 Nút xin vào đang XÁM (đã đủ người). ESC đóng giao diện, đợi 15s rồi thử lại…")
            _adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)  # ESC
            if not _sleep_coop(wk, 15.0):
                _mem_relief()
                return False
            # quay lại mở giao diện từ đầu
            state = _open_guild_ui(wk)
            if state == "abort":
                _mem_relief()
                return False
            if state == "inside":
                _log(wk, "🎉 Trong thời gian chờ đã vào liên minh (inside).")
                _mem_relief()
                return True
            else:
                continue
        elif join_state == "ok":
            _log(wk, "✅ Nút xin vào đang XANH (còn slot) — tiến hành xin vào.")
        else:
            _log(wk, "ℹ️ Không chắc theo màu — vẫn thử xin vào.")
        # ==== /Kiểm tra màu ====

        # Nếu còn slot (hoặc không chắc) → NHẤN JOIN
        _tap(wk, *pt)
        if not _sleep_coop(wk, 0.3):
            _mem_relief()
            return False

        # Mở lại để xác nhận trạng thái
        state = _open_guild_ui(wk)
        if state == "abort":
            _mem_relief()
            return False
        if state == "inside":
            _log(wk, "✅ Xin vào liên minh thành công (đã inside).")
            _mem_relief()
            return True

        # Nếu quay lại vẫn là 'join' → có thể đang chờ duyệt: đợi rồi thử lại
        _log(wk, "🤔 Chưa xác nhận được — đợi 15s rồi thử lại.")
        if not _sleep_coop(wk, 15.0):
            _mem_relief()
            return False

# ------------------ Public: đảm bảo inside ------------------
def ensure_guild_inside(wk, log=print) -> bool:
    """
    - Nếu thấy INSIDE trong REG_INSIDE → True
    - Nếu chưa: lặp BACK tới khi thấy OUTSIDE → TAP outside → kiểm tra lại INSIDE; lặp tới khi True
    """
    while True:
        if _aborted(wk):
            _log(wk, "⛔ Hủy theo yêu cầu (ensure_guild_inside).")
            _mem_relief()
            return False

        img = _grab_screen_np(wk)
        ok_in, _, _ = _find_on_frame(img, IMG_INSIDE, region=REG_INSIDE, threshold=THR_DEFAULT)
        _free_img(img)
        if ok_in:
            _log(wk, "✅ Đang ở giao diện Liên minh (inside).")
            _mem_relief()
            return True

        img2 = _grab_screen_np(wk)
        ok_out, _, _ = _find_on_frame(img2, IMG_OUTSIDE, region=REG_OUTSIDE, threshold=THR_DEFAULT)
        _free_img(img2)
        if not ok_out:
            _log(wk, "🔎 Chưa thấy 'Liên minh' (outside). BACK dọn UI rồi thử lại…")
            _adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)
            if not _sleep_coop(wk, ESC_DELAY):
                _mem_relief()
                return False
            continue

        _log(wk, "🟦 Thấy Liên minh (outside) → TAP mở giao diện.")
        _tap_center(wk, REG_OUTSIDE)
        if not _sleep_coop(wk, CLICK_DELAY):
            _mem_relief()
            return False
