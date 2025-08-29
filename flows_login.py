# flows_login.py
# (HOÀN CHỈNH) Dựa trên file gốc của bạn và thêm logic kiểm tra bảo trì.

from __future__ import annotations
import time
import cv2
import numpy as np
from module import log_wk as log
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
    free_img,resource_path,
    ocr_region as _ocr_region
)
import unicodedata, re
from pathlib import Path
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
REG_CUR_SERVER  = (345,1083,506,1145)   # vùng hiển thị server hiện tại
REG_SERVER_ICON = (43,380,335,478)      # vùng chứa icon server.png
REG_SERVER_LIST = (318, 331, 856, 1178)    # vùng danh sách server
REG_SAI_MAT_KHAU = (198, 788, 718, 863)  # vùng hiện thông báo "sai mật khẩu"
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
IMG_SERVER_ICON = resource_path("images/server_list/server.png")
IMG_SAI_MAT_KHAU = resource_path("images/login/sai_mat_khau.png")
# ================== GAME PKG/ACT (đồng bộ test) ==================
GAME_PKG = "com.phsgdbz.vn"
GAME_ACT = "com.phsgdbz.vn/org.cocos2dx.javascript.GameTwActivity"

GRAY_SATURATION_MAX = 25
THR_SERVER_IMG  = 0.85
THR_SERVER_FIND = 0.85

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
def _update_bad_password(wk, cloud, uga_id):
    if not uga_id:
        _log(wk, "[LOGIN][BADPWD] Bỏ qua update (uga_id rỗng)."); return False
    if not cloud:
        _log(wk, "[LOGIN][BADPWD] Bỏ qua update (cloud rỗng)."); return False

    payload = {"id": int(uga_id), "status": "bad_password"}
    try:
        _log(wk, f"[LOGIN][BADPWD] POST /api/user_game_accounts/status payload={payload}")
        if hasattr(cloud, "request"):
            res = cloud.request("POST", "/api/user_game_accounts/status", json=payload)
        else:
            _log(wk, "[LOGIN][BADPWD] ❌ CloudClient không có request()."); return False

        _log(wk, f"[LOGIN][BADPWD] RESP={res}")
        ok = isinstance(res, dict) and res.get("ok") is True and ((res.get("data") or {}).get("status") == "bad_password")
        if not ok:
            _log(wk, f"[LOGIN][BADPWD] ⚠️ Server không xác nhận update."); return False

        # Verify nhanh (không bắt buộc)
        try:
            ver = cloud.request("GET", "/api/user_game_accounts/status", params={"id": int(uga_id)})
            _log(wk, f"[LOGIN][BADPWD] VERIFY RESP={ver}")
        except Exception as ve:
            _log(wk, f"[LOGIN][BADPWD] VERIFY lỗi: {ve}")

        _log(wk, f"[LOGIN][BADPWD] ✅ Đã cập nhật UGA#{uga_id} → status=bad_password")
        return True
    except Exception as e:
        _log(wk, f"[LOGIN][BADPWD] ❌ Lỗi gọi API update: {e}")
        return False

def _norm_text(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    return re.sub(r"[^a-z0-9]+", "", s)

def select_server(wk, server: str) -> bool:
    """
    server: img_url từ API, ví dụ "images/server_list/dosat-s8.png".
    Quy trình:
      1) HEADER (REG_CUR_SERVER): OCR → normalize (bỏ dấu, non-alnum, '0'->'o') → so với expected → ĐÚNG: return True.
      2) Sai → tap_center(REG_CUR_SERVER) → sleep 0.5s →
               tìm & nhấn server.png (REG_SERVER_ICON) → sleep 1.0s →
               OCR quét LIST (REG_SERVER_LIST) theo "ô" dọc (có overlap) → ô match expected thì tap → return True.
      3) Không tìm được thì return False.
    Yêu cầu: các hằng số REG_CUR_SERVER, REG_SERVER_ICON, REG_SERVER_LIST,
             IMG_SERVER_ICON (images/server_list/server.png), THR_SERVER_FIND đã khai báo bên ngoài.
             Đầu file đã import: cv2, numpy as np, _ocr_region, find_on_frame, _tap/_tap_center, _sleep_coop, _grab_screen_np, free_img, _log, resource_path.
    """

    # ---- helpers ----
    def _norm_base(s: str) -> str:
        if not s:
            return ""
        s = unicodedata.normalize("NFD", s)
        s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
        s = s.replace("đ", "d").replace("Đ", "D").lower()
        s = re.sub(r"[^a-z0-9]+", "", s)
        return s

    def _norm0(s: str) -> str:
        # Chuẩn hoá + đổi '0' thành 'o' để tránh nhầm lẫn OCR (0/o)
        return _norm_base(s).replace("0", "o")

    if not server:
        _log(wk, "[LOGIN][SV] server(img_url) rỗng → bỏ qua chọn server.")
        return True

    expected_raw  = Path(server).stem                # "dosat-s8"
    expected_norm = _norm0(expected_raw)             # "dosats8" (và '0'->'o' nếu có)
    _log(wk, f"[LOGIN][SV] EXPECTED='{expected_raw}' → norm0='{expected_norm}' | server='{server}'")

    # ---------------- 1) HEADER: OCR vùng REG_CUR_SERVER (có preprocessing ổn định) ----------------
    img0 = _grab_screen_np(wk)
    try:
        x1, y1, x2, y2 = REG_CUR_SERVER
        roi = img0[y1:y2, x1:x2].copy()
        h, w = roi.shape[:2]
        scale = 3 if max(h, w) < 60 else 2
        roi = cv2.resize(roi, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, d=7, sigmaColor=60, sigmaSpace=60)
        th   = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        mean_val = float(np.mean(th))
        if mean_val < 127.0:  # nền trắng, chữ đen
            th = cv2.bitwise_not(th)
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)), iterations=1)
        th = cv2.copyMakeBorder(th, 6, 6, 6, 6, cv2.BORDER_CONSTANT, value=255)
        prep = cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)

        txt7 = (_ocr_region(prep, 0, 0, prep.shape[1], prep.shape[0], lang="vie", psm=7) or "").strip()
        txt6 = "" if txt7 else (_ocr_region(prep, 0, 0, prep.shape[1], prep.shape[0], lang="vie", psm=6) or "").strip()
        cur_txt  = (txt7 or txt6).replace("\n", " ")
        cur_norm = _norm0(cur_txt)
        ok_hdr   = bool(cur_norm) and (cur_norm == expected_norm or expected_norm in cur_norm or cur_norm in expected_norm)
        _log(wk, f"[LOGIN][SV] HEADER-OCR-PP ROI={w}x{h} scale={scale} mean={mean_val:.1f} "
                 f"psm7='{txt7}' psm6='{txt6}' → use='{cur_txt}' norm0='{cur_norm}' "
                 f"expected='{expected_norm}' match={ok_hdr}")
        if ok_hdr:
            _log(wk, "[LOGIN][SV] ✅ HEADER khớp (OCR) → đúng server sẵn, bỏ qua chọn.")
            return True
    finally:
        free_img(img0)


    # ---------------- 2) MỞ DANH SÁCH: tap vùng hiện tại → 0.5s → tìm & nhấn server.png ----------------
    _log(wk, "[LOGIN][SV] OPEN-LIST: tap_center(REG_CUR_SERVER) → chờ 1.5s.")
    _tap_center(wk, REG_CUR_SERVER)
    if not _sleep_coop(wk, 1.5):
        return False

    img2 = _grab_screen_np(wk)
    try:
        ok_icon, pos_icon, sc_icon = find_on_frame(img2, IMG_SERVER_ICON, region=REG_SERVER_ICON, threshold=THR_SERVER_FIND)
        _log(wk, f"[LOGIN][SV] FIND ICON server.png: region={REG_SERVER_ICON} thr={THR_SERVER_FIND} "
                 f"→ ok={ok_icon} pos={pos_icon} score={sc_icon}")
    finally:
        free_img(img2)

    if not ok_icon or not pos_icon:
        _log(wk, "[LOGIN][SV] ❌ Không thấy icon server.png để mở danh sách.")
        return False

    _log(wk, f"[LOGIN][SV] TAP ICON server.png tại {pos_icon} → chờ 1.0s.")
    _tap(wk, *pos_icon)
    if not _sleep_coop(wk, 1.0):
        return False

    # ---------------- 3) DANH SÁCH: OCR quét theo các “ô” dọc trong REG_SERVER_LIST (có overlap) ----------------
    N_SLOTS = 12
    x1, y1, x2, y2 = REG_SERVER_LIST
    H = max(1, y2 - y1)
    row_h  = max(32, H // N_SLOTS)
    stride = max(20, int(row_h * 0.75))  # chồng lấn 25% để tránh cắt hụt

    img3 = _grab_screen_np(wk)
    try:
        _log(wk, f"[LOGIN][SV] SCAN-LIST reg={REG_SERVER_LIST} → row_h≈{row_h}, stride={stride}")
        i = 0
        ry1 = y1
        while ry1 + 10 < y2:
            ry2 = min(y2, ry1 + row_h)

            # OCR ô (preprocessing giống HEADER)
            roi = img3[ry1:ry2, x1:x2].copy()
            h, w = roi.shape[:2]
            scale = 3 if max(h, w) < 60 else 2
            roi = cv2.resize(roi, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            gray = cv2.bilateralFilter(gray, d=7, sigmaColor=60, sigmaSpace=60)
            th   = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            mean_val = float(np.mean(th))
            if mean_val < 127.0:
                th = cv2.bitwise_not(th)
            th = cv2.morphologyEx(th, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)), iterations=1)
            th = cv2.copyMakeBorder(th, 6, 6, 6, 6, cv2.BORDER_CONSTANT, value=255)
            prep = cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)

            t7 = (_ocr_region(prep, 0, 0, prep.shape[1], prep.shape[0], lang="vie", psm=7) or "").strip()
            t6 = "" if t7 else (_ocr_region(prep, 0, 0, prep.shape[1], prep.shape[0], lang="vie", psm=6) or "").strip()
            use_txt  = (t7 or t6).replace("\n", " ")
            use_norm = _norm0(use_txt)

            i += 1
            hit = bool(use_norm) and (use_norm == expected_norm or expected_norm in use_norm or use_norm in expected_norm)
            _log(wk, f"[LOGIN][SV] SLOT#{i:02d} reg=({x1},{ry1},{x2},{ry2}) ROI={w}x{h} scale={scale} mean={mean_val:.1f} "
                     f"psm7='{t7}' psm6='{t6}' → use='{use_txt}' norm0='{use_norm}' "
                     f"expected='{expected_norm}' match={hit}")

            if hit:
                cx = (x1 + x2) // 2
                cy = (ry1 + ry2) // 2
                _log(wk, f"[LOGIN][SV] ✅ MATCH tại SLOT#{i:02d} → TAP ({cx},{cy})")
                _tap(wk, cx, cy)
                if not _sleep_coop(wk, 0.3):
                    return False
                return True

            ry1 += stride
    finally:
        free_img(img3)

    _log(wk, "[LOGIN][SV] ❌ Không tìm thấy server theo OCR trong danh sách.")
    return False

def _pre_login_taps(wk):
    seq = [(690, 650, 0.15), (693, 758, 0.15), (690, 650, 0.15)]
    for x, y, delay in seq:
        if _aborted(wk): break
        _tap(wk, x, y)
        # Sử dụng _sleep_coop để an toàn
        _sleep_coop(wk, delay)


def login_once(wk, email: str, password: str, server: str = "", date: str = "", *, uga_id=None, cloud=None) -> bool:
    if _aborted(wk): _log(wk, "⛔ Hủy trước khi login."); return False

    # Reset cờ bad password cho vòng gọi hiện tại
    try: setattr(wk, "last_login_badpwd", False)
    except Exception: pass

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

    # 4) Nhấn Login
    img = _grab_screen_np(wk)
    ok, pt, sc = find_on_frame(img, IMG_LOGIN_BUTTON, region=REG_LOGIN_BUTTON, threshold=0.86)
    free_img(img)
    if ok and pt: _tap(wk, *pt)
    else:         _tap_center(wk, REG_LOGIN_BUTTON)
    if not _sleep_coop(wk, 1.0): return False

    # 4B) KIỂM TRA SAI MẬT KHẨU TRONG 2S (mỗi 0.25s)
    deadline = time.time() + 2.0
    while time.time() < deadline:
        img = _grab_screen_np(wk)
        ok_bad, _, sc_bad = find_on_frame(img, IMG_SAI_MAT_KHAU, region=REG_SAI_MAT_KHAU, threshold=0.90)
        free_img(img)
        _log(wk, f"[LOGIN] Check 'sai_mat_khau' → ok={ok_bad} score={sc_bad}")
        if ok_bad:
            # ĐÁNH DẤU cho runner biết: lần fail này do sai mật khẩu
            try: setattr(wk, "last_login_badpwd", True)
            except Exception: pass

            _log(wk, "[LOGIN] ❌ Sai mật khẩu → cập nhật status=bad_password và bỏ qua tài khoản.")
            if not _sleep_coop(wk, 0.1): return False

            cloud = getattr(wk, 'cloud', None)
            uga_id = getattr(wk, 'uga_id', None)  # user_game_accounts.id (nếu có)
            ga_id  = getattr(wk, 'ga_id',  None)  # game_accounts.id (fallback)

            try:
                if cloud:
                    url = cloud._url("/api/user_game_accounts/status")
                    hdr = cloud._auth_headers()
                    if uga_id:
                        pl = {"id": int(uga_id), "status": "bad_password"}
                        _log(wk, f"[LOGIN][BADPWD] POST UGA payload={pl}")
                    else:
                        pl = {"game_account_id": int(ga_id), "status": "bad_password"}
                        _log(wk, f"[LOGIN][BADPWD] POST GA  payload={pl}")
                    r = cloud.session.post(url, headers=hdr, json=pl, timeout=30)
                    data = r.json()
                    _log(wk, f"[LOGIN][BADPWD] RESP={data}")
                else:
                    _log(wk, "[LOGIN][BADPWD] Thiếu wk.cloud — bỏ qua cập nhật server.")
            except Exception as e:
                _log(wk, f"[LOGIN][BADPWD] Lỗi gọi API update: {e}")

            return False

        if not _sleep_coop(wk, 0.25): return False
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
            # 3) (tuỳ chọn) chọn server
            if not select_server(wk, server):
                _log(wk, "Chọn server thất bại.");
                return False
            if _aborted(wk): return False
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
