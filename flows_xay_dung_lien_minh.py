# -*- coding: utf-8 -*-
"""
flows_xay_dung_lien_minh.py
Xây dựng Liên minh (xem quảng cáo + bấm xây tường thành)
- Phụ thuộc: đảm bảo đang ở Liên minh (inside) trước khi thao tác
- Ảnh: images/lien_minh/
"""

from __future__ import annotations
import time

from module import (
    log_wk as _log,
    adb_safe as _adb_safe,
    grab_screen_np as _grab_screen_np,
    find_on_frame as _find_on_frame,
    tap as _tap,
    tap_center as _tap_center,
    swipe as _swipe,
    aborted as _aborted,
    sleep_coop as _sleep_coop,
    free_img as _free_img,
    mem_relief as _mem_relief,
    DEFAULT_THR as THR_DEFAULT,
    ensure_inside_generic as _ensure_inside_generic,
    open_by_swiping as _open_by_swiping,resource_path,
)

# ========= REGIONS =========
REG_INSIDE              = (28, 3, 201, 75)           # Liên minh inside (header)
REG_OUTSIDE             = (581, 1485, 758, 1600)     # Liên minh icon (outside)

REG_BUILD_ICON          = (53, 648, 466, 805)        # xay-dung-lien-minh.png
REG_BUILD_INSIDE        = (85, 268, 420, 403)        # xay-dung-inside.png

REG_XEM_QC              = (53, 1055, 223, 1221)      # xem-quang-cao.png
REG_XEM_VIDEO           = (501, 946, 806, 1053)      # xem-video.png

REG_TUONG_THANH_ICON    = (8, 305, 630, 455)         # xay-dung-tuong-thanh.png
REG_NUT_BAM_XAY_DUNG    = (481, 1290, 835, 1468)     # nut-bam-xay-dung.png

# ========= IMAGES =========
IMG_INSIDE              = resource_path("images/lien_minh/lien-minh-inside.png")
IMG_OUTSIDE             = resource_path("images/lien_minh/lien-minh-outside.png")

IMG_BUILD_ICON          = resource_path("images/lien_minh/xay-dung-lien-minh.png")
IMG_BUILD_INSIDE        = resource_path("images/lien_minh/xay-dung-inside.png")

IMG_XEM_QC              = resource_path("images/lien_minh/xem-quang-cao.png")
IMG_XEM_VIDEO           = resource_path("images/lien_minh/xem-video.png")

IMG_TUONG_THANH_ICON    = resource_path("images/lien_minh/xay-dung-tuong-thanh.png")
IMG_NUT_BAM_XAY_DUNG    = resource_path("images/lien_minh/nut-bam-xay-dung.png")

# ========= PARAMS =========
THR_DEFAULT = 0.86
ESC_DELAY   = 1.5
CLICK_DELAY = 0.5


# ========= các bước con =========
def _ensure_inside(wk) -> bool:
    return _ensure_inside_generic(
        wk,
        IMG_OUTSIDE, REG_OUTSIDE,
        IMG_INSIDE,  REG_INSIDE,
        esc_delay=ESC_DELAY, click_delay=CLICK_DELAY
    )

def _open_build_menu(wk) -> bool:
    """
    Vuốt để mở mục 'xây dựng liên minh' rồi TAP.
    """
    # check & mở ngay nếu thấy
    img = _grab_screen_np(wk)
    ok, pt, _ = _find_on_frame(img, IMG_BUILD_ICON, region=REG_BUILD_ICON, threshold=THR_DEFAULT)
    _free_img(img)
    if ok and pt:
        _tap(wk, *pt)
        if not _sleep_coop(wk, 0.5): return False
        return True

    swipes = [
        (280, 980, 920, 980, 450),  # trái->phải (nội dung trượt sang trái)
    ]
    return _open_by_swiping(
        wk, IMG_BUILD_ICON, REG_BUILD_ICON,
        swipes=swipes, tries_each=3, settle=0.5, thr=THR_DEFAULT
    )

def _ensure_build_inside(wk) -> bool:
    for _ in range(8):
        if _aborted(wk): return False
        img = _grab_screen_np(wk)
        ok_in, _, _ = _find_on_frame(img, IMG_BUILD_INSIDE, region=REG_BUILD_INSIDE, threshold=THR_DEFAULT)
        _free_img(img)
        if ok_in:
            return True
        if not _sleep_coop(wk, 0.25): return False
    return False

def _watch_ads_loop(wk):
    while True:
        if _aborted(wk): return
        img = _grab_screen_np(wk)
        ok_qc, pt_qc, _ = _find_on_frame(img, IMG_XEM_QC, region=REG_XEM_QC, threshold=THR_DEFAULT)
        _free_img(img)
        if not ok_qc:
            break
        if pt_qc: _tap(wk, *pt_qc)
        if not _sleep_coop(wk, 0.4): return

        img2 = _grab_screen_np(wk)
        ok_vid, pt_vid, _ = _find_on_frame(img2, IMG_XEM_VIDEO, region=REG_XEM_VIDEO, threshold=THR_DEFAULT)
        _free_img(img2)
        if ok_vid and pt_vid:
            _tap(wk, *pt_vid)

        if not _sleep_coop(wk, 5.0): return
        _tap(wk, 748, 1135)  # đóng video
        if not _sleep_coop(wk, 0.7): return

    img = _grab_screen_np(wk)
    ok_build_in, _, _ = _find_on_frame(img, IMG_BUILD_INSIDE, region=REG_BUILD_INSIDE, threshold=THR_DEFAULT)
    _free_img(img)
    if ok_build_in:
        _tap(wk, 450, 1191)
        if not _sleep_coop(wk, 0.2): return
        _tap(wk, 450, 1191)
        if not _sleep_coop(wk, 0.4): return

    img = _grab_screen_np(wk)
    ok_build_in, _, _ = _find_on_frame(img, IMG_BUILD_INSIDE, region=REG_BUILD_INSIDE, threshold=THR_DEFAULT)
    _free_img(img)
    if ok_build_in:
        for (x,y) in [(291,450),(398,448),(788,453),(580,443),(466,441),(756,1130)]:
            if _aborted(wk): return
            _tap(wk, x, y)
            if not _sleep_coop(wk, 0.15): return

def _back_to_inside(wk):
    while True:
        if _aborted(wk): return
        img = _grab_screen_np(wk)
        ok_in, _, _ = _find_on_frame(img, IMG_INSIDE, region=REG_INSIDE, threshold=THR_DEFAULT)
        ok_out, _, _ = _find_on_frame(img, IMG_OUTSIDE, region=REG_OUTSIDE, threshold=THR_DEFAULT)
        _free_img(img)
        if ok_in:
            return
        if ok_out:
            _tap_center(wk, REG_OUTSIDE)
            if not _sleep_coop(wk, CLICK_DELAY): return
            continue
        _adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)
        if not _sleep_coop(wk, ESC_DELAY): return

def _build_wall(wk):
    """
    Tìm 'xay-dung-tuong-thanh.png' để bấm xây tường.
    """
    SWIPES_PER_CYCLE = 3
    MAX_CYCLES       = 10
    SWIPE_PAUSE      = 0.3

    for cycle in range(MAX_CYCLES):
        if _aborted(wk): return

        if not _ensure_inside(wk):
            return

        img = _grab_screen_np(wk)
        ok_wall, pt_wall, _ = _find_on_frame(img, IMG_TUONG_THANH_ICON, region=REG_TUONG_THANH_ICON, threshold=THR_DEFAULT)
        _free_img(img)
        if ok_wall and pt_wall:
            _tap(wk, *pt_wall)
            if not _sleep_coop(wk, 0.4): return
            break

        for _ in range(SWIPES_PER_CYCLE):
            if _aborted(wk): return
            _swipe(wk, 280, 980, 920, 980, dur_ms=450)   # kéo trái->phải (nội dung trượt sang trái)
            if not _sleep_coop(wk, SWIPE_PAUSE): return
            img = _grab_screen_np(wk)
            ok_wall, pt_wall, _ = _find_on_frame(img, IMG_TUONG_THANH_ICON, region=REG_TUONG_THANH_ICON, threshold=THR_DEFAULT)
            _free_img(img)
            if ok_wall and pt_wall:
                _tap(wk, *pt_wall)
                if not _sleep_coop(wk, 0.4): return
                break
        if ok_wall and pt_wall:
            break

        _log(wk, "↩️ 3 lần vuốt không thấy 'xây-dựng-tường-thành' → ESC đóng popup rồi tìm lại.")
        _adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)
        if not _sleep_coop(wk, ESC_DELAY): return

    else:
        _log(wk, "⚠️ Không tìm thấy 'xây-dựng-tường-thành' sau nhiều lần thử. Bỏ qua.")
        return

    # chờ nút bấm xây dựng
    MAX_WAIT_BTN = 24  # ~6 giây
    waited = 0
    while True:
        if _aborted(wk): return
        img2 = _grab_screen_np(wk)
        ok_btn, pt_btn, _ = _find_on_frame(img2, IMG_NUT_BAM_XAY_DUNG, region=REG_NUT_BAM_XAY_DUNG, threshold=THR_DEFAULT)
        _free_img(img2)
        if ok_btn and pt_btn:
            _tap(wk, *pt_btn)
            if not _sleep_coop(wk, 0.5): return
            _log(wk, "✅ Đã bấm 'nút bấm xây dựng'.")
            break
        if not _sleep_coop(wk, 0.25): return
        waited += 1
        if waited >= MAX_WAIT_BTN:
            _log(wk, "⚠️ Không thấy 'nút bấm xây dựng' trong thời gian cho phép. Bỏ qua.")
            return

# ========= entry point =========
def run_guild_build_flow(wk, log=print) -> bool:
    """
    Quy trình:
    1) Đảm bảo Liên minh inside
    2) Tìm & vào 'xây dựng liên minh'
    3) Khi đã vào build inside → xem quảng cáo
    4) Trở về Liên minh inside
    5) Xây tường thành
    """
    if _aborted(wk):
        _log(wk, "⛔ Hủy trước khi chạy Xây dựng Liên minh.")
        return False

    _log(wk, "➡️ Bắt đầu Xây dựng Liên minh")
    if not _ensure_inside(wk):
        return False

    # mở menu xây dựng và chờ vào màn hình build
    while True:
        if _aborted(wk): return False
        if _open_build_menu(wk):
            if _ensure_build_inside(wk):
                break
        _adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)
        if not _sleep_coop(wk, ESC_DELAY): return False
        if not _ensure_inside(wk): return False

    _watch_ads_loop(wk)
    if _aborted(wk): return False

    _back_to_inside(wk)
    if _aborted(wk): return False

    _build_wall(wk)
    if _aborted(wk): return False

    _log(wk, "✅ Hoàn tất Xây dựng Liên minh.")
    return True
