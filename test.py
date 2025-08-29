# ==== JOIN GUILD (LIÊN MINH) DUAL MODE ====
from __future__ import annotations
import time

# Các tiện ích từ module.py
from module import (
    log_wk, adb_safe,
    grab_screen_np, find_on_frame,
    tap, tap_center, sleep_coop, aborted,
    free_img, mem_relief, resource_path
)

# ===== REGIONS (theo toạ độ bạn yêu cầu) =====
REG_OUTSIDE         = (581, 1485, 758, 1600)        # lien-minh-outside.png
REG_INSIDE          = (28, 3, 201, 75)              # lien-minh-inside.png

REG_KIEM_TRA_CHUNG  = (663, 156, 861, 243)          # kiem-tra-chung.png
REG_JOIN_BTN        = (315, 1363, 595, 1456)        # gia-nhap-lien-minh.png (nút JOIN)
REG_NOT_FOUND       = (261, 765, 651, 821)          # chua-thay-lien-minh.png

# ===== IMAGES =====
IMG_OUTSIDE         = resource_path("images/lien_minh/lien-minh-outside.png")
IMG_INSIDE          = resource_path("images/lien_minh/lien-minh-inside.png")
IMG_JOIN            = resource_path("images/lien_minh/gia-nhap-lien-minh.png")
IMG_KIEM_TRA_CHUNG  = resource_path("images/lien_minh/kiem-tra-chung.png")
IMG_NOT_FOUND       = resource_path("images/lien_minh/chua-thay-lien-minh.png")

THR_DEFAULT = 0.86

# === helper: lấy config guild_target mỗi vòng (qua cloud client nếu có) ===
def _fetch_guild_target(cloud) -> str:
    try:
        if cloud is None:
            return ""
        # API client đã được bạn sửa để trả string value
        return str(cloud.get_user_config("guild_target") or "")
    except Exception:
        return ""

def _now_dt_str_for_api() -> str:
    # runner của bạn có sẵn hàm tương tự; nếu đã có thì dùng lại
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

# === helper: đảm bảo mở UI Liên minh (ESC -> tap outside) ===
def _open_guild_panel(wk) -> bool:
    # ESC cho tới khi thấy outside
    while True:
        if aborted(wk): return False
        img = grab_screen_np(wk)
        ok_out, _, _ = find_on_frame(img, IMG_OUTSIDE, region=REG_OUTSIDE, thr=THR_DEFAULT)
        free_img(img)
        if ok_out:
            break
        adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)  # ESC
        if not sleep_coop(wk, 1.0): return False

    # TAP outside -> đợi 1s
    tap_center(wk, REG_OUTSIDE)
    return sleep_coop(wk, 1.0)

# === helper: dò trạng thái theo PHƯƠNG ÁN 1 (không có guild_target) ===
def _probe_state_mode1(wk, max_try=5):
    """
    Thử tối đa max_try:
      - Nếu thấy JOIN ở REG_JOIN_BTN -> ('join', pt_join)
      - Nếu thấy INSIDE ở REG_INSIDE  -> ('inside', None)
      - Nếu chưa thấy -> lặp
    """
    for _ in range(max_try):
        if aborted(wk): return ("abort", None)
        img = grab_screen_np(wk)
        ok_join, pt_join, _ = find_on_frame(img, IMG_JOIN, region=REG_JOIN_BTN, thr=THR_DEFAULT)
        if ok_join and pt_join:
            free_img(img)
            return ("join", pt_join)
        ok_in, _, _ = find_on_frame(img, IMG_INSIDE, region=REG_INSIDE, thr=THR_DEFAULT)
        free_img(img)
        if ok_in:
            return ("inside", None)
        if not sleep_coop(wk, 0.35): return ("abort", None)
    return (None, None)

# === helper: dò trạng thái theo PHƯƠNG ÁN 2 (có guild_target) ===
def _probe_state_mode2(wk, max_try=5):
    """
    Thử tối đa max_try:
      - Nếu thấy KIỂM TRA CHUNG ở REG_KIEM_TRA_CHUNG -> ('kc', pt_kc)
      - Nếu thấy INSIDE -> ('inside', None)
      - Nếu chưa -> lặp
    """
    for _ in range(max_try):
        if aborted(wk): return ("abort", None)
        img = grab_screen_np(wk)
        ok_kc, pt_kc, _ = find_on_frame(img, IMG_KIEM_TRA_CHUNG, region=REG_KIEM_TRA_CHUNG, thr=THR_DEFAULT)
        if ok_kc and pt_kc:
            free_img(img)
            return ("kc", pt_kc)
        ok_in, _, _ = find_on_frame(img, IMG_INSIDE, region=REG_INSIDE, thr=THR_DEFAULT)
        free_img(img)
        if ok_in:
            return ("inside", None)
        if not sleep_coop(wk, 0.35): return ("abort", None)
    return (None, None)

# === helper: gõ text vào ô tìm kiếm (391,201) ===
def _clear_and_type(wk, text: str):
    # Tap vào ô
    tap(wk, 391, 201)
    if not sleep_coop(wk, 0.1): return False
    # Không dựa Ctrl+A (khó qua adb); xoá sạch bằng DEL nhiều lần
    for _ in range(24):
        adb_safe(wk, "shell", "input", "keyevent", "67", timeout=1)  # DEL
    if not sleep_coop(wk, 0.1): return False
    # Gõ text (validator bạn đã cấm whitespace)
    adb_safe(wk, "shell", "input", "text", text, timeout=2)
    return sleep_coop(wk, 0.1)

# === helper: kiểm tra “chưa thấy liên minh” trong 2s, 0.25s/nhịp ===
def _check_not_found_quick(wk, timeout_sec=2.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        if aborted(wk): return False
        img = grab_screen_np(wk)
        ok_nf, _, _ = find_on_frame(img, IMG_NOT_FOUND, region=REG_NOT_FOUND, thr=THR_DEFAULT)
        free_img(img)
        if ok_nf:
            return True
        if not sleep_coop(wk, 0.25): return False
    return False

# === helper: phân loại màu nút JOIN (nếu bạn đã có sẵn _classify_join_color) ===
def _classify_join_color(wk) -> str | None:
    """
    Trả 'ok' | 'full' | None
    (Bạn đã có hàm tương tự; nếu có rồi, dùng lại hàm cũ.)
    """
    try:
        from flows_utils import classify_join_color as _impl  # ví dụ
        return _impl(wk)
    except Exception:
        return None

# === entry: JOIN FLOW ===
def join_guild_once(wk, cloud=None, account_id: int | None = None, log=print) -> bool:
    """
    Hai phương án:
      - Phương án 1 (không có guild_target): JOIN ngay khi thấy nút 'Gia nhập liên minh'
      - Phương án 2 (có guild_target): Dùng 'Kiểm tra chung' để tìm liên minh theo tên, rồi JOIN

    Yêu cầu thêm:
      - Mỗi vòng lặp phải load lại guild_target (không tái sử dụng cache)
      - Nếu 2 lần double-click JOIN mà vẫn không vào 'inside' -> cập nhật last_leave_time rồi kết thúc vòng cho account này
      - Nếu thấy 'chưa-thấy-liên-minh' -> nghỉ 5 phút và log đỏ
    """
    if aborted(wk):
        mem_relief()
        return False

    # 1) Mở UI Liên minh (ESC -> tap outside)
    if not _open_guild_panel(wk):
        mem_relief()
        return False

    # 2) Lấy guild_target mỗi vòng
    guild_target = _fetch_guild_target(cloud)
    has_target = bool(guild_target.strip())

    # 3) Thử tối đa 5 lần nhận diện trạng thái ban đầu
    if has_target:
        state, pt = _probe_state_mode2(wk, max_try=5)  # 'kc' | 'inside'
    else:
        state, pt = _probe_state_mode1(wk, max_try=5)  # 'join' | 'inside'

    if state == "abort":
        mem_relief()
        return False
    if state == "inside":
        log_wk(wk, "✅ Đã ở trong Liên minh (inside) — không cần xin vào.")
        mem_relief()
        return True

    # ================= PHƯƠNG ÁN 1 =================
    if not has_target and state == "join":
        # Kiểm tra màu JOIN trước khi bấm
        if not sleep_coop(wk, 0.2):
            mem_relief()
            return False
        join_state = _classify_join_color(wk)  # 'ok' | 'full' | None
        if join_state == "full":
            log_wk(wk, "🚧 Nút xin vào đang XÁM (đủ người). ESC, đợi 15s rồi thử lại…")
            adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)  # ESC
            if not sleep_coop(wk, 15.0):
                mem_relief()
                return False
            # mở lại
            if not _open_guild_panel(wk):
                mem_relief()
                return False
            # kiểm tra lại nhanh
            st2, _ = _probe_state_mode1(wk, max_try=5)
            if st2 == "inside":
                log_wk(wk, "🎉 Trong thời gian chờ đã vào liên minh (inside).")
                mem_relief()
                return True
            # nếu vẫn join -> tiếp tục bên dưới

        elif join_state == "ok":
            log_wk(wk, "✅ Nút xin vào đang XANH (còn slot) — tiến hành xin vào.")
        else:
            log_wk(wk, "ℹ️ Không chắc theo màu — vẫn thử xin vào.")

        # Nhấn JOIN
        tap(wk, *pt)
        if not sleep_coop(wk, 0.3):
            mem_relief()
            return False

        # Xác nhận outcome: INSIDE hay vẫn ở ngoài
        st3, _ = _probe_state_mode1(wk, max_try=5)
        if st3 == "inside":
            log_wk(wk, "🎯 Xin vào Liên minh thành công (inside).")
            mem_relief()
            return True
        # Nếu chưa vào được: để runner lặp lại vòng sau
        mem_relief()
        return False

    # ================= PHƯƠNG ÁN 2 =================
    if has_target and state == "kc":
        # pt là toạ độ nút 'Kiểm tra chung' (nút tìm)
        # 1) Gõ tên liên minh
        if not _clear_and_type(wk, guild_target):
            mem_relief()
            return False

        # 2) Bấm 'Kiểm tra chung' 2 lần
        tap(wk, *pt)
        if not sleep_coop(wk, 0.25):
            mem_relief(); return False
        tap(wk, *pt)
        if not sleep_coop(wk, 0.2):
            mem_relief(); return False

        # 3) Kiểm tra nhanh “chưa thấy liên minh”
        if _check_not_found_quick(wk, timeout_sec=2.0):
            log_wk(wk, "🔴 KHÔNG tìm thấy liên minh theo tên cấu hình. Nghỉ 5 phút và yêu cầu người dùng cập nhật tên.")
            # nghỉ 5 phút
            if not sleep_coop(wk, 300.0):
                mem_relief()
                return False
            mem_relief()
            return False

        # 4) Thử bấm JOIN (nếu xuất hiện), nếu chưa có JOIN thì quay lại KC và lặp
        join_double_cycles = 0
        while True:
            if aborted(wk):
                mem_relief()
                return False

            # Thử tìm JOIN tại vùng chỉ định
            img = grab_screen_np(wk)
            ok_join, pt_join, _ = find_on_frame(img, IMG_JOIN, region=REG_JOIN_BTN, thr=THR_DEFAULT)
            free_img(img)

            if ok_join and pt_join:
                # Double click JOIN
                tap(wk, *pt_join)
                if not sleep_coop(wk, 0.2): mem_relief(); return False
                tap(wk, *pt_join)
                if not sleep_coop(wk, 0.5): mem_relief(); return False

                # Kiểm tra INSIDE / KC
                st_after, _ = _probe_state_mode2(wk, max_try=5)
                if st_after == "inside":
                    log_wk(wk, "🎯 Xin vào Liên minh thành công (inside).")
                    mem_relief()
                    return True

                # vẫn thấy 'Kiểm tra chung' -> lặp thêm 1 vòng (tối đa 2 cycles)
                join_double_cycles += 1
                if join_double_cycles >= 2:
                    # cập nhật last_leave_time nếu có cloud+account_id
                    try:
                        if cloud is not None and account_id is not None:
                            cloud.update_game_account(account_id, {'last_leave_time': _now_dt_str_for_api()})
                            log_wk(wk, "📝 [API] Cập nhật mốc rời liên minh cuối do JOIN không thành công sau 2 lần.")
                    except Exception as e:
                        log_wk(wk, f"⚠️ [API] Không cập nhật được last_leave_time: {e}")
                    mem_relief()
                    return False

                # quay về bước KC: bấm lại nút KC 2 lần
                tap(wk, *pt)
                if not sleep_coop(wk, 0.25): mem_relief(); return False
                tap(wk, *pt)
                if not sleep_coop(wk, 0.25): mem_relief(); return False
                continue

            # Không thấy JOIN -> nếu còn ở màn KC thì lặp lại quá trình KC
            img2 = grab_screen_np(wk)
            ok_kc, _, _ = find_on_frame(img2, IMG_KIEM_TRA_CHUNG, region=REG_KIEM_TRA_CHUNG, thr=THR_DEFAULT)
            free_img(img2)

            if ok_kc:
                # bấm lại KC 2 lần (làm mới danh sách)
                tap(wk, *pt)
                if not sleep_coop(wk, 0.25): mem_relief(); return False
                tap(wk, *pt)
                if not sleep_coop(wk, 0.25): mem_relief(); return False
                # rồi quay vòng tra lại
                continue

            # nếu không còn KC -> thử INSIDE
            st_after2, _ = _probe_state_mode2(wk, max_try=5)
            if st_after2 == "inside":
                log_wk(wk, "🎯 Xin vào Liên minh thành công (inside).")
                mem_relief()
                return True

            # không KC, không INSIDE -> thoát để runner thử vòng sau
            mem_relief()
            return False

    # Không xác định được trạng thái phù hợp -> để runner lặp vòng sau
    mem_relief()
    return False
