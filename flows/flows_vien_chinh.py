# -*- coding: utf-8 -*-
"""
flows_vien_chinh.py — phiên bản chuẩn hoá
Viễn chinh trong Liên minh
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
    # (SỬA LỖI) Thêm find_on_frame vào danh sách import
    find_on_frame,
    DEFAULT_THR as THR_DEFAULT,
    free_img as _free_img,
    mem_relief as _mem_relief,resource_path
)

# ===== REGIONS =====
REG_INSIDE = (28, 3, 201, 75)  # lien-minh-inside
REG_OUTSIDE = (581, 1485, 758, 1600)  # lien-minh-outside

REG_FIND = (33, 516, 628, 615)  # lien-minh-vien-chinh
REG_TRINH_SAT = (715, 1288, 888, 1480)  # nut-trinh-sat

REG_DEN = (308, 1290, 586, 1386)  # nut-den
REG_DONG = (771, 130, 881, 231)  # nut-dong

# ===== IMAGES =====
IMG_INSIDE = resource_path("images/lien_minh/lien-minh-inside.png")
IMG_OUTSIDE = resource_path("images/lien_minh/lien-minh-outside.png")

IMG_VIEN_CHINH = resource_path("images/lien_minh/lien-minh-vien-chinh.png")
IMG_TRINH_SAT = resource_path("images/lien_minh/nut-trinh-sat.png")
IMG_DEN = resource_path("images/lien_minh/nut-den.png")
IMG_DONG = resource_path("images/lien_minh/nut-dong.png")

# ===== PARAMS =====
ESC_DELAY = 1.0
CLICK_DELAY = 0.4


# ================= core =================

def _ensure_inside_hard(wk) -> bool:
    """
    Dọn popup & trở lại INSIDE:
      - Nếu đang thấy INSIDE → ESC cho tới khi MẤT INSIDE
      - Sau đó tìm OUTSIDE → TAP vào → chờ INSIDE; nếu không thấy cả 2 → ESC 1 cái rồi lặp.
    """
    # 1) nếu đang inside → ESC đến khi mất inside
    while True:
        if _aborted(wk): return False
        img = _grab_screen_np(wk)
        ok_in, _, _ = find_on_frame(img, IMG_INSIDE, region=REG_INSIDE, threshold=THR_DEFAULT)
        _free_img(img)
        if not ok_in:
            break
        _adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)  # ESC
        if not _sleep_coop(wk, ESC_DELAY): return False

    # 2) mở lại từ outside
    while True:
        if _aborted(wk): return False
        img = _grab_screen_np(wk)

        ok_in, _, _ = find_on_frame(img, IMG_INSIDE, region=REG_INSIDE, threshold=THR_DEFAULT)
        if ok_in:
            _free_img(img)
            return True

        ok_out, _, _ = find_on_frame(img, IMG_OUTSIDE, region=REG_OUTSIDE, threshold=THR_DEFAULT)
        _free_img(img)
        if ok_out:
            _tap_center(wk, REG_OUTSIDE)
            if not _sleep_coop(wk, 0.8): return False
            # chờ INSIDE xuất hiện tối đa 10 nhịp
            for _ in range(10):
                if _aborted(wk): return False
                img2 = _grab_screen_np(wk)
                ok_in2, _, _ = find_on_frame(img2, IMG_INSIDE, region=REG_INSIDE, threshold=THR_DEFAULT)
                _free_img(img2)
                if ok_in2:
                    return True
                if not _sleep_coop(wk, 0.2): return False
            continue

        # không thấy cả 2 → ESC 1 cái rồi tìm tiếp outside
        _adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)
        if not _sleep_coop(wk, ESC_DELAY): return False


def _open_expedition(wk) -> bool:
    """
    Từ INSIDE, lặp cho tới khi mở được 'Liên minh – Viễn chinh' và NHÌN THẤY 'nut-trinh-sat':
      - Mỗi lần vuốt đều kiểm tra ngay: trước swipe, sau swipe.
      - Thử theo thứ tự: (trái→phải)x3 rồi (phải→trái)x3; giữa các swipe đều check ngay.
      - Nếu vẫn không: ESC → quay lại _ensure_inside_hard và lặp.
    """
    while True:
        if _aborted(wk): return False
        if not _ensure_inside_hard(wk):
            return False

        # 0) thử tìm ngay khi chưa vuốt
        img0 = _grab_screen_np(wk)
        ok0, pt0, _ = find_on_frame(img0, IMG_VIEN_CHINH, region=REG_FIND, threshold=THR_DEFAULT)
        _free_img(img0)
        if ok0 and pt0:
            _tap(wk, *pt0)
            if not _sleep_coop(wk, CLICK_DELAY): return False
            # đợi trinh-sat xuất hiện
            for _ in range(20):
                if _aborted(wk): return False
                imgts = _grab_screen_np(wk)
                okt, _, _ = find_on_frame(imgts, IMG_TRINH_SAT, region=REG_TRINH_SAT, threshold=THR_DEFAULT)
                _free_img(imgts)
                if okt: return True
                if not _sleep_coop(wk, 0.2): return False

        # helper: sau khi vừa TAP 'viễn chinh' xong, chờ 'trinh-sat'
        def _wait_trinh_sat_after_tap() -> bool:
            for _ in range(20):
                if _aborted(wk): return False
                imgts = _grab_screen_np(wk)
                okt, _, _ = find_on_frame(imgts, IMG_TRINH_SAT, region=REG_TRINH_SAT, threshold=THR_DEFAULT)
                _free_img(imgts)
                if okt: return True
                if not _sleep_coop(wk, 0.2): return False
            # không thấy → ESC để rời màn hiện tại rồi vòng lại
            _adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)
            if not _sleep_coop(wk, ESC_DELAY): return False
            return False

        # 1) hướng TRÁI→PHẢI (nội dung trượt sang trái): 3 lần, mỗi lần check trước & sau
        for i in range(3):
            if _aborted(wk): return False

            # check trước swipe
            img1 = _grab_screen_np(wk)
            ok1, pt1, _ = find_on_frame(img1, IMG_VIEN_CHINH, region=REG_FIND, threshold=THR_DEFAULT)
            _free_img(img1)
            if ok1 and pt1:
                _tap(wk, *pt1)
                if not _sleep_coop(wk, CLICK_DELAY): return False
                if _wait_trinh_sat_after_tap(): return True
                break  # quay vòng ngoài để làm lại

            # swipe 1 cái
            _swipe(wk, 280, 980, 880, 980, dur_ms=450)  # trong màn → gần mép phải
            if not _sleep_coop(wk, 0.3): return False

            # check ngay sau swipe
            img2 = _grab_screen_np(wk)
            ok2, pt2, _ = find_on_frame(img2, IMG_VIEN_CHINH, region=REG_FIND, threshold=THR_DEFAULT)
            _free_img(img2)
            if ok2 and pt2:
                _tap(wk, *pt2)
                if not _sleep_coop(wk, CLICK_DELAY): return False
                if _wait_trinh_sat_after_tap(): return True
                break

            if (i % 2) == 1:
                _mem_relief()

        # 2) hướng PHẢI→TRÁI (nội dung trượt sang phải): 3 lần, mỗi lần check trước & sau
        for i in range(3):
            if _aborted(wk): return False

            # check trước swipe
            img3 = _grab_screen_np(wk)
            ok3, pt3, _ = find_on_frame(img3, IMG_VIEN_CHINH, region=REG_FIND, threshold=THR_DEFAULT)
            _free_img(img3)
            if ok3 and pt3:
                _tap(wk, *pt3)
                if not _sleep_coop(wk, CLICK_DELAY): return False
                if _wait_trinh_sat_after_tap(): return True
                break

            # swipe 1 cái
            _swipe(wk, 880, 980, 280, 980, dur_ms=450)  # gần mép phải → trong màn
            if not _sleep_coop(wk, 0.3): return False

            # check ngay sau swipe
            img4 = _grab_screen_np(wk)
            ok4, pt4, _ = find_on_frame(img4, IMG_VIEN_CHINH, region=REG_FIND, threshold=THR_DEFAULT)
            _free_img(img4)
            if ok4 and pt4:
                _tap(wk, *pt4)
                if not _sleep_coop(wk, CLICK_DELAY): return False
                if _wait_trinh_sat_after_tap(): return True
                break

            if (i % 2) == 1:
                _mem_relief()

        # 3) chưa mở được → ESC & lặp từ đầu
        _adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)
        if not _sleep_coop(wk, ESC_DELAY): return False


def _reopen_until_trinh_sat(wk, max_rounds=6) -> bool:
    """ESC & mở lại giao diện Viễn chinh cho tới khi NHÌN THẤY 'Trinh sát'."""
    rounds = 0
    while rounds < max_rounds and not _aborted(wk):
        if _open_expedition(wk):
            return True
        rounds += 1
        if (rounds % 2) == 0:
            _mem_relief()
    return False


def _do_trinh_sat_12_times(wk):
    """
    Đảm bảo đủ 12 lần hợp lệ:
      - Mỗi lần đều kiểm tra THẤY 'Trinh sát' rồi mới bấm.
      - Nếu mất nút → ESC & mở lại tới khi thấy lại 'Trinh sát' rồi mới tiếp tục.
      - Sau khi bấm: nếu thấy 'nut-den' hoặc 'nut-dong' thì bấm; không thấy thì bỏ qua.
    """
    done = 0
    while done < 12 and not _aborted(wk):
        # 1) xác nhận có 'Trinh sát'
        img = _grab_screen_np(wk)
        ok_ts, pt_ts, _ = find_on_frame(img, IMG_TRINH_SAT, region=REG_TRINH_SAT, threshold=THR_DEFAULT)
        _free_img(img)
        if not ok_ts or not pt_ts:
            _log(wk, "Không thấy 'Trinh sát' — mở lại Viễn chinh rồi tiếp tục.")
            if not _reopen_until_trinh_sat(wk, max_rounds=6):
                _log(wk, "❌ Không thể mở lại 'Trinh sát' sau nhiều lần thử.")
                return
            continue

        # 2) bấm 'Trinh sát'
        _tap(wk, *pt_ts)
        if not _sleep_coop(wk, 0.25): return

        # 3) nếu có 'nut-den' → bấm
        img2 = _grab_screen_np(wk)
        ok_den, p_den, _ = find_on_frame(img2, IMG_DEN, region=REG_DEN, threshold=THR_DEFAULT)
        _free_img(img2)
        if ok_den and p_den:
            _tap(wk, *p_den)
            if not _sleep_coop(wk, 0.2): return

        # 4) nếu có 'nut-dong' → bấm
        img3 = _grab_screen_np(wk)
        ok_dong, p_dong, _ = find_on_frame(img3, IMG_DONG, region=REG_DONG, threshold=THR_DEFAULT)
        _free_img(img3)
        if ok_dong and p_dong:
            _tap(wk, *p_dong)
            if not _sleep_coop(wk, 0.2): return

        done += 1
        _log(wk, f"Trinh sát thành công lần {done}/12")

        _mem_relief()

        if not _sleep_coop(wk, 0.25): return


def run_guild_expedition_flow(wk, log=print) -> bool:
    """
    Entry:
      1) Đảm bảo INSIDE không popup (_ensure_inside_hard)
      2) Mở 'Liên minh – Viễn chinh' và NHÌN THẤY 'Trinh sát'
      3) Nhấn 'Trinh sát' 12 lần (mỗi lần đều kiểm tra; mất nút thì mở lại rồi tiếp tục)
      4) ESC → chờ hiện OUTSIDE → DONE
    """
    if _aborted(wk):
        _log(wk, "⛔ Hủy trước khi chạy Viễn chinh.")
        _mem_relief()
        return False

    _log(wk, "➡️ Bắt đầu Viễn chinh")
    if not _ensure_inside_hard(wk):
        _mem_relief()
        return False

    if not _open_expedition(wk):
        _log(wk, "❌ Không mở được 'Liên minh - Viễn chinh'.")
        _mem_relief()
        return False

    _do_trinh_sat_12_times(wk)
    if _aborted(wk):
        _mem_relief()
        return False

    # ESC → chờ OUTSIDE rồi kết thúc
    _adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)
    if not _sleep_coop(wk, 1.0):
        _mem_relief()
        return False
    for _ in range(20):
        if _aborted(wk):
            _mem_relief()
            return False
        img = _grab_screen_np(wk)
        ok_out, _, _ = find_on_frame(img, IMG_OUTSIDE, region=REG_OUTSIDE, threshold=THR_DEFAULT)
        _free_img(img)
        if ok_out:
            _log(wk, "✅ Hoàn tất Viễn chinh (đã về màn có Liên minh outside).")
            _mem_relief()
            return True
        if not _sleep_coop(wk, 0.2):
            _mem_relief()
            return False

    _log(wk, "ℹ️ Không xác nhận được OUTSIDE sau ESC, nhưng đã rời viễn chinh.")
    _mem_relief()
    return True