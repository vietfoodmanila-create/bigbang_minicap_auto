# -*- coding: utf-8 -*-
"""
flows_chuc_phuc.py
Flow Chúc phúc: OCR theo "slot" trong một VÙNG giống logic quét server ở login.
- Quét vùng (321,186,555,1240), chia dải dọc thành nhiều "ô" chồng lấn -> OCR -> normalize (bỏ dấu, non-alnum, '0'->'o')
- So khớp với danh sách target.
- Khi match:
    Tap #1: (270, y_center_slot)
    Đợi 1.0s -> tìm 'images/chuc_phuc/chuc-phuc.png' -> Tap #2
    Tap #3: (366, 83)
- Giữ vuốt/đợi như cũ, log chi tiết từng bước.
"""

from __future__ import annotations
import time
from typing import List, Tuple, Optional
from pathlib import Path
import unicodedata, re

import cv2
import numpy as np

from module import (
    grab_screen_np, find_on_frame, tap, tap_center, swipe,
    sleep_coop, free_img, adb_safe, ocr_region,
    log_wk as _log, resource_path,
)

# ---------------- Template paths (đặt trong images/chuc_phuc) ----------------
IMG_MENU       = resource_path("images/chuc_phuc/nut-menu.png")
IMG_GUILD_OUT  = resource_path("images/chuc_phuc/lien-minh-outside.png")
IMG_RANK       = resource_path("images/chuc_phuc/bang-xep-hang.png")
IMG_BTN_RANK   = resource_path("images/chuc_phuc/nut-xep-hang.png")
IMG_BTN_SERVER = resource_path("images/chuc_phuc/lien-server.png")
IMG_BLESS_BTN  = resource_path("images/chuc_phuc/chuc-phuc.png")  # Nút 'Chúc phúc' (Tap #2)

# ---------------- Vùng tìm kiếm (x1,y1,x2,y2) ----------------
REG_MENU       = (0, 580, 81, 688)
REG_GUILD_OUT  = (581, 1485, 758, 1600)
REG_RANK       = (578, 38, 826, 130)
REG_BTN_RANK   = (6, 678, 280, 811)
REG_BTN_SERVER = (478, 1431, 696, 1538)

# VÙNG QUÉT DANH SÁCH CHÚC PHÚC (giống cách REG_SERVER_LIST ở login)
REG_BLESS_LIST = (321, 186, 555, 1240)

# ---------------- Tham số OCR-list/timeout/ngưỡng ----------------
THR_MENU = 0.88
THR_GUILD = 0.88
THR_RANK = 0.88
THR_BTN  = 0.85
THR_BLESS = 0.86  # tìm chuc-phuc.png

WAIT_PAIR_ICONS_SEC = 15
SCROLL_LIMIT = 8
SWIPE_DUR_MS = 1500  # vuốt chậm & ổn định

# Tap thứ ba giữ nguyên
TAP_THIRD = (366, 83)

# ---------------- Logging helper ----------------
def L(wk, msg: str):
    _log(wk, f"[BLESS] {msg}")

# ---------------- Template verification (hỗ trợ debug đường dẫn) ----------------
def _verify_templates(wk) -> bool:
    pairs = [
        ("IMG_MENU", IMG_MENU),
        ("IMG_GUILD_OUT", IMG_GUILD_OUT),
        ("IMG_RANK", IMG_RANK),
        ("IMG_BTN_RANK", IMG_BTN_RANK),
        ("IMG_BTN_SERVER", IMG_BTN_SERVER),
        ("IMG_BLESS_BTN", IMG_BLESS_BTN),
    ]
    ok_all = True
    for key, p in pairs:
        if not Path(p).exists():
            L(wk, f"❌ Thiếu file template {key}: {p}")
            ok_all = False
        else:
            L(wk, f"✅ Template {key}: {Path(p).resolve()}")
    return ok_all

# ---------------- Unicode helpers ----------------
def _strip_vn(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s

def _norm0(s: str) -> str:
    # Chuẩn hóa + thay '0' -> 'o' để tránh nhầm lẫn (đồng bộ login/server)
    return _strip_vn(s).replace("0", "o")

# ---------------- Các helper thao tác ----------------
def _key_back(wk):
    # Android BACK keycode = 4 (ESC)
    adb_safe(wk, "shell", "input", "keyevent", "4", timeout=3)

def _both_icons_present(wk) -> bool:
    img = grab_screen_np(wk)
    try:
        ok1, pos1, _ = find_on_frame(img, IMG_MENU, region=REG_MENU, threshold=THR_MENU)
        ok2, pos2, _ = find_on_frame(img, IMG_GUILD_OUT, region=REG_GUILD_OUT, threshold=THR_GUILD)
        L(wk, f"Check icons → menu: {ok1} pos={pos1} | guild: {ok2} pos={pos2}")
        return ok1 and ok2
    finally:
        free_img(img)

# ---------------- MỞ BẢNG XẾP HẠNG — PHƯƠNG ÁN 2 (giữ nguyên) ----------------
def _open_ranking_loop(wk) -> bool:
    """
    Chỉ dùng phương án 2, lặp đến khi thấy bang-xep-hang:
      - Chờ thấy cả nut-menu & lien-minh-outside
      - bấm nut-menu (ưu tiên theo template; nếu không → tọa độ fallback) → đợi 1.5s
      - tìm & bấm nut-xep-hang (REG_BTN_RANK) → đợi 1.5s
      - tìm & bấm lien-server (REG_BTN_SERVER) → đợi 1.5s
      - kiểm tra bang-xep-hang (REG_RANK)
    """
    L(wk, "Open ranking (phương án 2) bắt đầu…")
    loops = 0
    while True:
        loops += 1
        L(wk, f"Loop {loops}: chờ cặp icon…")
        t0 = time.time()
        while not _both_icons_present(wk):
            _key_back(wk)
            if not sleep_coop(wk, 1.0):
                return False
            if time.time() - t0 > WAIT_PAIR_ICONS_SEC:
                L(wk, "Hết thời gian chờ cặp icon — thử lại.")

        # bấm nut-menu
        img = grab_screen_np(wk)
        try:
            okm, posm, _ = find_on_frame(img, IMG_MENU, region=REG_MENU, threshold=THR_BTN)
            L(wk, f"Find MENU → ok={okm} pos={posm}")
        finally:
            free_img(img)
        if okm and posm:
            tap(wk, *posm); L(wk, f"Tap MENU tại {posm}")
        else:
            tap(wk, 30, 630); L(wk, "Tap MENU fallback (30,630)")
        if not sleep_coop(wk, 1.5):  # đợi sau tap
            return False

        # bấm nut-xep-hang
        img = grab_screen_np(wk)
        try:
            ok, pos, _ = find_on_frame(img, IMG_BTN_RANK, region=REG_BTN_RANK, threshold=THR_BTN)
            L(wk, f"Find BTN_RANK → ok={ok} pos={pos}")
        finally:
            free_img(img)
        if ok and pos:
            tap(wk, *pos); L(wk, f"Tap 'xếp hạng' tại {pos}")
            if not sleep_coop(wk, 1.5):  # đợi sau tap
                return False

            # bấm lien-server
            img = grab_screen_np(wk)
            try:
                oks, poss, _ = find_on_frame(img, IMG_BTN_SERVER, region=REG_BTN_SERVER, threshold=THR_BTN)
                L(wk, f"Find BTN_SERVER → ok={oks} pos={poss}")
            finally:
                free_img(img)
            if oks and poss:
                tap(wk, *poss); L(wk, f"Tap 'liên server' tại {poss}")
                if not sleep_coop(wk, 1.5):  # đợi sau tap
                    return False
        else:
            L(wk, "Không thấy nút 'xếp hạng' trong REG_BTN_RANK — lặp lại.")

        # kiểm tra bang-xep-hang
        img = grab_screen_np(wk)
        try:
            okr, posr, _ = find_on_frame(img, IMG_RANK, region=REG_RANK, threshold=THR_RANK)
            L(wk, f"Find RANK → ok={okr} pos={posr}")
        finally:
            free_img(img)
        if okr:
            L(wk, "Đã thấy bang-xep-hang.")
            return True

        # lặp tiếp
        if not sleep_coop(wk, 0.8):
            return False

# ---------------- OCR list + Tap (theo vùng giống login/select_server) ----------------
def _ocr_list_and_bless(wk, targets: List[str]) -> List[str]:
    """
    Quét danh sách trong REG_BLESS_LIST theo slot dọc (overlap), OCR + normalize (0->o),
    so khớp với targets. Khi match:
      - Tap #1: (270, y_center_slot)
      - Đợi 1.0s → tìm IMG_BLESS_BTN → Tap #2 (nếu thấy)
      - Tap #3: TAP_THIRD
    Trả về list tên gốc đã chúc.
    """
    done: List[str] = []
    if not targets:
        return done

    # Danh sách tạm (không mutate đầu vào)
    remain = list(targets)
    remain_norm = [_norm0(x) for x in remain]
    L(wk, f"[OCR-LIST] targets={targets} (norm={remain_norm})")

    x1, y1, x2, y2 = REG_BLESS_LIST
    H = max(1, y2 - y1)
    N_SLOTS = 12
    row_h  = max(32, H // N_SLOTS)
    stride = max(20, int(row_h * 0.75))  # chồng lấn 25% tránh cắt hụt

    img = grab_screen_np(wk)
    try:
        L(wk, f"[OCR-LIST] reg={REG_BLESS_LIST} → row_h≈{row_h}, stride={stride}")

        i = 0
        ry1 = y1
        while ry1 + 10 < y2:
            ry2 = min(y2, ry1 + row_h)
            roi = img[ry1:ry2, x1:x2].copy()
            h, w = roi.shape[:2]

            # --- Preprocess OCR (đồng bộ login/select_server) ---
            scale = 3 if max(h, w) < 60 else 2
            roi2  = cv2.resize(roi, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            gray  = cv2.cvtColor(roi2, cv2.COLOR_BGR2GRAY)
            gray  = cv2.bilateralFilter(gray, d=7, sigmaColor=60, sigmaSpace=60)
            th    = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            mean_val = float(np.mean(th))
            if mean_val < 127.0:
                th = cv2.bitwise_not(th)
            th = cv2.morphologyEx(th, cv2.MORPH_OPEN,
                                  cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
                                  iterations=1)
            th = cv2.copyMakeBorder(th, 6, 6, 6, 6, cv2.BORDER_CONSTANT, value=255)
            prep = cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)

            t7 = (ocr_region(prep, 0, 0, prep.shape[1], prep.shape[0], lang="vie", psm=7) or "").strip()
            t6 = "" if t7 else (ocr_region(prep, 0, 0, prep.shape[1], prep.shape[0], lang="vie", psm=6) or "").strip()
            use_txt  = (t7 or t6).replace("\n", " ")
            use_norm = _norm0(use_txt)

            i += 1
            # So khớp với mọi target
            found_idx = -1
            for k, tn in enumerate(remain_norm):
                if use_norm and (use_norm == tn or use_norm in tn or tn in use_norm):
                    found_idx = k; break

            hit = (found_idx >= 0)
            L(wk, f"[OCR-LIST] SLOT#{i:02d} reg=({x1},{ry1},{x2},{ry2}) ROI={w}x{h} "
                  f"scale={scale} mean={mean_val:.1f} psm7='{t7}' psm6='{t6}' "
                  f"→ use='{use_txt}' norm='{use_norm}' "
                  f"expected∈{remain_norm} match={hit}")

            if hit:
                orig_name = remain[found_idx]
                cy = (ry1 + ry2) // 2
                tap1 = (270, cy)  # theo yêu cầu: x=270, y lấy theo slot (giống tham số y của tap login)
                L(wk, f"[OCR-LIST] ✅ MATCH '{orig_name}' → TAP#1 {tap1}")
                tap(wk, *tap1)
                if not sleep_coop(wk, 1.0):
                    return done

                # Tìm nút Chúc phúc (Tap #2)
                img2 = grab_screen_np(wk)
                try:
                    okb, posb, scb = find_on_frame(img2, IMG_BLESS_BTN, threshold=THR_BLESS)
                    L(wk, f"[OCR-LIST] FIND 'chuc-phuc.png' → ok={okb} pos={posb} sc={scb}")
                finally:
                    free_img(img2)

                if okb and posb:
                    tap(wk, *posb)
                    L(wk, f"[OCR-LIST] TAP#2 tại {posb}")
                    if not sleep_coop(wk, 1.0):
                        return done
                else:
                    L(wk, "[OCR-LIST] ⚠️ Không thấy nút 'Chúc phúc' sau TAP#1.")

                # Tap #3 (giữ nguyên)
                tap(wk, *TAP_THIRD)
                L(wk, f"[OCR-LIST] TAP#3 tại {TAP_THIRD}")
                if not sleep_coop(wk, 0.5):
                    return done

                done.append(orig_name)
                # loại mục đã match để tránh chúc trùng trên cùng trang
                remain.pop(found_idx); remain_norm.pop(found_idx)

                # Nếu đã hết mục tiêu trên trang, có thể kết thúc vòng chạy trang
                if not remain_norm:
                    L(wk, "[OCR-LIST] Hết mục tiêu cần tìm trên trang hiện tại.")
                    break

            # Next slot
            ry1 += stride

    finally:
        free_img(img)

    if done:
        L(wk, f"[OCR-LIST] xong trang — matched: {done}")
    else:
        L(wk, "[OCR-LIST] xong trang — chưa match được ai.")
    return done

# ==================== ENTRYPOINT ====================
def run_bless_flow(wk, targets: List[str], log=None, max_scrolls: int = SCROLL_LIMIT) -> List[str]:
    """
    - Mở “Bảng xếp hạng” bằng phương án 2, lặp tới khi thấy.
    - OCR & chúc phúc các tên trong 'targets' bằng vùng REG_BLESS_LIST theo slot (giống login).
    - Kéo trang tối đa 'max_scrolls' lần (vuốt chậm SWIPE_DUR_MS) đến khi hoàn tất.
    """
    L(wk, f"BẮT ĐẦU flow chúc phúc — targets={targets}")
    if not targets:
        L(wk, "Không có target để chúc phúc → kết thúc sớm.")
        return []
    if not _verify_templates(wk):
        L(wk, "Dừng flow: thiếu template ảnh cần thiết.")
        return []

    # Mở bảng xếp hạng: PHƯƠNG ÁN 2 (như cũ)
    if not _open_ranking_loop(wk):
        L(wk, "Không thể mở bảng xếp hạng — kết thúc.")
        return []

    # Chờ ổn định rồi OCR
    if not sleep_coop(wk, 1.0):
        return []

    remaining = list(targets)
    blessed_ok: List[str] = []

    for scroll_idx in range(0, max_scrolls + 1):
        L(wk, f"----- Trang/Scroll vòng {scroll_idx}/{max_scrolls} — remaining={remaining}")
        done = _ocr_list_and_bless(wk, remaining)

        if done:
            blessed_ok.extend(done)
            # loại khỏi remaining theo chuẩn hoá để an toàn
            rem_norm = [_norm0(x) for x in remaining]
            for d in done:
                nd = _norm0(d)
                for i, rname in enumerate(rem_norm):
                    if rname == nd:
                        remaining.pop(i); rem_norm.pop(i)
                        break

        if not remaining:
            L(wk, f"HOÀN TẤT — đã chúc phúc xong tất cả: {blessed_ok}")
            break

        if scroll_idx >= max_scrolls:
            L(wk, f"ĐÃ ĐỦ {max_scrolls} lần cuộn — dừng lại. Chưa xong: {remaining}")
            break

        # Vuốt chậm & nghỉ 1.5s cho ổn định (giữ thông số cũ)
        L(wk, f"Kéo trang chậm (dur_ms={SWIPE_DUR_MS}) — 446,1256 → 446,190")
        swipe(wk, 446, 1255, 446, 188, dur_ms=SWIPE_DUR_MS)
        if not sleep_coop(wk, 1.5):
            break

    L(wk, f"KẾT THÚC flow chúc phúc — thành công: {blessed_ok} | chưa xong: {remaining}")
    return blessed_ok
