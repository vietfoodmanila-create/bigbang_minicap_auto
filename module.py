# module.py
# Phiên bản hoàn chỉnh, đã bổ sung đầy đủ các hàm tiện ích cần thiết.

import os, sys, re, time, uuid, shutil, subprocess, gc
from pathlib import Path
from typing import Optional, Tuple
import cv2
import numpy as np
import pytesseract

# --- CẤU HÌNH ---
try:
    from config import TESSERACT_EXE, TESSDATA_DIR
except ImportError:
    TESSERACT_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    TESSDATA_DIR = r"C:\Program Files\Tesseract-OCR\tessdata"
DEFAULT_THR = 0.88

# --- CÀI ĐẶT TESSERACT ---
pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE


def _set_tess_prefix():
    prefix = str(Path(TESSDATA_DIR))
    if not prefix.endswith(("\\", "/")): prefix += os.sep
    os.environ["TESSDATA_PREFIX"] = prefix


_set_tess_prefix()


# --- CÁC HÀM TIỆN ÍCH CHUNG ---
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def log_wk(wk, msg: str):
    """Gửi log thông qua worker chính."""
    if wk and hasattr(wk, 'log'):
        wk.log(msg)
    elif hasattr(wk, 'w') and hasattr(wk.w, 'log'):  # Dành cho AutoThread
        wk.w.log(msg)
    else:
        print(f"[{getattr(wk, 'device_id', 'GLOBAL')}] {msg}", flush=True)


# --- LOGIC NHẬN DIỆN HÌNH ẢNH ---
_template_cache: dict[str, np.ndarray] = {}


def load_template(path: str) -> np.ndarray:
    """Load ảnh mẫu từ file và cache lại."""
    path_key = Path(path).as_posix()
    if path_key not in _template_cache:
        mat = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if mat is None:
            raise FileNotFoundError(f"Không đọc được file ảnh template: {path}")
        _template_cache[path_key] = mat
    return _template_cache[path_key]


def find_on_frame(frame_bgr, template_path: str, *, region: tuple = None, threshold: float = 0.85):
    """Tìm kiếm ảnh mẫu trên một khung hình một cách an toàn."""
    if frame_bgr is None:
        return False, None, 0.0

    screen_to_search = frame_bgr.copy()
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


# --- CÁC HÀM WRAPPER ĐỂ flows_* SỬ DỤNG ---
def adb_safe(wk, *args, timeout=6):
    return wk.adb(*args, timeout=timeout)


def tap(wk, x, y):
    wk.adb("shell", "input", "tap", str(x), str(y), timeout=3)


def tap_center(wk, reg):
    x1, y1, x2, y2 = reg
    tap(wk, (x1 + x2) // 2, (y1 + y2) // 2)


def swipe(wk, x1, y1, x2, y2, dur_ms=450):
    wk.adb("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(dur_ms), timeout=3)


def aborted(wk) -> bool:
    """Kiểm tra xem luồng auto đã nhận được yêu cầu dừng chưa."""
    if hasattr(wk, 'w'):  # Dành cho AutoThread
        return wk.w.stop_event.is_set()
    if hasattr(wk, 'stop_event'):  # Dành cho Worker chính
        return wk.stop_event.is_set()
    return False


def sleep_coop(wk, secs: float) -> bool:
    """Hàm sleep an toàn, có thể bị ngắt bởi sự kiện dừng."""
    if hasattr(wk, 'w') and hasattr(wk.w, '_sleep_coop'):  # Dành cho AutoThread
        return wk.w._sleep_coop(secs)
    if hasattr(wk, '_sleep_coop'):  # Dành cho Worker chính
        return wk._sleep_coop(secs)
    time.sleep(secs)  # Fallback
    return True


def grab_screen_np(wk=None) -> Optional[np.ndarray]:
    """Hàm chụp ảnh chính, sẽ được Worker ghi đè để lấy ảnh từ queue."""
    if wk and hasattr(wk, 'grab_screen_np_override'):
        return wk.grab_screen_np_override()
    log_wk(wk, "Lỗi: Hàm grab_screen_np chưa được worker khởi tạo.")
    return None


def type_text(wk, text: str):
    adb_safe(wk, "shell", "input", "text", text.replace(" ", "%s"), timeout=4)


def back(wk, times: int = 1, wait_each: float = 0.2):
    for _ in range(times):
        if aborted(wk): break
        adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)
        time.sleep(wait_each)


# --- CÁC HÀM TIỆN ÍCH BỊ THIẾU ĐÃ ĐƯỢC BỔ SUNG LẠI ---
def state_simple(wk, package_hint: str = "com.phsgdbz.vn") -> str:
    """Xác định trạng thái đơn giản của game (cần đăng nhập, trong game, v.v.)."""
    code, out, _ = adb_safe(wk, "shell", "cmd", "activity", "get-foreground-activity", timeout=5)
    comp = ""
    if code == 0 and out and "ComponentInfo{" in out:
        try:
            comp = out.split("ComponentInfo{", 1)[1].split("}", 1)[0]
        except Exception:
            comp = ""
    if not comp:
        c2, out2, _ = adb_safe(wk, "shell", "dumpsys", "window", "windows", timeout=6)
        if c2 == 0 and out2:
            for line in out2.splitlines():
                if package_hint in line and "/" in line:
                    m = re.search(r"([a-zA-Z0-9_.]+/[a-zA-Z0-9_.$]+)", line)
                    if m:
                        comp = m.group(1)
                        break

    if "com.bbt.android.sdk.login.HWLoginActivity" in comp:
        return "need_login"
    if "org.cocos2dx.javascript.GameTwActivity" in comp:
        return "gametw"
    return "unknown"


def pt_in_region(pt: Optional[Tuple[int, int]], reg: Tuple[int, int, int, int]) -> bool:
    """Kiểm tra một điểm có nằm trong một vùng chữ nhật hay không."""
    if not pt:
        return False
    x, y = pt
    x1, y1, x2, y2 = reg
    return (x1 <= x <= x2) and (y1 <= y <= y2)


def esc_soft_clear(wk, times: int = 3, wait_each: float = 1.0):
    """Nhấn BACK nhẹ 1 lần + ESC `times` lần để dọn dẹp giao diện."""
    adb_safe(wk, "shell", "input", "keyevent", "4", timeout=3)  # BACK
    for _ in range(times):
        if aborted(wk): break
        adb_safe(wk, "shell", "input", "keyevent", "111", timeout=3)  # ESC
        time.sleep(wait_each)


def is_green_pixel(wk, x: int, y: int, h_range=(35, 85), s_min=80, v_min=80, sample: int = 3) -> bool:
    """Kiểm tra pixel gần (x,y) có 'xanh lá' theo HSV không."""
    img = grab_screen_np(wk)
    try:
        if img is None: return False
        h, w = img.shape[:2]
        if not (0 <= x < w and 0 <= y < h): return False
        r = max(1, sample // 2)
        x1, y1 = max(0, x - r), max(0, y - r)
        x2, y2 = min(w, x + r + 1), min(h, y + r + 1)
        roi = img[y1:y2, x1:x2].copy()
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        H = float(np.mean(hsv[..., 0]))
        S = float(np.mean(hsv[..., 1]))
        V = float(np.mean(hsv[..., 2]))
        return (h_range[0] <= H <= h_range[1]) and (S >= s_min) and (V >= v_min)
    finally:
        if img is not None: del img


def wait_state(wk, target: str = "need_login", timeout: float = 6.0, interval: float = 0.25) -> bool:
    """Đợi tới khi `state_simple(wk)` trả về trạng thái mong muốn."""
    end = time.time() + timeout
    while time.time() < end:
        if aborted(wk): return False
        st = state_simple(wk)
        if st == target:
            return True
        time.sleep(interval)
    return False


# Các hàm không còn cần thiết nhưng giữ lại để tương thích nếu có file nào đó vẫn gọi
def free_img(*imgs): pass


def mem_relief(): gc.collect()