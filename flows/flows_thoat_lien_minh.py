# -*- coding: utf-8 -*-
"""
flows_thoat_lien_minh.py
Tự rời (thoát) Liên minh

— BỔ SUNG THEO YÊU CẦU —
• Mỗi vòng lặp: chụp frame KIỂM TRA KÉP (ưu tiên 'kiem-tra-chung' trước, rồi tới 'inside').
• Sau khi TAP vào Liên minh (outside): sleep 1.5s rồi KIỂM TRA KÉP; nếu chưa rõ thì poll 3–4 nhịp (0.3s/nhịp), ưu tiên 'kiem-tra-chung' trước.
• Bất kỳ chỗ nào trước đây chỉ dò 'inside' để quyết định bước tiếp -> thay bằng dò 'kiem-tra-chung' trước rồi mới 'inside'.
• Không tự ghi file ở flow; chỉ return True khi thấy 'kiem-tra-chung'. Việc cập nhật last_leave do runner lo.

Điều chỉnh swipe theo đúng cơ chế màn 900x1600:
- Vuốt NGANG (phải→trái): (280,980) -> (0,980)
- Vuốt DỌC (lên trên): (478,1345) -> (478,1)

Quy trình tổng:
1) Đầu mỗi vòng: kiểm tra kép (kiem-tra-chung / inside).
2) Đảm bảo vào Liên minh (inside) và dọn popup (có kiểm tra kép sau TAP outside).
3) Vuốt ngang phải→trái để tìm 'sanh-lien-minh' rồi TAP; đợi 2 giây.
4) Vào 'Động thái', rồi fling dọc để tìm 'Rời khỏi liên minh' + xác nhận.
5) Kiểm tra rời thành công (ưu tiên 'kiem-tra-chung' trước).
"""

from __future__ import annotations
import time

# ====== IMPORT TOÀN BỘ HÀM DÙNG CHUNG TỪ module.py ======
from module import (
    log_wk, adb_safe,
    grab_screen_np, find_on_frame,
    tap, tap_center, swipe,
    aborted, sleep_coop,
    free_img, mem_relief,resource_path
)

# ===== REGIONS =====
REG_INSIDE          = (28, 3, 201, 75)             # lien-minh-inside
REG_OUTSIDE         = (581, 1485, 758, 1600)       # lien-minh-outside

REG_SANH            = (186, 485, 848, 568)         # sanh-lien-minh.png
REG_DONG_THAI       = (28, 1381, 266, 1483)        # dong-thai.png
REG_BTN_ROI         = (621, 1293, 840, 1390)       # roi-khoi-lien-minh.png
REG_XAC_NHAN_ROI    = (521, 911, 773, 1011)        # xac-nhan-roi-lm.png

# ===== IMAGES =====
IMG_INSIDE          = resource_path("images/lien_minh/lien-minh-inside.png")
IMG_OUTSIDE         = resource_path("images/lien_minh/lien-minh-outside.png")

IMG_SANH            = resource_path("images/lien_minh/sanh-lien-minh.png")
IMG_DONG_THAI       = resource_path("images/lien_minh/dong-thai.png")
IMG_ROI             = resource_path("images/lien_minh/roi-khoi-lien-minh.png")
IMG_XN_ROI          = resource_path("images/lien_minh/xac-nhan-roi-lm.png")
IMG_KIEM_TRA_CHUNG  = resource_path("images/lien_minh/kiem-tra-chung.png")

# ===== PARAMS =====
THR_DEFAULT = 0.86
ESC_DELAY   = 1.0
CLICK_DELAY = 0.4
MAX_ROUNDS  = 30


# ========= tiện ích kiểm tra kép =========
def _check_left_or_inside_from_img(img) -> str | None:
    """
    Ưu tiên dò 'kiem-tra-chung' trước, sau đó 'inside'.
    Trả về:
      - 'left'   : đã rời (hoặc bị kick)
      - 'inside' : vẫn đang trong Liên minh
      - None     : không xác định từ frame hiện tại
    """
    ok_left, _, _ = find_on_frame(img, IMG_KIEM_TRA_CHUNG, region=None)
    if ok_left:
        return "left"
    ok_in, _, _ = find_on_frame(img, IMG_INSIDE, region=REG_INSIDE)
    if ok_in:
        return "inside"
    return None

def _check_left_or_inside(wk) -> str | None:
    img = grab_screen_np(wk)
    state = _check_left_or_inside_from_img(img) if img is not None else None
    free_img(img)
    return state


# ================= core =================

def _ensure_inside_clean(wk) -> str | bool:
    """
    ESC tới khi thấy OUTSIDE → TAP OUTSIDE → đợi & KIỂM TRA KÉP.
    Trả:
      - 'inside' : đã đảm bảo vào giao diện Liên minh
      - 'left'   : phát hiện 'kiem-tra-chung' → coi như đã rời
      - False    : bị hủy
    """
    while True:
        if aborted(wk): return False

        # ESC cho đến khi nhìn thấy outside
        while True:
            if aborted(wk): return False
            img = grab_screen_np(wk)
            ok_out, _, _ = find_on_frame(img, IMG_OUTSIDE, region=REG_OUTSIDE)
            free_img(img)
            if ok_out:
                break
            adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)  # ESC
            if not sleep_coop(wk, ESC_DELAY): return False

        # TAP outside
        tap_center(wk, REG_OUTSIDE)

        # — bổ sung: chờ 1.5s rồi kiểm tra kép —
        if not sleep_coop(wk, 1.5): return False
        img2 = grab_screen_np(wk)
        state = _check_left_or_inside_from_img(img2) if img2 is not None else None
        free_img(img2)
        if state == "left":
            log_wk(wk, "✅ Thấy 'kiem-tra-chung' sau khi mở Liên minh — coi như đã rời.")
            return "left"
        if state == "inside":
            log_wk(wk, "✅ Đang ở Liên minh (inside).")
            if not sleep_coop(wk, 0.6): return False
            return "inside"

        # nếu chưa xác định → poll 3–4 nhịp (0.3s/nhịp), ưu tiên 'kiem-tra-chung'
        for _ in range(4):
            if not sleep_coop(wk, 0.3): return False
            img3 = grab_screen_np(wk)
            state = _check_left_or_inside_from_img(img3) if img3 is not None else None
            free_img(img3)
            if state == "left":
                log_wk(wk, "✅ Thấy 'kiem-tra-chung' — coi như đã rời.")
                return "left"
            if state == "inside":
                log_wk(wk, "✅ Đang ở Liên minh (inside).")
                if not sleep_coop(wk, 0.6): return False
                return "inside"

        # không thấy inside sau khi tap → ESC và lặp lại
        adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)
        if not sleep_coop(wk, ESC_DELAY): return False


def _open_guild_hall(wk) -> bool:
    """
    Vuốt NGANG (phải→trái) 3–4 lần để tìm 'sanh-lien-minh.png' rồi TAP.
    Sau khi TAP Sảnh → đợi 2s rồi mới kiểm tra 'Động thái'.
    """
    # thử tìm ngay
    img = grab_screen_np(wk)
    ok, pt, _ = find_on_frame(img, IMG_SANH, region=REG_SANH)
    free_img(img)
    if ok and pt:
        tap(wk, *pt)
        if not sleep_coop(wk, 2.0): return False
        return True

    # vuốt phải→trái, mỗi lần thử lại
    for _ in range(4):
        if aborted(wk): return False
        swipe(wk, 280, 980, 0, 980, dur_ms=450)
        if not sleep_coop(wk, 0.3): return False
        img = grab_screen_np(wk)
        ok, pt, _ = find_on_frame(img, IMG_SANH, region=REG_SANH)
        free_img(img)
        if ok and pt:
            tap(wk, *pt)
            if not sleep_coop(wk, 2.0): return False
            return True
    return False


def _enter_hall_until_feed(wk) -> bool:
    """
    Sau TAP sảnh:
      - Nếu thấy 'dong-thai' → True
      - Nếu không: nếu còn 'sanh-lien-minh' → TAP lại sảnh
      - Nếu cả 2 không thấy → False (để vòng ngoài làm lại từ đầu)
    """
    for i in range(10):
        if aborted(wk): return False
        img = grab_screen_np(wk)
        ok_feed, _, _ = find_on_frame(img, IMG_DONG_THAI, region=REG_DONG_THAI)
        if ok_feed:
            free_img(img)
            return True
        ok_sanh, pt_sanh, _ = find_on_frame(img, IMG_SANH, region=REG_SANH)
        free_img(img)
        if ok_sanh and pt_sanh:
            tap(wk, *pt_sanh)
            if not sleep_coop(wk, 2.0): return False
            continue
        if (i % 5) == 0: mem_relief()
        return False
    return False


def _fling_and_find_leave(wk) -> bool:
    """
    Ở trang 'Động thái':
      - Vuốt dọc 2 lần (478,1345)->(478,1)
      - Đợi 1s, tìm 'roi-khoi-lien-minh' & 'xac-nhan-roi-lm'
      - Nếu chưa thấy, tiếp tục các vòng fling + tìm cho tới khi thấy hoặc bị hủy
    """
    tap(wk, 540, 1000)
    if not sleep_coop(wk, 0.1): return False

    # 2 lần vuốt dọc mạnh
    for _ in range(2):
        if aborted(wk): return False
        swipe(wk, 478, 1345, 478, 1, dur_ms=450)
        if not sleep_coop(wk, 0.15): return False

    if not sleep_coop(wk, 1.0): return False

    # kiểm tra nút rời
    def _try_click_leave():
        img = grab_screen_np(wk)
        ok_roi, pt_roi, _ = find_on_frame(img, IMG_ROI, region=REG_BTN_ROI)
        free_img(img)
        if ok_roi and pt_roi:
            tap(wk, *pt_roi)
            # đợi & bấm xác nhận rời
            for _ in range(12):
                if aborted(wk): return False
                img2 = grab_screen_np(wk)
                ok_xn, pt_xn, _ = find_on_frame(img2, IMG_XN_ROI, region=REG_XAC_NHAN_ROI)
                free_img(img2)
                if ok_xn and pt_xn:
                    tap(wk, *pt_xn)
                    if not sleep_coop(wk, 0.4): return False
                    return True
                if not sleep_coop(wk, 0.2): return False
        return None  # chưa thấy

    got = _try_click_leave()
    if got is True:
        return True
    if got is False:
        return False

    # nếu chưa thấy → tiếp tục fling theo vòng lặp an toàn
    loop = 0
    while True:
        if aborted(wk): return False
        # thêm một chu kỳ fling (3 lần) rồi đợi
        for _ in range(3):
            if aborted(wk): return False
            swipe(wk, 478, 1345, 478, 1, dur_ms=450)
            if not sleep_coop(wk, 0.12): return False
        if not sleep_coop(wk, 1.0): return False

        got = _try_click_leave()
        if got is True:
            return True
        if got is False:
            return False

        # vẫn chưa thấy nút rời → đảm bảo còn ở trang Động thái (tùy chọn)
        img = grab_screen_np(wk)
        ok_feed, _, _ = find_on_frame(img, IMG_DONG_THAI, region=REG_DONG_THAI)
        free_img(img)
        if not ok_feed:
            return False

        loop += 1
        if (loop % 4) == 0:
            mem_relief()


def _verify_left(wk) -> bool:
    """
    ESC về outside → TAP outside:
      - ƯU TIÊN: nếu thấy 'kiem-tra-chung' ⇒ ĐÃ rời; True
      - Nếu thấy INSIDE ⇒ CHƯA rời; False
      - Nếu chưa rõ → poll tiếp (ưu tiên 'kiem-tra-chung' trước)
    """
    # ESC cho tới khi thấy outside
    while True:
        if aborted(wk): return False
        img = grab_screen_np(wk)
        ok_out, _, _ = find_on_frame(img, IMG_OUTSIDE, region=REG_OUTSIDE)
        free_img(img)
        if ok_out:
            break
        adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)
        if not sleep_coop(wk, ESC_DELAY): return False

    # TAP outside → kiểm tra
    tap_center(wk, REG_OUTSIDE)
    if not sleep_coop(wk, 1.5): return False

    # Kiểm tra kép nhiều nhịp, ƯU TIÊN 'kiem-tra-chung'
    for _ in range(12):
        if aborted(wk): return False
        img2 = grab_screen_np(wk)
        state = _check_left_or_inside_from_img(img2) if img2 is not None else None
        free_img(img2)

        if state == "left":
            log_wk(wk, "✅ Đã rời Liên minh (thấy 'kiem-tra-chung').")
            return True
        if state == "inside":
            log_wk(wk, "⚠️ Vẫn thấy Liên minh (inside) → chưa rời được.")
            return False

        if not sleep_coop(wk, 0.25): return False

    log_wk(wk, "ℹ️ Không xác nhận được trạng thái rời. Sẽ thử lại quy trình rời.")
    return False


# ================= entry =================
def run_guild_leave_flow(wk, log=print) -> bool:
    """
    Vòng tổng tối đa MAX_ROUNDS:
      0) ĐẦU MỖI VÒNG: kiểm tra kép (kiem-tra-chung / inside)
      1) Đảm bảo inside sạch popup (có kiểm tra kép sau TAP outside)
      2) Mở Sảnh Liên minh
      3) Vào tới 'Động thái'
      4) Fling + rời liên minh + xác nhận
      5) Kiểm tra rời thành công → nếu chưa, lặp lại
    """
    if aborted(wk):
        log_wk(wk, "⛔ Hủy trước khi chạy Thoát Liên minh.")
        mem_relief()
        return False

    log_wk(wk, "➡️ Bắt đầu Thoát Liên minh")
    for round_no in range(1, MAX_ROUNDS + 1):
        if aborted(wk):
            mem_relief()
            return False
        log_wk(wk, f"— vòng rời liên minh {round_no}/{MAX_ROUNDS} —")

        # (0) ĐẦU MỖI VÒNG: kiểm tra kép
        state0 = _check_left_or_inside(wk)
        if state0 == "left":
            log_wk(wk, "✅ Phát hiện 'kiem-tra-chung' ngay đầu vòng — coi như đã rời.")
            mem_relief()
            return True
        # nếu 'inside' thì tiếp tục quy trình rời; nếu None cũng tiếp tục

        # (1) Đảm bảo inside sạch popup (có kiểm tra kép sau TAP outside)
        st = _ensure_inside_clean(wk)
        if st is False:
            mem_relief()
            return False
        if st == "left":
            mem_relief()
            return True
        # nếu st == 'inside' → tiếp tục

        # (2) Mở Sảnh Liên minh
        if not _open_guild_hall(wk):
            log_wk(wk, "ℹ️ Chưa mở được 'Sảnh Liên minh' — thử lại từ đầu.")
            if (round_no % 4) == 0: mem_relief()
            continue

        # (3) Vào 'Động thái'
        if not _enter_hall_until_feed(wk):
            log_wk(wk, "ℹ️ Không vào được trang 'Động thái' — thử lại từ đầu.")
            if (round_no % 4) == 0: mem_relief()
            continue

        # (4) Fling + rời + xác nhận
        ok_leave = _fling_and_find_leave(wk)
        if not ok_leave:
            log_wk(wk, "ℹ️ Chưa bấm được 'Rời khỏi liên minh' — thử lại từ đầu.")
            if (round_no % 4) == 0: mem_relief()
            continue

        # (5) Kiểm tra rời thành công (ưu tiên 'kiem-tra-chung' trước)
        if _verify_left(wk):
            log_wk(wk, "🏁 Thoát Liên minh — HOÀN TẤT.")
            mem_relief()
            return True
        else:
            log_wk(wk, "↩️ Chưa rời được — lặp lại quy trình rời.")
            if (round_no % 4) == 0: mem_relief()

    log_wk(wk, "⏹️ Hết MAX_ROUNDS vẫn chưa rời được liên minh.")
    mem_relief()
    return False
