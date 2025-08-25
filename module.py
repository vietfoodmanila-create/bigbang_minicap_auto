# module.py
# PHIÊN BẢN KHÔI PHỤC ĐẦY ĐỦ - Đã đối chiếu và bổ sung toàn bộ logic từ module.py gốc.

import os, sys, re, time, uuid, shutil, subprocess, gc
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any, Union
from datetime import datetime, timedelta
import cv2
import numpy as np
import pytesseract

# --- CẤU HÌNH ---
try:
    from config import TESSERACT_EXE, TESSDATA_DIR
except ImportError:
    TESSERACT_EXE = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
    TESSDATA_DIR = r"C:\\Program Files\\Tesseract-OCR\\tessdata"
DEFAULT_THR = 0.88

# --- CÀI ĐẶT TESSERACT ---
pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE


def _set_tess_prefix():
    prefix = str(Path(TESSDATA_DIR))
    if not prefix.endswith(("\\", "/")): prefix += os.sep
    os.environ["TESSDATA_PREFIX"] = prefix


_set_tess_prefix()


# --- CÁC LỚP VÀ HẰNG SỐ CỐT LÕI ---
class NoStore:
    """Lớp lưu trữ trạng thái tạm thời, không lưu vào file."""
    pass


_template_cache: Dict[str, np.ndarray] = {}


# --- CÁC HÀM TIỆN ÍCH CHUNG ---
def resource_path(relative_path: str) -> str:
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def log_wk(wk, msg: str):
    """Gửi log thông qua worker chính một cách an toàn."""
    try:
        if wk and hasattr(wk, 'log'):
            wk.log(msg)
        elif hasattr(wk, 'w') and hasattr(wk.w, 'log'):
            wk.w.log(msg)
        else:
            print(f"[{getattr(wk, 'device_id', 'GLOBAL')}] {msg}", flush=True)
    except Exception:
        print(f"[FALLBACK LOG] {msg}", flush=True)


def mem_relief():
    gc.collect()


def free_img(*imgs):
    pass


# --- LOGIC NHẬN DIỆN HÌNH ẢNH ---
def load_template(path: str) -> Optional[np.ndarray]:
    path_key = Path(path).as_posix()
    if path_key not in _template_cache:
        try:
            mat = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if mat is None:
                raise FileNotFoundError(f"Không đọc được file ảnh template: {path}")
            _template_cache[path_key] = mat
        except Exception as e:
            print(f"Lỗi khi load template '{path}': {e}")
            return None
    return _template_cache[path_key]


def find_on_frame(frame_bgr: Optional[np.ndarray], template_path: str, *,
                  region: Optional[Tuple[int, int, int, int]] = None, threshold: float = 0.85) -> Tuple[
    bool, Optional[Tuple[int, int]], float]:
    if frame_bgr is None:
        return False, None, 0.0
    try:
        screen_to_search = frame_bgr
        template = load_template(template_path)
        if template is None: return False, None, 0.0

        offset_x, offset_y = 0, 0
        if region:
            x1, y1, x2, y2 = region
            screen_to_search = screen_to_search[y1:y2, x1:x2]
            offset_x, offset_y = x1, y1

        if screen_to_search.shape[0] < template.shape[0] or screen_to_search.shape[1] < template.shape[1]:
            return False, None, 0.0

        res = cv2.matchTemplate(screen_to_search, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        score = float(max_val)

        if score >= threshold:
            template_h, template_w = template.shape[:2]
            center_x = offset_x + max_loc[0] + template_w // 2
            center_y = offset_y + max_loc[1] + template_h // 2
            return True, (center_x, center_y), score

        return False, None, score
    except Exception:
        return False, None, 0.0


# --- CÁC HÀM WRAPPER TƯƠNG TÁC VỚI GIẢ LẬP ---
def adb_safe(wk, *args, timeout=6):
    return wk.adb(*args, timeout=timeout)


def tap(wk, x: int, y: int):
    adb_safe(wk, "shell", "input", "tap", str(x), str(y), timeout=3)


def tap_center(wk, reg: Tuple[int, int, int, int]):
    x1, y1, x2, y2 = reg
    tap(wk, (x1 + x2) // 2, (y1 + y2) // 2)


def swipe(wk, x1: int, y1: int, x2: int, y2: int, dur_ms: int = 450):
    adb_safe(wk, "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(dur_ms), timeout=3)


def type_text(wk, text: str):
    adb_safe(wk, "shell", "input", "text", text.replace(" ", "%s"), timeout=4)


def back(wk, times: int = 1, wait_each: float = 0.2):
    for _ in range(times):
        if aborted(wk): break
        adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)
        time.sleep(wait_each)


def esc_soft_clear(wk, times: int = 3, wait_each: float = 1.0):
    adb_safe(wk, "shell", "input", "keyevent", "4", timeout=3)
    for _ in range(times):
        if aborted(wk): break
        adb_safe(wk, "shell", "input", "keyevent", "111", timeout=3)
        time.sleep(wait_each)


# --- CÁC HÀM ĐIỀU KHIỂN LUỒNG VÀ TRẠNG THÁI ---
def aborted(wk) -> bool:
    if hasattr(wk, 'w'):
        return wk.w.stop_event.is_set()
    if hasattr(wk, 'stop_event'):
        return wk.stop_event.is_set()
    if hasattr(wk, '_abort'):
        return wk._abort
    return False


def sleep_coop(wk, secs: float) -> bool:
    if hasattr(wk, 'w') and hasattr(wk.w, '_sleep_coop'):
        return wk.w._sleep_coop(secs)
    if hasattr(wk, '_sleep_coop'):
        return wk._sleep_coop(secs)

    end_time = time.time() + secs
    while time.time() < end_time:
        if aborted(wk): return False
        time.sleep(min(1.0, end_time - time.time()))
    return True


def grab_screen_np(wk=None) -> Optional[np.ndarray]:
    if hasattr(wk, 'w') and hasattr(wk.w, 'get_latest_frame'):
        return wk.w.get_latest_frame()
    if hasattr(wk, 'get_latest_frame'):
        return wk.get_latest_frame()

    log_wk(wk, "Lỗi: Hàm grab_screen_np chưa được worker khởi tạo đúng cách.")
    return None


def state_simple(wk, package_hint: str = "com.phsgdbz.vn") -> str:
    comp = ""
    code, out, _ = adb_safe(wk, "shell", "dumpsys", "activity", "top", "-c", timeout=5)
    if code == 0 and out:
        if m := re.search(r"ACTIVITY ([a-zA-Z0-9_.]+/[a-zA-Z0-9_.$]+)", out):
            comp = m.group(1)

    if not comp:
        c2, out2, _ = adb_safe(wk, "shell", "dumpsys", "window", "windows", timeout=6)
        if c2 == 0 and out2:
            for line in out2.splitlines():
                if "mCurrentFocus" in line or "mFocusedApp" in line:
                    if m := re.search(r"([a-zA-Z0-9_.]+/[a-zA-Z0-9_.$]+)", line):
                        comp = m.group(1)
                        break

    if "com.bbt.android.sdk.login.HWLoginActivity" in comp: return "need_login"
    if "org.cocos2dx.javascript.GameTwActivity" in comp: return "gametw"
    return "unknown"


def wait_state(wk, target: str = "need_login", timeout: float = 6.0, interval: float = 0.25) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if aborted(wk): return False
        if state_simple(wk) == target: return True
        time.sleep(interval)
    return state_simple(wk) == target


# --- CÁC HÀM TIỆN ÍCH LOGIC GAME ---
def pt_in_region(pt: Optional[Tuple[int, int]], reg: Tuple[int, int, int, int]) -> bool:
    if not pt: return False
    x, y = pt
    x1, y1, x2, y2 = reg
    return (x1 <= x <= x2) and (y1 <= y <= y2)


def is_green_pixel(wk, x: int, y: int, h_range=(35, 85), s_min=80, v_min=80, sample: int = 3) -> bool:
    img = grab_screen_np(wk)
    try:
        if img is None: return False
        h, w = img.shape[:2]
        if not (0 <= x < w and 0 <= y < h): return False
        r = max(1, sample // 2)
        x1, y1 = max(0, x - r), max(0, y - r)
        x2, y2 = min(w, x + r + 1), min(h, y + r + 1)
        roi = img[y1:y2, x1:x2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        H = float(np.mean(hsv[..., 0]))
        S = float(np.mean(hsv[..., 1]))
        V = float(np.mean(hsv[..., 2]))
        return (h_range[0] <= H <= h_range[1]) and (S >= s_min) and (V >= v_min)
    finally:
        if img is not None: del img


def ensure_inside_generic(wk, entry_points: List[str], targets: List[str], max_tries: int = 8) -> bool:
    for i in range(max_tries):
        if aborted(wk): return False
        img = grab_screen_np(wk)
        if img is None:
            log_wk(wk, "ensure_inside_generic: Không lấy được ảnh màn hình.")
            sleep_coop(wk, 1)
            continue

        for target_path in targets:
            found, _, _ = find_on_frame(img, target_path, threshold=0.9)
            if found:
                log_wk(wk, f"ensure_inside_generic: Đã ở đúng màn hình (target: {Path(target_path).name}).")
                return True

        was_clicked = False
        for entry_path in entry_points:
            found, pos, _ = find_on_frame(img, entry_path)
            if found:
                log_wk(wk, f"ensure_inside_generic: Tìm thấy điểm vào ({Path(entry_path).name}), đang nhấn...")
                tap(wk, pos[0], pos[1])
                was_clicked = True
                break

        if was_clicked:
            sleep_coop(wk, 1.5)
        else:
            log_wk(wk, "ensure_inside_generic: Không tìm thấy target/entry, đang dọn dẹp UI.")
            esc_soft_clear(wk, 2)
            sleep_coop(wk, 1)

    log_wk(wk, "ensure_inside_generic: Thất bại sau nhiều lần thử.")
    return False


def open_by_swiping(wk, target_path: str, swipe_reg: Tuple[int, int, int, int], max_swipes: int = 4) -> bool:
    x1, y1, x2, y2 = swipe_reg
    for i in range(max_swipes):
        if aborted(wk): return False
        img = grab_screen_np(wk)
        if img is None:
            sleep_coop(wk, 1)
            continue

        found, pos, _ = find_on_frame(img, target_path)
        if found:
            log_wk(wk, f"open_by_swiping: Tìm thấy '{Path(target_path).name}'.")
            return True

        if i < max_swipes:
            log_wk(wk, f"open_by_swiping: Vuốt lần {i + 1} để tìm '{Path(target_path).name}'.")
            swipe(wk, x1, y1, x2, y2)
            sleep_coop(wk, 1.0)

    log_wk(wk, f"open_by_swiping: Không tìm thấy '{Path(target_path).name}' sau {max_swipes} lần vuốt.")
    return False


# --- CÁC HÀM OCR ---
def _preprocess_for_ocr(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return thresh


def ocr_region(wk, region: Tuple[int, int, int, int], ocr_config: str = "--psm 7") -> str:
    img = grab_screen_np(wk)
    if img is None:
        return ""
    try:
        x1, y1, x2, y2 = region
        roi = img[y1:y2, x1:x2]
        processed_roi = _preprocess_for_ocr(roi)
        text = pytesseract.image_to_string(processed_roi, lang='eng', config=ocr_config)
        return text.strip()
    except Exception as e:
        log_wk(wk, f"Lỗi OCR: {e}")
        return ""
    finally:
        if img is not None: del img


def find_text_on_screen(wk, text_to_find: str, lang='eng', ocr_config: str = "--psm 6") -> Optional[
    Tuple[int, int, int, int]]:
    img = grab_screen_np(wk)
    if img is None: return None
    try:
        d = pytesseract.image_to_data(img, lang=lang, config=ocr_config, output_type=pytesseract.Output.DICT)
        n_boxes = len(d['level'])
        for i in range(n_boxes):
            if text_to_find.lower() in d['text'][i].lower():
                (x, y, w, h) = (d['left'][i], d['top'][i], d['width'][i], d['height'][i])
                return (x, y, x + w, y + h)
        return None
    except Exception as e:
        log_wk(wk, f"Lỗi tìm kiếm text: {e}")
        return None
    finally:
        if img is not None: del img


# --- CÁC HÀM LOGIC CỤ THỂ KHÁC ---
def wait_for_any(wk, templates: List[str], timeout: float = 10.0, region: Optional[Tuple[int, int, int, int]] = None) -> \
Optional[str]:
    end_time = time.time() + timeout
    while time.time() < end_time:
        if aborted(wk): return None
        img = grab_screen_np(wk)
        if img is None:
            sleep_coop(wk, 0.5)
            continue

        for template_path in templates:
            found, _, _ = find_on_frame(img, template_path, region=region)
            if found:
                return template_path

        sleep_coop(wk, 0.2)
    return None


def close_all_popups(wk, close_buttons: List[str], max_closes: int = 5):
    for _ in range(max_closes):
        if aborted(wk): return

        img = grab_screen_np(wk)
        if img is None:
            sleep_coop(wk, 1)
            continue

        closed_one = False
        for btn_path in close_buttons:
            found, pos, _ = find_on_frame(img, btn_path, threshold=0.9)
            if found:
                log_wk(wk, f"Tìm thấy và đóng popup: {Path(btn_path).name}")
                tap(wk, pos[0], pos[1])
                closed_one = True
                sleep_coop(wk, 1.0)
                break

        if not closed_one:
            log_wk(wk, "Không tìm thấy thêm popup nào để đóng.")
            return


# --- CÁC HÀM LẬP KẾ HOẠCH (ĐỂ TƯƠNG THÍCH) ---
def _scan_eligible_accounts(accounts: list, features: dict) -> list:
    """Quét và trả về danh sách các tài khoản đủ điều kiện chạy xây dựng/viễn chinh."""
    eligible = []
    now = datetime.now()
    check_build = features.get("build", False)
    check_expe = features.get("expe", False)

    for acc in accounts:
        try:
            last_build_str = acc.get("last_build")
            last_expe_str = acc.get("last_expe")
            is_eligible = False

            if check_build:
                if not last_build_str or (now - datetime.fromisoformat(last_build_str)) > timedelta(hours=8.1):
                    is_eligible = True

            if not is_eligible and check_expe:
                if not last_expe_str or (now - datetime.fromisoformat(last_expe_str)) > timedelta(hours=8.1):
                    is_eligible = True

            if is_eligible:
                eligible.append(acc)
        except Exception:
            eligible.append(acc)
    return eligible


def _plan_online_blessings(accounts: list, bless_config: dict, bless_targets: list, exclude_emails: list) -> dict:
    """Lập kế hoạch chúc phúc, trả về dict {email: [target_emails]}."""
    plan = {}
    if not bless_config.get("enabled") or not bless_targets:
        return {}

    online_accounts = [acc for acc in accounts if acc.get("game_email") not in exclude_emails]
    if not online_accounts:
        return {}

    num_targets_per_acc = bless_config.get("targets_per_blessing", 3)

    for i, acc in enumerate(online_accounts):
        email = acc.get("game_email")
        start_index = (i * num_targets_per_acc) % len(bless_targets)
        targets_for_this_acc = [bless_targets[j % len(bless_targets)] for j in
                                range(start_index, start_index + num_targets_per_acc)]
        plan[email] = targets_for_this_acc

    return plan