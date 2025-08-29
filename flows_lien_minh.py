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
def join_guild_once(wk, log=None) -> bool:
    """
    Logic xin vào liên minh (tuân thủ flow cũ, thêm 2 nhánh theo config 'guild_target'):

    - Nếu KHÔNG có user_config 'guild_target' (hoặc value rỗng):
        + Mỗi vòng: mở UI liên minh (dùng _open_guild_ui cũ) → nếu 'inside' thì DONE.
        + Nếu ở trạng thái có nút 'gia-nhap-lien-minh' → kiểm tra màu bằng _classify_join_color:
            * 'full' (xám) → ESC, đợi 15s, mở lại UI, lặp.
            * 'ok' hoặc None → TAP 'gia-nhap-lien-minh' 1 lần rồi theo dõi; vào 'inside' là DONE.
    - Nếu CÓ user_config 'guild_target' (value != ""):
        + Mỗi vòng: mở UI liên minh → nếu 'inside' thì DONE.
        + Tìm 'kiem-tra-chung.png' ở (663,156,861,243), nếu có:
            * TAP ô nhập (391,201) → xoá sạch (gửi nhiều DEL) → _type_text(value)
            * TAP nút 'kiem-tra-chung.png' 2 lần để tìm
            * Trong 2s, mỗi 0.25s kiểm tra 'chua-thay-lien-minh.png' ở (261,765,651,821):
                - Nếu THẤY → log cảnh báo đỏ, nghỉ 5 phút, return False (nhường vòng sau)
            * Nếu KHÔNG thấy 'chua-thay-lien-minh' → tìm 'gia-nhap-lien-minh.png' ở (315,1363,595,1456):
                - Nếu THẤY → TAP 2 lần; theo dõi chuyển 'inside'. Thử tối đa 2 lần TAP-2-lần.
                - Nếu KHÔNG THẤY → nếu còn đang ở 'kiem-tra-chung' thì lặp lại tìm & nhập.
            * Nếu đã TAP 'gia-nhap-lien-minh' 2 lần mà vẫn không vào 'inside':
                - Cập nhật last_leave_time = NOW qua CloudClient (tham khảo flows_thoat_lien_minh),
                  rồi return False để chuyển tài khoản khác.

    Ghi chú: dùng lại helpers/module cũ: _open_guild_ui, _classify_join_color, find_on_frame, _tap/_type_text/_sleep_coop/_adb_safe, resource_path...
    """
    from module import (
        log_wk as _log, grab_screen_np as _grab_screen_np, free_img,
        find_on_frame, tap as _tap, sleep_coop as _sleep_coop, adb_safe as _adb_safe,
        resource_path, type_text as _type_text
    )
    import time
    from datetime import datetime

    # ===== IMG & REG theo yêu cầu =====
    IMG_JOIN_BTN        = resource_path("images/lien_minh/gia-nhap.png")
    IMG_INSIDE          = resource_path("images/lien_minh/lien-minh-inside.png")
    IMG_KIEM_TRA_CHUNG  = resource_path("images/lien_minh/kiem-tra-chung.png")
    IMG_SEARCH_NOTFOUND = resource_path("images/lien_minh/chua-thay-lien-minh.png")

    REG_JOIN_BTN        = (315, 1363, 595, 1456)
    REG_KIEM_TRA_CHUNG  = (663, 156, 861, 243)
    REG_SEARCH_NOTFOUND = (261, 765, 651, 821)
    # REG_INSIDE: tuỳ ảnh 'lien-minh-inside.png' của bạn; dùng vùng an toàn quanh header trong UI inside
    REG_INSIDE          = (581, 134, 843, 228)

    # Toạ độ ô nhập cho phương án 2
    PT_SEARCH_INPUT     = (391, 201)

    THR = 0.86

    def _state_now():
        img = _grab_screen_np(wk)
        try:
            ok_inside, _, _ = find_on_frame(img, IMG_INSIDE, region=REG_INSIDE, threshold=THR)
            if ok_inside:
                return "inside", None
            ok_join, pt_join, _ = find_on_frame(img, IMG_JOIN_BTN, region=REG_JOIN_BTN, threshold=THR)
            if ok_join and pt_join:
                return "join_btn", pt_join
            ok_kc, pt_kc, _ = find_on_frame(img, IMG_KIEM_TRA_CHUNG, region=REG_KIEM_TRA_CHUNG, threshold=THR)
            if ok_kc and pt_kc:
                return "kiemtra", pt_kc
            return "unknown", None
        finally:
            free_img(img)

    def _get_guild_target() -> str:
        val = ""  # mặc định khi chưa có cấu hình / wk.cloud rỗng
        try:
            cloud = getattr(wk, "cloud", None)
            if cloud:
                # CloudClient.get_user_config() trả về CHUỖI value; 404 -> "" (không ném lỗi)
                val = str(cloud.get_user_config("guild_target") or "").strip()
            else:
                _log(wk, "[GUILD] wk.cloud rỗng — coi như chưa có config.")
        except Exception as e:
            _log(wk, f"[GUILD] get_user_config('guild_target') lỗi: {e}")
        return val

    # ===== vòng lặp tối đa 5 lần như yêu cầu =====
    join_double_taps = 0
    for round_idx in range(1, 6):
        if not _sleep_coop(wk, 0.2): return False

        # Luôn mở UI theo flow cũ (ESC → mở lại). _open_guild_ui là hàm cũ đã có trong file.
        state = _open_guild_ui(wk)
        if state == "abort":
            _log(wk, "[GUILD] Hủy mở UI liên minh."); return False
        if state == "inside":
            _log(wk, "[GUILD] Đang ở trong liên minh (inside)."); return True

        # Load config_value MỖI VÒNG (không cache)
        guild_target = _get_guild_target()
        has_target = bool(guild_target)

        # Đánh giá trạng thái hiện tại sau khi UI đã mở
        cur, pt = _state_now()
        _log(wk, f"[GUILD] Vòng {round_idx}/5 — guild_target={'<rỗng>' if not has_target else guild_target} — state={cur} pt={pt}")

        # ===== PHƯƠNG ÁN 1: KHÔNG có guild_target → đi theo join button + kiểm màu =====
        if not has_target:
            if cur == "inside":
                return True
            if cur != "join_btn" or not pt:
                # Không thấy join button → lặp
                if not _sleep_coop(wk, 0.8): return False
                continue

            # Kiểm tra màu theo code cũ
            if not _sleep_coop(wk, 0.2): return False
            join_state = _classify_join_color(wk)  # 'ok' | 'full' | None (hàm cũ)
            if join_state == "full":
                _log(wk, "🚧 Nút xin vào đang XÁM (đủ người). ESC và chờ 15s rồi thử lại…")
                _adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)  # ESC
                if not _sleep_coop(wk, 15.0): return False
                continue
            elif join_state == "ok":
                _log(wk, "✅ Nút xin vào đang XANH — tiến hành xin vào.")
            else:
                _log(wk, "ℹ️ Không chắc màu — vẫn thử xin vào.")

            _tap(wk, *pt)
            if not _sleep_coop(wk, 0.3): return False

            # Theo dõi chuyển vào 'inside' trong 10 * 0.5s
            follow_deadline = time.time() + 5.0
            while time.time() < follow_deadline:
                s2, _ = _state_now()
                if s2 == "inside":
                    _log(wk, "🎉 Đã vào liên minh (inside).")
                    return True
                if not _sleep_coop(wk, 0.5): return False
            # chưa vào — lặp vòng ngoài
            continue

        # ===== PHƯƠNG ÁN 2: CÓ guild_target → dùng 'kiem-tra-chung' để tìm theo tên
        else:
            # Bắt buộc có 'kiem-tra-chung' trên header để thao tác
            if cur != "kiemtra":
                # thử tìm lại
                img = _grab_screen_np(wk)
                try:
                    ok_kc, pt_kc, _ = find_on_frame(img, IMG_KIEM_TRA_CHUNG, region=REG_KIEM_TRA_CHUNG, threshold=THR)
                    if ok_kc and pt_kc:
                        cur, pt = "kiemtra", pt_kc
                finally:
                    free_img(img)

            if cur != "kiemtra":
                _log(wk, "[GUILD] Chưa thấy 'kiem-tra-chung' — lặp.")
                if not _sleep_coop(wk, 0.8): return False
                continue

            # Nhập tên liên minh = guild_target
            _tap(wk, *PT_SEARCH_INPUT)
            if not _sleep_coop(wk, 0.15): return False

            # Xoá sạch nội dung cũ: di chuyển về cuối rồi DEL nhiều lần
            _adb_safe(wk, "shell", "input", "keyevent", "123", timeout=2)  # KEYCODE_MOVE_END
            for _ in range(24):
                _adb_safe(wk, "shell", "input", "keyevent", "67", timeout=2)  # KEYCODE_DEL nhanh
            if not _sleep_coop(wk, 0.05): return False

            _type_text(wk, guild_target)
            if not _sleep_coop(wk, 0.15): return False

            # Bấm 'kiem-tra-chung' 2 lần
            for _ in range(2):
                img = _grab_screen_np(wk)
                try:
                    ok_kc, pt_kc, _ = find_on_frame(img, IMG_KIEM_TRA_CHUNG, region=REG_KIEM_TRA_CHUNG, threshold=THR)
                    _log(wk, f"[GUILD] TAP 'kiem-tra-chung' → ok={ok_kc} pt={pt_kc}")
                finally:
                    free_img(img)
                if ok_kc and pt_kc:
                    _tap(wk, *pt_kc)
                    if not _sleep_coop(wk, 1.0): return False

            # 2s theo dõi 'chua-thay-lien-minh'
            not_found = False
            until = time.time() + 2.0
            while time.time() < until:
                img = _grab_screen_np(wk)
                try:
                    ok_nf, _, _ = find_on_frame(img, IMG_SEARCH_NOTFOUND, region=REG_SEARCH_NOTFOUND, threshold=THR)
                finally:
                    free_img(img)
                _log(wk, f"[GUILD] Check 'chua-thay-lien-minh' → {ok_nf}")
                if ok_nf:
                    not_found = True
                    break
                if not _sleep_coop(wk, 0.25): return False

            if not_found:
                _log(wk, f"[GUILD][❗] KHÔNG TÌM THẤY liên minh '{guild_target}'. Nghỉ 5 phút rồi thử lại. Vui lòng cập nhật tên chính xác.")
                _sleep_coop(wk, 300.0)  # 5 phút
                return False

            # Nếu có kết quả — tìm nút 'gia-nhap-lien-minh' trong vùng nút
            if not _sleep_coop(wk, 2.0): return False
            img = _grab_screen_np(wk)
            try:
                ok_j, pt_j, _ = find_on_frame(img, IMG_JOIN_BTN, region=REG_JOIN_BTN, threshold=THR)
                _log(wk, f"[GUILD] Tìm 'gia-nhap-lien-minh' → ok={ok_j} pt={pt_j}")
            finally:
                free_img(img)

            if ok_j and pt_j:
                # Bấm 2 lần như yêu cầu rồi theo dõi
                _tap(wk, *pt_j)
                if not _sleep_coop(wk, CLICK_DELAY): return False
                _tap(wk, *pt_j)
                join_double_taps += 1
                _log(wk, f"[GUILD] Đã TAP 'gia-nhap-lien-minh' 2 lần (lần {join_double_taps}/2).")

                # Theo dõi chuyển 'inside'
                until2 = time.time() + 5.0
                while time.time() < until2:
                    s2, _ = _state_now()
                    if s2 == "inside":
                        _log(wk, "🎉 Đã vào liên minh (inside) sau khi Join theo tên.")
                        return True
                    if not _sleep_coop(wk, 0.5): return False

                if join_double_taps >= 2:
                    # Cập nhật last_leave_time = NOW rồi dừng tài khoản này
                    cloud = getattr(wk, "cloud", None)
                    ga_id = getattr(wk, "ga_id", None)
                    if cloud and ga_id:
                        try:
                            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            cloud.update_game_account(int(ga_id), {"last_leave_time": now})
                            _log(wk, f"[GUILD] 📝 Cập nhật last_leave_time={now} do Join 2 lượt không thành.")
                        except Exception as e:
                            _log(wk, f"[GUILD] ⚠️ Lỗi cập nhật last_leave_time: {e}")
                    return False

                # chưa đủ 2 lần — lặp vòng ngoài để thử lại
                continue

            else:
                # Không thấy join button; nếu vẫn còn 'kiem-tra-chung' thì lặp lại nhập/kiểm tra
                _log(wk, "[GUILD] Không thấy nút 'gia-nhap-lien-minh'; thử lại quy trình tìm.")
                if not _sleep_coop(wk, 0.8): return False
                continue

    _log(wk, "[GUILD] Hết 5 vòng thử xin vào — dừng.")
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
