# flows_logout.py — chỉ giữ logic đặc thù, mọi helper đã import từ module.py
from __future__ import annotations
import time

from module import (
    log_wk as log,
    adb_safe,
    grab_screen_np,
    find_on_frame,
    tap,
    tap_center,
    free_img,
    mem_relief,
    back,
    state_simple,
    pt_in_region,
    esc_soft_clear,
    is_green_pixel,
    wait_state,resource_path
)

USE_CV = True  # cần opencv-python

# ================= REGIONS =================
REG_DA_DANG_NHAP        = (416, 996, 596, 1050)
REG_XAC_NHAN_THOAT      = (473, 878, 788, 1011)
REG_DOI_TAI_KHOAN       = (490, 1105, 768, 1230)
REG_XAC_NHAN_DOI_TK     = (496, 891, 776, 1010)
MENU_REGION             = (0, 580, 81, 688)
REG_CAI_DAT             = (13, 803, 275, 943)

REG_PHU_DE              = (0, 1466, 170, 1588)
REG_NUT_QUAY_LAI        = (3, 1348, 175, 1596)

REG_NUT_CAI_DAT         = (33, 773, 140, 905)

# ================= TEMPLATES =================
IMG_DA_DANG_NHAP        = resource_path("images/thoat_tai_khoan/da-dang-nhap.png")
IMG_XAC_NHAN_THOAT      = resource_path("images/thoat_tai_khoan/xac-nhan-thoat.png")
IMG_NUT_MENU            = resource_path("images/thoat_tai_khoan/nut-menu.png")
IMG_CAI_DAT             = resource_path("images/thoat_tai_khoan/cai-dat.png")
IMG_DOI_TAI_KHOAN       = resource_path("images/thoat_tai_khoan/doi-tai-khoan.png")
IMG_XAC_NHAN_DOI_TK     = resource_path("images/thoat_tai_khoan/xac-nhan-doi-tk.png")

IMG_PHU_DE              = resource_path("images/thoat_tai_khoan/phu-de.png")
IMG_NUT_QUAY_LAI        = resource_path("images/thoat_tai_khoan/nut-quay-lai.png")
IMG_NUT_CAI_DAT         = resource_path("images/thoat_tai_khoan/nut-cai-dat.png")

# ================= TIỆN ÍCH NHỎ (bổ sung) =================
def _grace_check_need_login(wk, secs: float = 2.0) -> bool:
    """
    Chờ ngắn 'need_login' nếu đang chuyển cảnh. Trả True nếu đã vào màn đăng nhập.
    Dùng trước khi ESC/lặp round để tránh làm lỗi giao diện khi game đang loading sang need_login.
    """
    if wait_state(wk, target="need_login", timeout=secs):
        log(wk, "→ Vừa chuyển sang màn hình đăng nhập (need_login).")
        return True
    return False

# ================= ĐẶC THÙ FLOW =================
def _try_click_da_dang_nhap(wk) -> bool:
    log(wk, "Tìm nút 'ĐÃ ĐĂNG NHẬP'…")
    img = grab_screen_np(wk)
    ok, pt, sc = find_on_frame(img, IMG_DA_DANG_NHAP, region=REG_DA_DANG_NHAP, threshold=0.85)
    free_img(img)
    log(wk, f"KQ 'da-dang-nhap': ok={ok}, score={sc:.3f}, pt={pt}")
    if ok and pt:
        tap(wk, *pt)
        return True
    return False

def _confirm_thoat_on_frame(wk, tries=6) -> bool:
    log(wk, "Chờ 'XÁC NHẬN THOÁT'…")
    for t in range(1, tries+1):
        img = grab_screen_np(wk)
        ok, pt, sc = find_on_frame(img, IMG_XAC_NHAN_THOAT, region=REG_XAC_NHAN_THOAT, threshold=0.85)
        if not ok:
            ok, pt, sc = find_on_frame(img, IMG_XAC_NHAN_THOAT, region=None, threshold=0.85)
        log(wk, f"[Try {t}/{tries}] xac-nhan-thoat: ok={ok}, sc={sc:.3f}, pt={pt}")
        free_img(img)
        if ok and pt:
            tap(wk, *pt)
            return True
        time.sleep(0.25)
    return False

def _menu_settings_switch_menuimg(wk) -> bool:
    """
    Nhánh PA1:
      - Bấm 'menu' → thấy 'cài đặt' (đúng vùng) → CHÈN chuỗi tap phụ:
        (131,870) → 1s → nếu pixel(180,720) KHÔNG xanh thì tap(180,720) → tap(623,1166) → 1s → tap(623,948)
        → nếu đã về 'need_login' thì DONE; nếu chưa thì quay logic cũ: vào 'Cài đặt' → 'Đổi tài khoản' → 'Xác nhận'.
    """
    # tìm nút menu
    img = grab_screen_np(wk)
    ok, pt, sc = find_on_frame(img, IMG_NUT_MENU, region=MENU_REGION, threshold=0.88)
    log(wk, f"Tìm 'nut-menu.png' trong vùng {MENU_REGION}…")
    log(wk, f"KQ 'nut-menu': ok={ok}, sc={sc:.3f}, pt={pt}")
    free_img(img)
    if not ok or not pt_in_region(pt, MENU_REGION):
        # Trước khi bắt đầu ESC, chờ grace need_login 1.2s
        if _grace_check_need_login(wk, 1.2):
            return True
        log(wk, "Không thấy menu → ESC x3 rồi thử lại…")
        esc_soft_clear(wk, times=3, wait_each=1.0)
        img = grab_screen_np(wk)
        ok, pt, sc = find_on_frame(img, IMG_NUT_MENU, region=MENU_REGION, threshold=0.88)
        log(wk, f"KQ thử lại 'nut-menu': ok={ok}, sc={sc:.3f}, pt={pt}")
        free_img(img)
        if not ok or not pt_in_region(pt, MENU_REGION):
            return False

    # bấm menu → đợi → tìm 'cài đặt'
    tap(wk, *pt)
    time.sleep(1.5)
    # Chờ grace need_login ngắn trước khi dò ảnh (đề phòng UI vừa nhảy ra màn login)
    if _grace_check_need_login(wk, 1.0):
        mem_relief()
        return True

    img = grab_screen_np(wk)
    ok, pt, sc = find_on_frame(img, IMG_CAI_DAT, region=REG_CAI_DAT, threshold=0.90)
    log(wk, f"KQ 'cai-dat' (vùng {REG_CAI_DAT}): ok={ok}, sc={sc:.3f}, pt={pt}")
    free_img(img)
    if not ok or not pt_in_region(pt, REG_CAI_DAT):
        # grace check trước khi ESC spam
        if _grace_check_need_login(wk, 1.2):
            mem_relief()
            return True
        log(wk, "Không thấy 'cai-dat' đúng vùng → ESC x3 rồi thử lại…")
        esc_soft_clear(wk, times=3, wait_each=1.0)
        img = grab_screen_np(wk)
        ok, pt, sc = find_on_frame(img, IMG_CAI_DAT, region=REG_CAI_DAT, threshold=0.90)
        free_img(img)
        if not ok or not pt_in_region(pt, REG_CAI_DAT):
            return False

    # ===== Chuỗi TAP phụ trước khi logout cũ =====
    log(wk, "↪ Gặp 'cài đặt' — thực hiện chuỗi tap phụ trước khi tiếp tục logout cũ…")
    tap(wk, 131, 870)
    time.sleep(1.0)

    if not is_green_pixel(wk, 180, 720):
        tap(wk, 180, 720)

    tap(wk, 623, 1166)
    time.sleep(1.0)
    tap(wk, 623, 948)

    if wait_state(wk, target="need_login", timeout=2):
        log(wk, "✅ Thoát nhanh thành công sau chuỗi tap phụ.")
        mem_relief()
        return True
    # ===== /Chuỗi TAP phụ =====

    # (tiếp tục) — bấm 'cài đặt'
    tap(wk, *pt)
    time.sleep(0.25)

    # Đổi tài khoản
    img = grab_screen_np(wk)
    ok, pt, sc = find_on_frame(img, IMG_DOI_TAI_KHOAN, region=REG_DOI_TAI_KHOAN, threshold=0.88)
    if not ok:
        ok, pt, sc = find_on_frame(img, IMG_DOI_TAI_KHOAN, threshold=0.88)
    log(wk, f"KQ 'doi-tai-khoan': ok={ok}, sc={sc:.3f}, pt={pt}")
    free_img(img)
    if not ok or not pt:
        return False
    tap(wk, *pt)
    time.sleep(0.25)

    # Xác nhận đổi TK
    img = grab_screen_np(wk)
    ok, pt, sc = find_on_frame(img, IMG_XAC_NHAN_DOI_TK, region=REG_XAC_NHAN_DOI_TK, threshold=0.88)
    if not ok:
        ok, pt, sc = find_on_frame(img, IMG_XAC_NHAN_DOI_TK, threshold=0.88)
    log(wk, f"KQ 'xac-nhan-doi-tk': ok={ok}, sc={sc:.3f}, pt={pt}")
    free_img(img)
    if ok and pt:
        tap(wk, *pt)
        return True
    return False

# ================== LOGIC CHÍNH ==================
def logout_once(wk, max_rounds: int = 5) -> bool:
    """
    PA1 (tối đa 5 vòng):
      1) 'đã đăng nhập' → 'xác nhận thoát' → chờ need_login.
      2) hoặc 'menu' → 'cài đặt' → 'đổi tài khoản' → 'xác nhận'.
      3) nếu có 'phu-de' hoặc 'nut-quay-lai' → ESC nhịp tới khi thấy 'menu' rồi (2).

    PA2 (fallback):
      ESC → 1s → tap(38,36) → 1s → tìm 'nut-cai-dat' (vùng REG_NUT_CAI_DAT)
      → vào cài đặt → 'đổi tài khoản' → 'xác nhận' → need_login.
    """
    # -------- PA1
    for i in range(1, max_rounds + 1):
        st = state_simple(wk)
        log(wk, f"LOGOUT PA1 round {i}/{max_rounds} — state={st}")

        # Nếu đã là need_login thì xong
        if st == "need_login":
            log(wk, "→ Đã ở màn hình login. DONE.")
            mem_relief()
            return True

        # NEW: grace chờ chuyển cảnh need_login ngắn trước khi làm gì khác
        if _grace_check_need_login(wk, 2.0):
            mem_relief()
            return True

        # 1) 'ĐÃ ĐĂNG NHẬP'
        if _try_click_da_dang_nhap(wk):
            time.sleep(0.2)
            if _confirm_thoat_on_frame(wk, tries=6):
                # Chờ need_login dài tiêu chuẩn
                if wait_state(wk, "need_login", timeout=6):
                    log(wk, "→ Thoát OK (nhánh 'ĐÃ ĐĂNG NHẬP').")
                    mem_relief()
                    return True
                # Nếu chưa kịp → grace thêm trước khi next round
                if _grace_check_need_login(wk, 2.0):
                    mem_relief()
                    return True

        # 2) Thử thấy 'menu'
        img = grab_screen_np(wk)
        ok_menu, pt_menu, _ = find_on_frame(img, IMG_NUT_MENU, region=MENU_REGION, threshold=0.88)
        free_img(img)
        if ok_menu and pt_in_region(pt_menu, MENU_REGION):
            if _menu_settings_switch_menuimg(wk):
                if wait_state(wk, "need_login", timeout=6) or _grace_check_need_login(wk, 2.0):
                    log(wk, "→ Thoát OK (nhánh menu/cài đặt).")
                    mem_relief()
                    return True
        else:
            # 3a) Có 'phu-de' → ESC 1.5s cho tới khi thấy menu
            img = grab_screen_np(wk)
            ok_phude, _, _ = find_on_frame(img, IMG_PHU_DE, region=REG_PHU_DE, threshold=0.88)
            free_img(img)
            if ok_phude:
                log(wk, "Thấy 'phu-de' → ESC 1.5s cho tới khi thấy menu…")
                for _ in range(20):
                    # grace check trước mỗi lần ESC
                    if _grace_check_need_login(wk, 1.0):
                        mem_relief()
                        return True
                    esc_soft_clear(wk, times=1, wait_each=1.5)
                    img = grab_screen_np(wk)
                    ok_menu, pt_menu, _ = find_on_frame(img, IMG_NUT_MENU, region=MENU_REGION, threshold=0.88)
                    free_img(img)
                    if ok_menu and pt_in_region(pt_menu, MENU_REGION):
                        if _menu_settings_switch_menuimg(wk):
                            if wait_state(wk, "need_login", timeout=6) or _grace_check_need_login(wk, 2.0):
                                log(wk, "→ Thoát OK (phu-de → menu/cài đặt).")
                                mem_relief()
                                return True
                continue

            # 3b) Có 'nut-quay-lai' → ESC 1.0s cho tới khi thấy menu
            img = grab_screen_np(wk)
            ok_back_btn, _, _ = find_on_frame(img, IMG_NUT_QUAY_LAI, region=REG_NUT_QUAY_LAI, threshold=0.88)
            free_img(img)
            if ok_back_btn:
                log(wk, "Thấy 'nut-quay-lai' → ESC 1.0s cho tới khi thấy menu…")
                for _ in range(20):
                    # grace check trước mỗi lần ESC
                    if _grace_check_need_login(wk, 1.0):
                        mem_relief()
                        return True
                    esc_soft_clear(wk, times=1, wait_each=1.0)
                    img = grab_screen_np(wk)
                    ok_menu, pt_menu, _ = find_on_frame(img, IMG_NUT_MENU, region=MENU_REGION, threshold=0.88)
                    free_img(img)
                    if ok_menu and pt_in_region(pt_menu, MENU_REGION):
                        if _menu_settings_switch_menuimg(wk):
                            if wait_state(wk, "need_login", timeout=6) or _grace_check_need_login(wk, 2.0):
                                log(wk, "→ Thoát OK (quay-lai → menu/cài đặt).")
                                mem_relief()
                                return True
                continue

        # Vòng kế tiếp — trước khi ESC nhẹ, chờ grace need_login 0.8s
        if _grace_check_need_login(wk, 0.8):
            mem_relief()
            return True
        esc_soft_clear(wk, times=1, wait_each=1.0)
        time.sleep(0.3)

    # -------- PA2 (fallback)
    log(wk, "PA1 không thành công → chuyển PA2.")
    while True:
        # Grace check trước mỗi chu kỳ PA2
        if _grace_check_need_login(wk, 1.0):
            mem_relief()
            return True

        esc_soft_clear(wk, times=1, wait_each=1.0)
        tap(wk, 38, 36)
        time.sleep(1.0)

        # Tìm nút 'cài đặt' trong vùng REG_NUT_CAI_DAT
        for _ in range(12):
            if _grace_check_need_login(wk, 1.0):
                mem_relief()
                return True

            img = grab_screen_np(wk)
            ok, pt, sc = find_on_frame(img, IMG_NUT_CAI_DAT, region=REG_NUT_CAI_DAT, threshold=0.88)
            log(wk, f"Tìm 'nut-cai-dat' (vùng {REG_NUT_CAI_DAT}): ok={ok}, sc={sc:.3f}, pt={pt}")
            free_img(img)
            if ok and pt and pt_in_region(pt, REG_NUT_CAI_DAT):
                tap(wk, *pt)    # vào Cài đặt
                time.sleep(0.25)

                img = grab_screen_np(wk)
                ok2, pt2, _ = find_on_frame(img, IMG_DOI_TAI_KHOAN, region=REG_DOI_TAI_KHOAN, threshold=0.88)
                if not ok2:
                    ok2, pt2, _ = find_on_frame(img, IMG_DOI_TAI_KHOAN, threshold=0.88)
                free_img(img)
                if not ok2 or not pt2:
                    break
                tap(wk, *pt2)
                time.sleep(0.25)

                img = grab_screen_np(wk)
                ok3, pt3, _ = find_on_frame(img, IMG_XAC_NHAN_DOI_TK, region=REG_XAC_NHAN_DOI_TK, threshold=0.88)
                if not ok3:
                    ok3, pt3, _ = find_on_frame(img, IMG_XAC_NHAN_DOI_TK, threshold=0.88)
                free_img(img)
                if ok3 and pt3:
                    tap(wk, *pt3)
                    if wait_state(wk, "need_login", timeout=8) or _grace_check_need_login(wk, 2.0):
                        log(wk, "→ Thoát OK (PA2).")
                        mem_relief()
                        return True
                break

            # chưa thấy → làm lại chu trình
            esc_soft_clear(wk, times=1, wait_each=1.0)
            tap(wk, 38, 36)
            time.sleep(1.0)

        log(wk, "PA2 chưa thành công, lặp lại…")
        mem_relief()
