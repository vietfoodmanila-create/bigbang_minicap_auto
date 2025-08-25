# -*- coding: utf-8 -*-
"""
flows_chuc_phuc.py
Flow chúc phúc: chỉ dùng phương án 2 (fallback) lặp đến khi thấy bảng xếp hạng.
Vuốt chậm (dur_ms tăng), delay 1.5s sau các thao tác tap/gesture, OCR bỏ dấu + non-alnum.
"""

from __future__ import annotations
import time
from typing import List, Tuple, Optional
from pathlib import Path
import unicodedata
import re

from module import (
    grab_screen_np, find_on_frame, tap, tap_center, swipe,
    sleep_coop, free_img, adb_safe, ocr_region,
    log_wk as _log,resource_path,
)

# ---------------- Template paths (đặt trong images/chuc_phuc) ----------------
IMG_MENU = resource_path("images/chuc_phuc/nut-menu.png")
IMG_GUILD_OUT = resource_path("images/chuc_phuc/lien-minh-outside.png")
IMG_RANK = resource_path("images/chuc_phuc/bang-xep-hang.png")
IMG_BTN_RANK = resource_path("images/chuc_phuc/nut-xep-hang.png")
IMG_BTN_SERVER = resource_path("images/chuc_phuc/lien-server.png")

# ---------------- Vùng tìm kiếm (x1,y1,x2,y2) ----------------
REG_MENU = (0, 580, 81, 688)
REG_GUILD_OUT = (581, 1485, 758, 1600)
REG_RANK = (578, 38, 826, 130)
REG_BTN_RANK = (6, 678, 280, 811)
REG_BTN_SERVER = (478, 1431, 696, 1538)

# ---------------- OCR slots và toạ độ tap ----------------
# (region, (tap1_x,tap1_y), (tap2_x,tap2_y))
# 7 vùng OCR đã cập nhật
OCR_SLOTS: List[Tuple[Tuple[int,int,int,int], Tuple[int,int], Tuple[int,int]]] = [
    ((330,203,540,260),   (265,268),  (758,811)),
    ((330,343,540,421),   (268,430),  (756,970)),
    ((330,493,540,573),   (273,586),  (755,1116)),
    ((330,646,540,721),   (265,745),  (758,635)),
    ((330,795,540,880),   (263,876),  (760,783)),
    ((330,945,540,1013),  (263,1031), (756,936)),
    ((330,1098,540,1170), (270,1186), (760,1090)),
]

# ---------------- Ngưỡng/timeout ----------------
THR_MENU = 0.88
THR_GUILD = 0.88
THR_RANK = 0.88
THR_BTN  = 0.85
WAIT_PAIR_ICONS_SEC = 15
SCROLL_LIMIT = 8
SWIPE_DUR_MS = 1500  # vuốt chậm & ổn định; chỉnh theo ý nếu cần
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
    ]
    ok_all = True
    for key, p in pairs:
        if not Path(p).exists():
            L(wk, f"❌ Thiếu file template {key}: {p}")
            ok_all = False
        else:
            L(wk, f"✅ Template {key}: {Path(p).resolve()}")
    return ok_all

# ---------------- Unicode helpers (bỏ dấu + bỏ mọi ký tự không phải chữ/số) ----------------
def _strip_vn(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s

def _normalize_name(s: str) -> str:
    return _strip_vn(s)

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

# ---------------- MỞ BẢNG XẾP HẠNG — PHƯƠNG ÁN 2 (duy nhất) ----------------
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

# ---------------- So khớp OCR ----------------
def _match_target(txt: str, targets_norm: List[str]) -> Optional[str]:
    t = _normalize_name(txt)
    if not t:
        return None
    for name in targets_norm:
        if t == name or t in name or name in t:
            return name
    return None

def _ocr_page_and_bless(wk, targets: List[str]) -> List[str]:
    """
    OCR 7 vùng, nếu tên có trong targets thì nhấn 3 điểm và trả về DANH SÁCH TÊN GỐC đã chúc.
    - So khớp theo dạng đã chuẩn hoá (bỏ dấu + bỏ ký tự không chữ/số) ở CẢ 2 phía.
    - Tap 3 điểm: tap1 -> tap2 -> (366, 83) với delay 1.0s, 1.0s, 0.5s.
    """
    done: List[str] = []
    if not targets:
        return done

    # BẢN SAO CỤC BỘ để không mutate danh sách caller
    loc_targets = list(targets)
    loc_norm = [_normalize_name(x) for x in loc_targets]
    L(wk, f"OCR page — targets còn lại: {targets} (norm={loc_norm})")

    img_full = grab_screen_np(wk)
    try:
        for idx, (reg, tap1, tap2) in enumerate(OCR_SLOTS, start=1):
            x1, y1, x2, y2 = reg
            try:
                txt = ocr_region(img_full, x1, y1, x2, y2, lang="vie", psm=6)
            except Exception as e:
                L(wk, f"OCR slot#{idx} reg={reg} → LỖI OCR: {e}")
                txt = ""
            txt_show = (txt or "").replace("\n", " ").strip()
            tnorm = _normalize_name(txt)
            L(wk, f"OCR slot#{idx} reg={reg} → '{txt_show}' | norm='{tnorm}'")

            # TÌM CHỈ SỐ trong loc_norm để lấy TÊN GỐC
            found_idx = -1
            for i, name_norm in enumerate(loc_norm):
                if tnorm and (tnorm == name_norm or tnorm in name_norm or name_norm in tnorm):
                    found_idx = i
                    break

            if found_idx < 0:
                L(wk, f"Slot#{idx} → không khớp target nào.")
                continue

            orig_name = loc_targets[found_idx]   # <-- TÊN GỐC trả về
            L(wk, f"Slot#{idx} → KHỚP: '{orig_name}' | Tap {tap1} → {tap2} → (366, 83)")

            # TAP 3 ĐIỂM với delay yêu cầu
            tap(wk, *tap1);           sleep_coop(wk, 1.0)
            tap(wk, *tap2);           sleep_coop(wk, 1.0)
            tap(wk, 366, 83);         sleep_coop(wk, 0.5)

            done.append(orig_name)

            # Loại mục đã khớp khỏi BẢN SAO CỤC BỘ để tránh nhấn trùng trong cùng trang
            loc_targets.pop(found_idx)
            loc_norm.pop(found_idx)

            if not loc_norm:
                L(wk, "Đã hoàn tất toàn bộ targets trên trang hiện tại.")
                break
    finally:
        free_img(img_full)

    L(wk, f"OCR page xong — matched (orig): {done}")
    return done


# ==================== ENTRYPOINT ====================
def run_bless_flow(wk, targets: List[str], log=None, max_scrolls: int = SCROLL_LIMIT) -> List[str]:
    """
    - Mở “Bảng xếp hạng” bằng phương án 2, lặp tới khi thấy.
    - OCR & chúc phúc các tên trong 'targets'.
    - Kéo trang tối đa 'max_scrolls' lần (vuốt chậm SWIPE_DUR_MS) đến khi hoàn tất.
    """
    L(wk, f"BẮT ĐẦU flow chúc phúc — targets={targets}")
    if not targets:
        L(wk, "Không có target để chúc phúc → kết thúc sớm.")
        return []
    if not _verify_templates(wk):
        L(wk, "Dừng flow: thiếu template ảnh cần thiết.")
        return []

    # Mở bảng xếp hạng: CHỈ phương án 2
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
        done = _ocr_page_and_bless(wk, remaining)

        if done:
            blessed_ok.extend(done)
            rem_norm = [_normalize_name(x) for x in remaining]
            for d in done:
                nd = _normalize_name(d)
                for i, rname in enumerate(rem_norm):
                    if rname == nd:
                        remaining.pop(i)
                        rem_norm.pop(i)
                        break

        if not remaining:
            L(wk, f"HOÀN TẤT — đã chúc phúc xong tất cả: {blessed_ok}")
            break

        if scroll_idx >= max_scrolls:
            L(wk, f"ĐÃ ĐỦ {max_scrolls} lần cuộn — dừng lại. Chưa xong: {remaining}")
            break

        # Vuốt chậm & nghỉ 1.5s cho ổn định
        L(wk, f"Kéo trang chậm (dur_ms={SWIPE_DUR_MS}) — 446,1256 → 446,190")
        swipe(wk, 446, 1256, 446, 188, dur_ms=SWIPE_DUR_MS)
        if not sleep_coop(wk, 1.5):
            break

    L(wk, f"KẾT THÚC flow chúc phúc — thành công: {blessed_ok} | chưa xong: {remaining}")
    return blessed_ok
