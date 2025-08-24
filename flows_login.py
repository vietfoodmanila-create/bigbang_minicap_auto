# flows_login.py
# (HOÀN CHỈNH) Dựa trên file gốc của bạn và thêm logic kiểm tra bảo trì.

from __future__ import annotations
import time
import cv2
import numpy as np

# ====== import toàn bộ helper dùng chung từ module.py ======
from module import (
    log_wk as _log,
    adb_safe as _adb_safe,
    tap as _tap,
    tap_center as _tap_center,
    sleep_coop as _sleep_coop,
    aborted as _aborted,
    grab_screen_np as _grab_screen_np,
    find_on_frame,
    DEFAULT_THR as _THR_DEFAULT,
    type_text as _type_text,
    back as _back,
    state_simple as _state_simple,
    free_img,resource_path
)

# ================== VÙNG ==================
REG_CLEAR_EMAIL_X = (645, 556, 751, 731)
REG_EMAIL_EMPTY = (146, 586, 756, 720)
REG_CLEAR_PASSWORD_X = (645, 688, 750, 881)
REG_PASSWORD_EMPTY = (146, 701, 755, 820)
REG_LOGIN_BUTTON = (156, 846, 761, 951)
REG_DA_DANG_NHAP = (418, 971, 650, 1068)
REG_XAC_NHAN_DANG_NHAP = (283, 875, 626, 998)
REG_GAME_LOGIN_BUTTON = (318, 1183, 590, 1308)
REG_XAC_NHAN_OFFLINE = (511, 1253, 790, 1363)
REG_ICON_LIEN_MINH = (598, 1463, 753, 1600)
REG_THONG_BAO = (315, 228, 620, 375)

# ================== ẢNH ==================
IMG_CLEAR_EMAIL_X = resource_path("images/login/clear_email_x.png")
IMG_EMAIL_EMPTY = resource_path("images/login/email_empty.png")
IMG_CLEAR_PASSWORD_X = resource_path("images/login/clear_password_x.png")
IMG_PASSWORD_EMPTY = resource_path("images/login/password_empty.png")
IMG_LOGIN_BUTTON = resource_path("images/login/login_button.png")
IMG_DA_DANG_NHAP = resource_path("images/login/da_dang_nhap.png")
IMG_XAC_NHAN_DANG_NHAP = resource_path("images/login/xac_nhan_dang_nhap.png")
IMG_GAME_LOGIN_BUTTON = resource_path("images/login/game_login_button.png")
IMG_XAC_NHAN_OFFLINE = resource_path("images/login/xac_nhan_offline.png")
IMG_ICON_LIEN_MINH = resource_path("images/login/icon_lien_minh.png")
IMG_THONG_BAO = resource_path("images/login/thong-bao.png")

# ================== GAME PKG/ACT (đồng bộ test) ==================
GAME_PKG = "com.phsgdbz.vn"
GAME_ACT = "com.phsgdbz.vn/org.cocos2dx.javascript.GameTwActivity"

GRAY_SATURATION_MAX = 25


def _is_pixel_gray(img: np.ndarray, x: int, y: int) -> tuple[bool, str]:
    if img is None:
        return False, "Không có ảnh"
    try:
        y1, x1 = max(0, y - 1), max(0, x - 1)
        y2, x2 = min(img.shape[0], y + 2), min(img.shape[1], x + 2)
        roi = img[y1:y2, x1:x2]
        hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        avg_saturation = np.mean(hsv_roi[:, :, 1])
        msg = f"Kiểm tra bảo trì tại ({x},{y}): Độ bão hòa màu = {avg_saturation:.1f}"
        return avg_saturation < GRAY_SATURATION_MAX, msg
    except Exception as e:
        return False, f"Lỗi khi kiểm tra màu pixel: {e}"


def select_server(wk, server: str) -> bool:
    if not server: return True
    _log(wk, f"(TODO) Chọn server: {server}")
    return True


def _pre_login_taps(wk):
    seq = [(690, 650, 0.15), (693, 758, 0.15), (690, 650, 0.15)]
    for x, y, delay in seq:
        if _aborted(wk): break
        _tap(wk, x, y)
        # Sử dụng _sleep_coop để an toàn
        _sleep_coop(wk, delay)


def login_once(wk, email: str, password: str, server: str = "", date: str = "") -> bool:
    if _aborted(wk): _log(wk, "⛔ Hủy trước khi login."); return False
    # Nếu không ở need_login, thử back nhẹ vài lần để lộ form
    st = _state_simple(wk, package_hint=GAME_PKG)
    if st != "need_login":
        _back(wk, times=2, wait_each=0.4)
        if not _sleep_coop(wk, 0.6): return False

    _pre_login_taps(wk)
    if _aborted(wk): return False
    # 1) Clear & nhập email
    img = _grab_screen_np(wk)
    ok, pt, sc = find_on_frame(img, IMG_CLEAR_EMAIL_X, region=REG_CLEAR_EMAIL_X, threshold=0.86)
    free_img(img)
    if ok and pt:
        _tap(wk, *pt)
        if not _sleep_coop(wk, 0.2): return False
    _tap_center(wk, REG_EMAIL_EMPTY)
    if not _sleep_coop(wk, 0.2): return False
    _type_text(wk, email)
    if not _sleep_coop(wk, 0.2): return False

    # 2) Clear & nhập password
    img = _grab_screen_np(wk)
    ok, pt, sc = find_on_frame(img, IMG_CLEAR_PASSWORD_X, region=REG_CLEAR_PASSWORD_X, threshold=0.86)
    free_img(img)
    if ok and pt:
        _tap(wk, *pt)
        if not _sleep_coop(wk, 0.2): return False
    _tap_center(wk, REG_PASSWORD_EMPTY)
    if not _sleep_coop(wk, 0.2): return False
    _type_text(wk, password)
    if not _sleep_coop(wk, 0.2): return False

    # 3) (tuỳ chọn) chọn server
    if not select_server(wk, server):
        _log(wk, "Chọn server thất bại.");
        return False
    if _aborted(wk): return False

    # 4) Nhấn Login
    img = _grab_screen_np(wk)
    ok, pt, sc = find_on_frame(img, IMG_LOGIN_BUTTON, region=REG_LOGIN_BUTTON, threshold=0.86)
    free_img(img)
    if ok and pt:
        _tap(wk, *pt)
    else:
        _tap_center(wk, REG_LOGIN_BUTTON)
    if not _sleep_coop(wk, 1.0): return False

    # ===== 5) PHA "VÀO GAME" (LOGIC ĐÚNG) =====
    pressed_once = False
    phase_deadline = time.time() + 60

    def _both_buttons(img_now):
        ok_da, _, sc_da = find_on_frame(img_now, IMG_DA_DANG_NHAP, region=REG_DA_DANG_NHAP, threshold=0.86)
        ok_game, pt_game, sc_game = find_on_frame(img_now, IMG_GAME_LOGIN_BUTTON, region=REG_GAME_LOGIN_BUTTON,
                                                  threshold=0.86)
        return ok_da, ok_game, pt_game

    while time.time() < phase_deadline:
        if _aborted(wk): return False

        img = _grab_screen_np(wk)
        if img is None:
            if not _sleep_coop(wk, 1.0): return False
            continue

        ok_da, ok_game, pt_game = _both_buttons(img)

        if ok_da and ok_game:
            is_gray, msg = _is_pixel_gray(img, 263, 1115)
            if is_gray:
                _log(wk, "⚠️ Phát hiện trò chơi đang bảo trì.")
                free_img(img);
                return False
            if pt_game:
                _tap(wk, *pt_game);
                pressed_once = True
                free_img(img);
                if not _sleep_coop(wk, 2.0): return False
                continue

        # (LOGIC ĐẦY ĐỦ) Xử lý các popup khi 2 nút chính không có
        if not ok_da and not ok_game:
            ok_tb, _, _ = find_on_frame(img, IMG_THONG_BAO, region=REG_THONG_BAO, threshold=0.86)
            if ok_tb:
                _tap(wk, 443, 1300);
                free_img(img)
                if not _sleep_coop(wk, 1.5): return False
                continue

            ok_xn, pt_xn, _ = find_on_frame(img, IMG_XAC_NHAN_DANG_NHAP, region=REG_XAC_NHAN_DANG_NHAP, threshold=0.86)
            if ok_xn and pt_xn:
                _tap(wk, *pt_xn);
                free_img(img)
                if not _sleep_coop(wk, 1.0): return False
                continue

            # Nếu đã từng bấm nút "Vào Game" thì thoát vòng lặp
            if pressed_once:
                free_img(img)
                break

        free_img(img)
        if not _sleep_coop(wk, 0.5): return False

    # ===== 6) Kiểm tra 'xác nhận offline' =====
    for _ in range(5):
        if _aborted(wk): return False
        img = _grab_screen_np(wk)
        ok, pt, sc = find_on_frame(img, IMG_XAC_NHAN_OFFLINE, region=REG_XAC_NHAN_OFFLINE, threshold=0.86)
        free_img(img)
        if ok and pt:
            _tap(wk, *pt)
            if not _sleep_coop(wk, 1.0): return False
            break
        if not _sleep_coop(wk, 0.5): return False

    # ===== 7) Đợi vào game =====
    end = time.time() + 60
    while time.time() < end:
        if _aborted(wk): return False
        st = _state_simple(wk, package_hint=GAME_PKG)
        if st == "gametw":
            img = _grab_screen_np(wk)
            ok, _, sc = find_on_frame(img, IMG_ICON_LIEN_MINH, region=REG_ICON_LIEN_MINH, threshold=0.86)
            free_img(img)
            if ok:
                return True
        if not _sleep_coop(wk, 1.0): return False

    return False