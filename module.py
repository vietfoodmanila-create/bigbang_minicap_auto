# module.py
# ==========================================================
#  Auto helper (ADB + OpenCV + Tesseract) — no mouse needed
#  (ĐÃ MỞ RỘNG: adapter cho flows_* sử dụng wk.adb / wk.adb_bin)
# ==========================================================
import os,sys
import re
import time
import uuid
import shutil
import subprocess
import gc
from pathlib import Path
from typing import Optional, Tuple, Callable
from image_data import IMAGE_DATA # Import dictionary dữ liệu ảnh
import base64
import cv2
import numpy as np
import pytesseract


# ================== CẤU HÌNH ==================
ADB = r"D:\Program Files\Nox\bin\nox_adb.exe"
DEVICE = "127.0.0.1:62025"
SCREEN_W, SCREEN_H = 900, 1600

TESSERACT_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSDATA_DIR  = r"C:\Program Files\Tesseract-OCR\tessdata"

IMAGES_DIR = "images"
DEFAULT_THR = 0.88

pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE

def _set_tess_prefix():
    # Trỏ TRỰC TIẾP vào thư mục tessdata và đảm bảo có dấu / hoặc \ ở cuối
    prefix = str(Path(TESSDATA_DIR))
    if not prefix.endswith(("\\", "/")):
        prefix += os.sep
    os.environ["TESSDATA_PREFIX"] = prefix

_set_tess_prefix()



# ================== TIỆN ÍCH CHUNG ==================
def resource_path(relative_path):
    """ Lấy đường dẫn tuyệt đối đến tài nguyên, hoạt động cho cả chế độ dev và PyInstaller """
    try:
        # PyInstaller tạo một thư mục tạm và lưu đường dẫn trong _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)
def _run(cmd, text=True, timeout: Optional[int] = None):
    return subprocess.run(cmd, capture_output=True, text=text, timeout=timeout)

def log(msg: str):
    print(msg, flush=True)


# ================== ADB (toàn cục) ==================
def adb_ok() -> bool:
    return Path(ADB).exists() or shutil.which(Path(ADB).name) is not None

def adb(*args, text=True):
    return _run([ADB, "-s", DEVICE] + list(args), text=text)

def ensure_connected() -> None:
    if not adb_ok():
        raise FileNotFoundError(f"Không thấy ADB ở: {ADB}")

    out = _run([ADB, "devices"]).stdout
    if DEVICE not in out:
        log(f"🔌 Đang kết nối {DEVICE} ...")
        _run([ADB, "connect", DEVICE])
        out = _run([ADB, "devices"]).stdout

    if DEVICE not in out or "device" not in out.split(DEVICE)[-1]:
        raise RuntimeError(f"ADB chưa thấy {DEVICE}. Hãy mở Nox và đúng cổng 62xxx")
    log(f"✅ ADB đã kết nối {DEVICE}")

def wm_size_str() -> str:
    return adb("shell", "wm", "size").stdout.strip()

def tap_global(x: int, y: int, delay_ms: int = 0):
    adb("shell", "input", "tap", str(x), str(y))
    if delay_ms:
        time.sleep(delay_ms / 1000)

def swipe_global(x1, y1, x2, y2, dur_ms=200):
    adb("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(dur_ms))

def input_text(text: str):
    adb("shell", "input", "text", text.replace(" ", "%s"))


# ================== MÀN HÌNH (toàn cục) ==================
def screencap_bytes() -> bytes:
    p = _run([ADB, "-s", DEVICE, "exec-out", "screencap", "-p"], text=False)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError("Không chụp được màn hình qua ADB.")
    return p.stdout

def screencap_cv() -> np.ndarray:
    data = screencap_bytes()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("Giải mã ảnh thất bại.")
    return img

def save_png(img, path="screen.png"):
    cv2.imwrite(path, img)

def crop(img, x1, y1, x2, y2):
    return img[y1:y2, x1:x2]

def crop_wh(img, x, y, w, h):
    return img[y:y+h, x:x+w]


# ================== TEMPLATE MATCH (CÓ CACHE) ==================
_template_cache: dict[str, np.ndarray] = {}


def _load_image_from_b64(path_key: str) -> np.ndarray | None:
    """
    Giải mã một chuỗi Base64 từ dictionary IMAGE_DATA và chuyển thành ảnh OpenCV.
    """
    # Lấy chuỗi base64 từ dictionary bằng key (chính là đường dẫn)
    b64_string = IMAGE_DATA.get(path_key)
    if not b64_string:
        # Nếu không tìm thấy, có thể ảnh mới chưa được mã hóa
        raise FileNotFoundError(
            f"Không tìm thấy dữ liệu ảnh cho key '{path_key}' trong image_data.py. Bạn đã chạy lại encode_images.py chưa?")

    # Giải mã chuỗi Base64 về dạng nhị phân
    image_bytes = base64.b64decode(b64_string)

    # Chuyển dữ liệu nhị phân thành một mảng numpy
    np_array = np.frombuffer(image_bytes, np.uint8)

    # Đọc mảng numpy thành ảnh màu OpenCV
    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


# Cache vẫn giữ nguyên để tăng tốc
_template_cache: dict[str, np.ndarray] = {}


def load_template(path: str) -> np.ndarray:
    """
    Nâng cấp: Load ảnh từ cache, nếu không có thì giải mã từ image_data.py
    """
    # Chuẩn hóa đường dẫn để khớp với key trong dictionary
    path_key = Path(path).as_posix()

    if path_key not in _template_cache:
        # Thay vì cv2.imread, chúng ta gọi hàm giải mã mới
        mat = _load_image_from_b64(path_key)
        if mat is None:
            raise RuntimeError(f"Giải mã ảnh thất bại từ key: {path_key}")
        _template_cache[path_key] = mat

    return _template_cache[path_key]

def match_template(screen: np.ndarray, template: np.ndarray, thr=DEFAULT_THR
                   ) -> Tuple[bool, Optional[Tuple[int,int]], float]:
    res = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, maxv, _, maxloc = cv2.minMaxLoc(res)
    if maxv >= thr:
        h, w = template.shape[:2]
        cx, cy = maxloc[0] + w//2, maxloc[1] + h//2
        return True, (cx, cy), float(maxv)
    return False, None, float(maxv)

def match(screen: np.ndarray, template_path: str, thr=DEFAULT_THR
          ) -> Tuple[bool, Optional[Tuple[int,int]], float]:
    templ = load_template(template_path)
    return match_template(screen, templ, thr)

def locate_and_tap(screen: np.ndarray, template_path: str, thr=DEFAULT_THR) -> Tuple[bool, Optional[Tuple[int,int]], float]:
    ok, pos, score = match(screen, template_path, thr)
    if ok and pos:
        tap_global(*pos)
    return ok, pos, score

def wait_and_tap(template_path: str, timeout: float = 10, thr=DEFAULT_THR, interval=0.5) -> bool:
    t0 = time.time()
    while time.time() - t0 <= timeout:
        screen = screencap_cv()
        ok, pos, sc = locate_and_tap(screen, template_path, thr)
        if ok:
            log(f"✅ Tìm thấy {template_path} @ {pos} (score={sc:.3f})")
            return True
        time.sleep(interval)
    log(f"❌ Không thấy {template_path} trong {timeout}s")
    return False

def wait_visible(template_path: str, timeout: float = 10, thr=DEFAULT_THR, interval=0.5) -> bool:
    t0 = time.time()
    templ = load_template(template_path)
    while time.time() - t0 <= timeout:
        screen = screencap_cv()
        ok, _, sc = match_template(screen, templ, thr)
        if ok:
            log(f"👀 Thấy {template_path} (score={sc:.3f})")
            return True
        time.sleep(interval)
    log(f"⌛ Hết thời gian chờ {template_path}")
    return False


# ================== OCR ==================
def _list_langs() -> str:
    try:
        _set_tess_prefix()
        out = _run([TESSERACT_EXE, "--list-langs"], text=True, timeout=5).stdout
        return out or ""
    except Exception:
        return ""


def _lang_available(lang_code: str) -> bool:
    return lang_code.lower() in _list_langs().lower()

def ocr_image(img_bgr: np.ndarray, lang="vie", psm=6, whitelist: Optional[str] = None,
              save_debug: bool = False) -> str:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3,3), 0)
    gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1]

    if save_debug:
        name = f"roi_{uuid.uuid4().hex[:6]}.png"
        cv2.imwrite(name, gray)
        log(f"💾 Lưu ROI debug: {name}")

    # dùng TESSDATA_PREFIX, không truyền --tessdata-dir (giống pick_coords/ocr_utils)
    cfg = f'--psm {psm} --oem 3'
    if whitelist:
        cfg += f' -c tessedit_char_whitelist={whitelist}'

    _set_tess_prefix()
    langs_raw = _list_langs().lower()
    # ưu tiên 'vie+eng' nếu cả hai đều có, nếu không có 'vie' thì fallback 'eng'
    if "vie" in langs_raw and "eng" in langs_raw:
        chosen = "vie+eng"
    elif "vie" in langs_raw:
        chosen = "vie"
    elif "eng" in langs_raw:
        chosen = "eng"
    else:
        # không có ngôn ngữ nào khả dụng: trả rỗng để không nổ thread
        chosen = "eng"

    txt = pytesseract.image_to_string(gray, lang=chosen, config=cfg)

    return txt.strip()

def ocr_region(img_bgr: np.ndarray, x1, y1, x2, y2, **kwargs) -> str:
    roi = crop(img_bgr, x1, y1, x2, y2)
    return ocr_image(roi, **kwargs)


# ================== PYAUTOGUI-LIKE ==================
def locate_and_tap_loop(template_path: str, tries: int = 5, thr=DEFAULT_THR, interval=0.8) -> bool:
    for i in range(tries):
        screen = screencap_cv()
        ok, pos, sc = locate_and_tap(screen, template_path, thr)
        if ok:
            log(f"✅ [{i+1}/{tries}] Tap {template_path} @ {pos} (score={sc:.3f})")
            return True
        log(f"🔎 [{i+1}/{tries}] Chưa thấy {template_path} ...")
        time.sleep(interval)
    log(f"❌ Không tap được {template_path} sau {tries} lần")
    return False

def type_text_via_adb(text: str, clear_first: bool=False, clear_taps: int=1, clear_pos: Tuple[int,int]=(0,0)):
    if clear_first:
        for _ in range(clear_taps):
            tap_global(*clear_pos)
            time.sleep(0.15)
    input_text(text)


# ================== CLEAR RAM / CACHE ==================
def clear_caches():
    try:
        _template_cache.clear()
    except Exception:
        pass
    try:
        cv2.destroyAllWindows()
    except Exception:
        pass
    try:
        gc.collect()
    except Exception:
        pass
    log("🧹 Đã clear cache/cv2/gc.")


# =====================================================================
# ===============  PHẦN ADAPTER DÙNG CHO flows_* (wk)  =================
# =====================================================================
def log_wk(wk, msg: str):
    try:
        if hasattr(wk, "statusChanged"):
            wk.statusChanged.emit(getattr(wk, "port", -1), msg)
    except Exception:
        pass
    print(f"[{getattr(wk,'port',-1)}] {msg}", flush=True)

def adb_safe(wk, *args, timeout=6):
    try:
        if wk and hasattr(wk, "adb") and callable(wk.adb):
            return wk.adb(*args, timeout=timeout)
    except Exception as e:
        log_wk(wk, f"ADB lỗi (wk): {e}")
        return -1, "", str(e)
    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        p = subprocess.run([ADB, "-s", DEVICE, *args], capture_output=True, text=True, timeout=timeout, startupinfo=startupinfo)
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as e:
        return -1, "", str(e)

def adb_bin_safe(wk, *args, timeout=6):
    if wk and hasattr(wk, "adb_bin") and callable(wk.adb_bin):
        try:
            return wk.adb_bin(*args, timeout=timeout)
        except Exception as e:
            log_wk(wk, f"ADB(bin) lỗi (wk): {e}")
            return -1, b"", str(e).encode()
    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        p = subprocess.run([ADB, "-s", DEVICE, *args], capture_output=True, timeout=timeout, startupinfo=startupinfo)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return -1, b"", str(e).encode()


def screencap_bytes_wk(wk) -> Optional[bytes]:
    """
    (SỬA LỖI) Sử dụng phương thức chụp ảnh 3 bước an toàn (lưu file -> kéo về -> đọc)
    để tránh lỗi MemoryError do đầy bộ đệm. Đây là phương pháp ổn định nhất.
    """
    port = getattr(wk, 'port', 'global')
    temp_device_path = f"/sdcard/__screencap_{port}.png"
    temp_pc_path = Path(f"__temp_screencap_{port}.png").resolve()

    try:
        # Bước 1: Chụp và lưu ảnh vào file tạm trên thiết bị
        code, out, err = adb_safe(wk, "shell", "screencap", "-p", temp_device_path, timeout=5)
        if code != 0:
            log_wk(wk, f"Lỗi chụp ảnh trên thiết bị: {err}")
            return None

        # Bước 2: Kéo file ảnh từ thiết bị về máy tính
        code, out, err = adb_safe(wk, "pull", temp_device_path, str(temp_pc_path), timeout=6)
        if code != 0:
            log_wk(wk, f"Lỗi kéo file ảnh về máy tính: {err}")
            return None

        # Bước 3: Đọc nội dung file ảnh từ máy tính
        if temp_pc_path.exists() and temp_pc_path.stat().st_size > 0:
            with open(temp_pc_path, "rb") as f:
                content = f.read()
            return content
        else:
            log_wk(wk, "Lỗi: File ảnh kéo về bị rỗng hoặc không tồn tại.")
            return None

    except Exception as e:
        log_wk(wk, f"Lỗi bất ngờ trong quá trình chụp ảnh: {e}")
        return None
    finally:
        # Bước 4: Dọn dẹp file tạm ở cả hai nơi để giữ sạch sẽ
        try:
            if temp_pc_path.exists():
                os.remove(temp_pc_path)
            # Luôn cố gắng xóa file trên thiết bị
            adb_safe(wk, "shell", "rm", temp_device_path, timeout=2)
        except Exception as e:
            log_wk(wk, f"Cảnh báo: Lỗi khi dọn dẹp file tạm: {e}")

def _try_wk_frame_fetcher(wk) -> Optional[np.ndarray]:
    """
    Nếu wk có frame_fetcher() trả về bytes ảnh (JPEG/PNG), dùng nó thay cho screencap.
    An toàn: nếu lỗi hoặc None -> trả None để fallback sang ADB screencap.
    """
    try:
        fn = getattr(wk, "frame_fetcher", None)
        if callable(fn):
            data = fn()
            if not data:
                return None
            return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception as e:
        try:
            log_wk(wk, f"frame_fetcher lỗi: {e}")
        except Exception:
            pass
    return None


def grab_screen_np(wk=None) -> Optional[np.ndarray]:
    """
    Ưu tiên lấy ảnh từ Minicap (wk.frame_fetcher) nếu có.
    Nếu không có/ lỗi, fallback về screencap logic gốc để BẢO TOÀN HÀNH VI CŨ.
    Kèm theo ghi nhận nguồn frame cho mục đích debug/giám sát.
    """
    try:
        if wk is not None:
            img = _try_wk_frame_fetcher(wk)
            if img is not None:
                _frame_src_note(wk, "minicap")
                return img

        raw = screencap_bytes_wk(wk) if wk is not None else screencap_bytes()
        if not raw:
            if wk is not None:
                log_wk(wk, "Không chụp được màn hình.")
            else:
                log("Không chụp được màn hình.")
            return None

        img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if wk is not None:
            _frame_src_note(wk, "screencap")
        return img

    except Exception as e:
        if wk is not None:
            log_wk(wk, f"imdecode lỗi: {e}")
        else:
            log(f"imdecode lỗi: {e}")
        return None

def _frame_src_note(wk, src_name):
    """
    Ghi nhận nguồn frame ('minicap' | 'screencap') vào wk, chỉ log khi chuyển nguồn.
    Bật log bằng biến môi trường: BB_LOG_FRAME_SRC=1
    Đồng thời tăng counter để xem thống kê cuối phiên.
    """
    try:
        prev = getattr(wk, "_frame_source", None)
        if prev != src_name:
            setattr(wk, "_frame_source", src_name)
            if os.environ.get("BB_LOG_FRAME_SRC", "0") in ("1", "true", "True"):
                try:
                    log_wk(wk, f"[FRAME] source={src_name}")
                except Exception:
                    pass
        if src_name == "minicap":
            setattr(wk, "_stats_minicap", getattr(wk, "_stats_minicap", 0) + 1)
        else:
            setattr(wk, "_stats_screencap", getattr(wk, "_stats_screencap", 0) + 1)
    except Exception:
        pass

def get_frame_source(wk):
    """Trả về 'minicap' | 'screencap' | 'unknown' (nếu chưa có)."""
    try:
        return getattr(wk, "_frame_source", "unknown")
    except Exception:
        return "unknown"



def find_on_frame(
        frame_bgr_or_gray,
        template_path: str,
        *,
        region: tuple[int, int, int, int] | None = None,
        threshold: float = 0.85,
        grayscale: bool = True,
        allow_downscale: bool = False,
        max_dim: int = 1280,
):
    """
    Khớp template trên 1 frame (hoặc ROI).
    Trả: (ok: bool, point: (x,y) | None, score: float) - Point là TÂM của vùng khớp.
    """
    import cv2
    import numpy as np

    if frame_bgr_or_gray is None:
        return False, None, 0.0

    tpl = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR)
    if tpl is None or tpl.size == 0:
        return False, None, 0.0

    img = frame_bgr_or_gray

    if grayscale and img.ndim == 3:
        try:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        except Exception:
            return False, None, 0.0

    offx = offy = 0
    if region is not None:
        try:
            x1, y1, x2, y2 = region
        except Exception:
            return False, None, 0.0
        h, w = img.shape[:2]
        x1 = max(0, min(int(x1), w));
        x2 = max(0, min(int(x2), w))
        y1 = max(0, min(int(y1), h));
        y2 = max(0, min(int(y2), h))
        if x2 <= x1 or y2 <= y1:
            return False, None, 0.0
        roi = img[y1:y2, x1:x2]
        if roi is None or roi.size == 0:
            return False, None, 0.0
        img = roi.copy()
        offx, offy = x1, y1

    scale = 1.0
    ih, iw = img.shape[:2]
    if allow_downscale and max(ih, iw) > max_dim:
        scale = max_dim / float(max(ih, iw))
        new_w = max(1, int(iw * scale));
        new_h = max(1, int(ih * scale))
        img_use = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        th, tw = tpl.shape[:2]
        tpl_use = cv2.resize(tpl, (max(1, int(tw * scale)), max(1, int(th * scale))), interpolation=cv2.INTER_AREA)
    else:
        img_use = img
        tpl_use = tpl

    ih, iw = img_use.shape[:2]
    th, tw = tpl_use.shape[:2]
    if th <= 0 or tw <= 0 or ih < th or iw < tw:
        return False, None, 0.0

    try:
        res = cv2.matchTemplate(img_use, tpl_use, cv2.TM_CCOEFF_NORMED)
    except Exception:
        return False, None, 0.0

    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
    score = float(max_val)
    if score < float(threshold):
        return False, None, score

    # (SỬA LỖI) Tính toán tọa độ TÂM thay vì góc trên trái
    # Lấy kích thước của template đã được scale (tpl_use)
    th_scaled, tw_scaled = tpl_use.shape[:2]

    # Tọa độ tâm trên ảnh đã scale
    center_x_scaled = max_loc[0] + tw_scaled // 2
    center_y_scaled = max_loc[1] + th_scaled // 2

    # Chuyển đổi về tọa độ gốc và cộng với offset của vùng region
    center_x_original = int(center_x_scaled / scale) + offx
    center_y_original = int(center_y_scaled / scale) + offy

    return True, (center_x_original, center_y_original), score
# ==== CLOUD API (chuẩn dùng chung cho toàn app) ====
import os, json, platform, hashlib, uuid, requests
from pathlib import Path

API_BASE_URL = "https://api.bbtkauto.io.vn"   # KHÔNG có /api ở cuối

_session = requests.Session()
_session.headers.update({"User-Agent": "BBTKAuto/1.0"})

def _url(path: str) -> str:
    return API_BASE_URL.rstrip("/") + path

def stable_device_uid() -> str:
    try:
        mac = uuid.getnode()
    except Exception:
        mac = 0
    sig = f"{platform.node()}|{platform.machine()}|{platform.processor()}|{mac}"
    return "PC-" + hashlib.sha1(sig.encode("utf-8")).hexdigest()[:12].upper()

def _token_file() -> Path:
    d = (Path(os.environ.get("APPDATA") or Path.home() / ".config") / "BBTKAuto")
    d.mkdir(parents=True, exist_ok=True)
    return d / "token.json"

def save_token(token: str, email: str | None = None, exp: str | None = None):
    _token_file().write_text(json.dumps({"token": token, "email": email, "exp": exp}, ensure_ascii=False), encoding="utf-8")

def load_token() -> dict | None:
    tf = _token_file()
    if not tf.exists(): return None
    try:
        return json.loads(tf.read_text(encoding="utf-8"))
    except Exception:
        return None

def clear_token():
    try:
        _token_file().unlink(missing_ok=True)
    except Exception:
        pass

def _safe_json(r: requests.Response) -> dict:
    if r.status_code >= 400:
        try:
            j = r.json(); msg = j.get("error") or j.get("message") or r.text
        except Exception:
            msg = r.text
        return {"ok": False, "status": r.status_code, "error": msg}
    try:
        j = r.json()
        return j if isinstance(j, dict) else {"ok": False, "error": "bad_json"}
    except Exception:
        return {"ok": False, "error": "bad_json"}

# ---- Register / OTP ----
def api_register_start(email: str, password: str) -> dict:
    try:
        r = _session.post(_url("/api/register/start"), json={"email": email, "password": password}, timeout=15)
    except Exception as e:
        return {"ok": False, "error": f"network_error: {e}"}
    return _safe_json(r)

def api_register_resend(email: str) -> dict:
    try:
        r = _session.post(_url("/api/register/resend"), json={"email": email}, timeout=15)
    except Exception as e:
        return {"ok": False, "error": f"network_error: {e}"}
    return _safe_json(r)

def api_register_verify(email: str, code: str) -> dict:
    try:
        r = _session.post(_url("/api/register/verify"), json={"email": email, "code": code}, timeout=15)
    except Exception as e:
        return {"ok": False, "error": f"network_error: {e}"}
    return _safe_json(r)

# ---- Login / Logout / Status ----
def api_login(email: str, password: str, device_uid: str | None = None, device_name: str | None = None) -> dict:
    payload = {
        "email": email,
        "password": password,
        "device_uid": device_uid or stable_device_uid(),
        "device_name": device_name or platform.node(),
    }
    try:
        r = _session.post(_url("/api/login"), json=payload, timeout=15)
    except Exception as e:
        return {"ok": False, "error": f"network_error: {e}"}
    data = _safe_json(r)
    if data.get("ok") and data.get("token"):
        save_token(data["token"], email=email, exp=data.get("exp"))
    return data

def api_logout() -> dict:
    tok = (load_token() or {}).get("token")
    if not tok:
        clear_token(); return {"ok": True}
    try:
        _session.post(_url("/api/logout"), headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    except Exception:
        pass
    clear_token()
    return {"ok": True}

def api_license_status() -> dict:
    tok = (load_token() or {}).get("token")
    if not tok:
        return {"logged_in": False, "reason": "no_token"}
    try:
        r = _session.get(_url("/api/license/status"), headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    except Exception as e:
        return {"logged_in": False, "reason": "network_error", "error": str(e)}
    if r.status_code in (401, 403):
        return {"logged_in": False, "reason": "unauthorized"}
    if r.status_code == 404:
        return {"logged_in": False, "reason": "endpoint_missing"}
    if r.status_code >= 400:
        try:
            j = r.json(); msg = j.get("error") or j.get("message") or r.text
        except Exception:
            msg = r.text
        return {"logged_in": False, "reason": "server_error", "status": r.status_code, "error": msg}
    try:
        data = r.json()
    except Exception:
        return {"logged_in": False, "reason": "bad_json"}
    data["logged_in"] = True
    return data


def tap(wk, x, y):
    if wk:
        adb_safe(wk, "shell", "input", "tap", str(x), str(y), timeout=3)
    else:
        tap_global(x, y)

def tap_center(wk, reg):
    x1, y1, x2, y2 = reg
    tap(wk, (x1+x2)//2, (y1+y2)//2)

def swipe(wk, x1, y1, x2, y2, dur_ms=450):
    if wk:
        adb_safe(wk, "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(dur_ms), timeout=3)
    else:
        swipe_global(x1, y1, x2, y2, dur_ms)

def aborted(wk) -> bool:
    return bool(getattr(wk, "_abort", False))

def sleep_coop(wk, secs: float) -> bool:
    step = 0.2
    n = int(max(1, secs / step))
    for _ in range(n):
        if aborted(wk):
            return False
        time.sleep(step)
    return True

def free_img(*imgs):
    for im in imgs:
        try:
            del im
        except:
            pass

def mem_relief():
    try:
        gc.collect()
    except:
        pass

def type_text(wk, text: str):
    adb_safe(wk, "shell", "input", "text", text, timeout=4)

def back(wk, times: int = 1, wait_each: float = 0.2):
    for _ in range(times):
        adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)
        time.sleep(wait_each)

def state_simple(wk, package_hint: str = "com.phsgdbz.vn") -> str:
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


# ================== (NEW) HELPERS DÙNG CHUNG BỔ SUNG ==================
def pt_in_region(pt: Optional[Tuple[int,int]], reg: Tuple[int,int,int,int]) -> bool:
    if not pt:
        return False
    x, y = pt
    x1, y1, x2, y2 = reg
    return (x1 <= x <= x2) and (y1 <= y <= y2)

def esc_soft_clear(wk, times: int = 3, wait_each: float = 1.0):
    """BACK nhẹ 1 lần + ESC `times` lần để dọn overlay/ads."""
    adb_safe(wk, "shell", "input", "keyevent", "4", timeout=3)  # BACK
    for _ in range(times):
        adb_safe(wk, "shell", "input", "keyevent", "111", timeout=3)  # ESC
        time.sleep(wait_each)

def is_green_pixel(wk, x: int, y: int, h_range=(35,85), s_min=80, v_min=80, sample: int = 3) -> bool:
    """Kiểm tra pixel gần (x,y) có 'xanh lá' theo HSV không (lấy ROI sample×sample quanh điểm)."""
    img = grab_screen_np(wk)
    try:
        if img is None:
            return False
        h, w = img.shape[:2]
        if not (0 <= x < w and 0 <= y < h):
            return False
        r = max(1, sample//2)
        x1, y1 = max(0, x - r), max(0, y - r)
        x2, y2 = min(w, x + r + 1), min(h, y + r + 1)
        roi = img[y1:y2, x1:x2].copy()
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        H = float(np.mean(hsv[..., 0]))
        S = float(np.mean(hsv[..., 1]))
        V = float(np.mean(hsv[..., 2]))
        return (h_range[0] <= H <= h_range[1]) and (S >= s_min) and (V >= v_min)
    finally:
        free_img(img)

def wait_state(wk, target: str = "need_login", timeout: float = 6.0, interval: float = 0.25) -> bool:
    """Đợi tới khi `state_simple(wk)` == target."""
    end = time.time() + timeout
    while time.time() < end:
        st = state_simple(wk)
        if st == target:
            return True
        time.sleep(interval)
    return False

# ---------- BỔ SUNG CHO CÁC FLOW ----------
def wait_visible_region(wk, tpl_path: str, region: Optional[Tuple[int,int,int,int]] = None,
                        timeout: float = 10.0, thr: float = DEFAULT_THR, interval: float = 0.3) -> bool:
    """
    Poll theo region (nếu có). True nếu thấy template trong thời gian timeout.
    """
    end = time.time() + timeout
    while time.time() < end:
        img = grab_screen_np(wk)
        ok, _, _ = find_on_frame(img, tpl_path, region=region, threshold=thr)
        free_img(img)
        if ok:
            return True
        if not sleep_coop(wk, interval):
            return False
    return False

def ensure_inside_generic(wk,
                          img_outside: str, reg_outside: Tuple[int,int,int,int],
                          img_inside: str,  reg_inside: Tuple[int,int,int,int],
                          esc_delay: float = 1.0, click_delay: float = 0.4) -> bool:
    """
    Back dọn UI cho tới khi thấy OUTSIDE → tap outside → chờ INSIDE (vòng lặp an toàn).
    """
    while True:
        if aborted(wk):
            return False

        img = grab_screen_np(wk)
        ok_in, _, _  = find_on_frame(img, img_inside,  region=reg_inside,  threshold=DEFAULT_THR)
        ok_out, _, _ = find_on_frame(img, img_outside, region=reg_outside, threshold=DEFAULT_THR)
        free_img(img)

        if ok_in:
            return True

        if not ok_out:
            adb_safe(wk, "shell", "input", "keyevent", "4", timeout=2)
            if not sleep_coop(wk, esc_delay):
                return False
            continue

        tap_center(wk, reg_outside)
        if not sleep_coop(wk, click_delay):
            return False

def open_by_swiping(wk, tpl_path: str, region: Tuple[int,int,int,int],
                    swipes: list[Tuple[int,int,int,int,int]],
                    tries_each: int = 3, settle: float = 0.3, thr: float = DEFAULT_THR) -> bool:
    """
    Tìm template theo pattern 'check trước → swipe → check sau' theo danh sách swipes.
    """
    # check ngay
    img = grab_screen_np(wk)
    ok, pt, _ = find_on_frame(img, tpl_path, region=region, threshold=thr)
    free_img(img)
    if ok and pt:
        tap(wk, *pt)
        if not sleep_coop(wk, settle):
            return False
        return True

    for (x1, y1, x2, y2, dur) in swipes:
        for _ in range(tries_each):
            if aborted(wk):
                return False
            # check trước swipe
            img = grab_screen_np(wk)
            ok, pt, _ = find_on_frame(img, tpl_path, region=region, threshold=thr)
            free_img(img)
            if ok and pt:
                tap(wk, *pt)
                if not sleep_coop(wk, settle):
                    return False
                return True

            # swipe + check sau
            swipe(wk, x1, y1, x2, y2, dur_ms=dur)
            if not sleep_coop(wk, 0.3):
                return False

            img = grab_screen_np(wk)
            ok, pt, _ = find_on_frame(img, tpl_path, region=region, threshold=thr)
            free_img(img)
            if ok and pt:
                tap(wk, *pt)
                if not sleep_coop(wk, settle):
                    return False
                return True
    return False

def reopen_until_visible(wk, open_fn: Callable[[], bool], check_tpl: str,
                         region: Optional[Tuple[int,int,int,int]] = None,
                         max_rounds: int = 6, wait: float = 0.2, thr: float = DEFAULT_THR) -> bool:
    """
    Gọi open_fn() lặp lại cho tới khi thấy check_tpl (theo region), tối đa max_rounds.
    """
    rounds = 0
    while rounds < max_rounds and not aborted(wk):
        if open_fn():
            # sau khi open thành công, xác nhận thấy template
            for _ in range(int(3 / max(wait, 0.1))):
                img = grab_screen_np(wk)
                ok, _, _ = find_on_frame(img, check_tpl, region=region, threshold=thr)
                free_img(img)
                if ok:
                    return True
                if not sleep_coop(wk, wait):
                    return False
        rounds += 1
        if (rounds % 2) == 0:
            mem_relief()
    return False
def ocr_text_in_region(wk, y1: int, y2: int, x1: int, x2: int,
                       lang_preference: str = "vie+eng",
                       psm: int = 6,
                       whitelist: str | None = None) -> str:
    """
    Chụp màn hình hiện tại, cắt ROI theo (y1:y2, x1:x2), OCR chữ trong vùng.
    - Ưu tiên ngôn ngữ 'vie+eng' nếu khả dụng; fallback 'vie' rồi 'eng'.
    - Xử lý toàn bộ trong RAM, không lưu file tạm trên máy.
    - Dọn bộ nhớ sau khi xong.

    Args:
        wk: worker có adb/adp_bin (chuyển tiếp vào grab_screen_np).
        y1, y2, x1, x2: toạ độ vùng cần OCR (theo thứ tự y rồi x).
        lang_preference: chuỗi ngôn ngữ ưu tiên, mặc định "vie+eng".
        psm: Tesseract page segmentation mode (mặc định 6).
        whitelist: nếu cần giới hạn ký tự cho Tesseract.

    Returns:
        str: text đã OCR (strip). Trả "" nếu lỗi/không có gì.
    """
    img = grab_screen_np(wk)
    if img is None:
        return ""

    try:
        # Clamp to bounds & kiểm tra hợp lệ
        h, w = img.shape[:2]
        y1c, y2c = max(0, min(y1, h)), max(0, min(y2, h))
        x1c, x2c = max(0, min(x1, w)), max(0, min(x2, w))
        if y2c <= y1c or x2c <= x1c:
            return ""

        # Cắt ROI (copy) và tiền xử lý: gray -> blur -> Otsu
        roi = img[y1c:y2c, x1c:x2c].copy()
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

        # Chọn ngôn ngữ: ưu tiên vie+eng -> vie -> eng
        langs_avail = (_list_langs() or "").lower()
        def _has(lang_code: str) -> bool:
            return lang_code and lang_code.lower() in langs_avail

        chosen = None
        # nếu lang_preference là combo kiểu 'a+b'
        if "+" in (lang_preference or ""):
            parts = [p.strip().lower() for p in lang_preference.split("+") if p.strip()]
            if parts and all(_has(p) for p in parts):
                chosen = "+".join(parts)
        # nếu chưa chọn được thì thử mặc định chuỗi ưu tiên
        if not chosen:
            if _has("vie") and _has("eng"):
                chosen = "vie+eng"
            elif _has("vie"):
                chosen = "vie"
            elif _has("eng"):
                chosen = "eng"
            else:
                chosen = "eng"  # fallback an toàn

        # Cấu hình Tesseract (không lưu file nào)
        cfg = f'--psm {psm} --oem 3 --tessdata-dir "{TESSDATA_DIR}"'
        if whitelist:
            cfg += f' -c tessedit_char_whitelist={whitelist}'

        text = pytesseract.image_to_string(gray, lang=chosen, config=cfg)
        return (text or "").strip()

    except Exception:
        return ""
    finally:
        # Dọn RAM
        try:
            free_img(img, roi, gray)  # gray/roi có thể chưa tồn tại nếu lỗi sớm
        except:
            try:
                free_img(img)
            except:
                pass
        mem_relief()
