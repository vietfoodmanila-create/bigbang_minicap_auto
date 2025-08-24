# File: pick_coords_standalone.py
# Phiên bản nâng cấp để kết nối với LDPlayer và đọc cấu hình tự động.

import sys
import subprocess
import time
import os
import uuid
from pathlib import Path

# Thử import các thư viện bên ngoài
try:
    import cv2
    import numpy as np
    import pyperclip
except ImportError:
    print("Lỗi: Vui lòng cài đặt các thư viện cần thiết bằng lệnh sau:")
    print("pip install opencv-python numpy pyperclip")
    sys.exit(1)

# ====================================================================
# === PHẦN 1: TỰ ĐỘNG ĐỌC CẤU HÌNH TỪ CONFIG.PY ======================
# ====================================================================
try:
    # Import các cấu hình cần thiết từ file config.py
    from config import LDPLAYER_ADB_PATH, SCREEN_W, SCREEN_H

    # !!! THAY ĐỔI ID CỦA MÁY ẢO BẠN MUỐN KẾT NỐI VÀO ĐÂY !!!
    # Bạn có thể lấy ID này từ giao diện của tool auto.
    DEVICE_ID = "emulator-5554"

    ADB_PATH = LDPLAYER_ADB_PATH

except ImportError:
    print("Lỗi: Không tìm thấy file config.py hoặc thiếu cấu hình cần thiết.")
    # Cấu hình dự phòng nếu không có file config.py
    ADB_PATH = r"D:\LDPlayer\LDPlayer9\adb.exe"  # Sửa lại nếu cần
    DEVICE_ID = "emulator-5554"
    SCREEN_W, SCREEN_H = 900, 1600

# Thư mục để lưu ảnh chụp
SHOT_DIR = "test/shots"
DEBUG = True


# ====================================================================
# === PHẦN 2: CÁC HÀM TIỆN ÍCH ADB VÀ MÀN HÌNH =======================
# ====================================================================

def _run(args, text=True):
    """Hàm chạy một lệnh và trả về kết quả."""
    # Ẩn cửa sổ dòng lệnh trên Windows
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    return subprocess.run(args, capture_output=True, text=text, startupinfo=startupinfo)


def adb(*args, text=True):
    """Hàm gửi lệnh ADB tới thiết bị đã chỉ định."""
    cmd_with_device = [ADB_PATH, "-s", DEVICE_ID] + list(args)
    if DEBUG:
        print("→ ADB:", " ".join([str(x) for x in cmd_with_device]))
    return _run(cmd_with_device, text=text)


def ensure_connected():
    """Đảm bảo ADB đã được kết nối với thiết bị."""
    if not Path(ADB_PATH).exists():
        raise FileNotFoundError(f"Không tìm thấy ADB ở: {ADB_PATH}")

    # Chạy lệnh 'adb devices' để kiểm tra
    out = _run([ADB_PATH, "devices"]).stdout
    if DEVICE_ID not in out or "device" not in out:
        raise RuntimeError(f"ADB chưa thấy thiết bị '{DEVICE_ID}'. Vui lòng đảm bảo LDPlayer đang chạy.")
    print(f"✅ ADB đã kết nối với thiết bị {DEVICE_ID}")


def screencap_cv() -> np.ndarray | None:
    """Chụp ảnh màn hình và trả về dưới dạng đối tượng OpenCV."""
    try:
        # Sử dụng phương pháp an toàn: lưu file tạm rồi đọc
        p = adb("exec-out", "screencap", "-p", text=False)
        if p.returncode != 0 or not p.stdout:
            raise RuntimeError("Không chụp được màn hình qua ADB.")

        data = p.stdout
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)

        if img is None:
            raise RuntimeError("Giải mã ảnh thất bại.")

        if DEBUG:
            Path(SHOT_DIR).mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = Path(SHOT_DIR) / f"screen_{ts}.png"
            cv2.imwrite(str(path), img)
            print(f"💾 Đã lưu ảnh chụp màn hình: {path} (kích thước={img.shape})")
        return img
    except Exception as e:
        print(f"Lỗi khi chụp màn hình: {e}")
        return None


# ====================================================================
# === PHẦN 3: LOGIC CHÍNH CỦA CÔNG CỤ CẮT ẢNH ========================
# ====================================================================

# Các biến toàn cục
SCALE = 0.6  # Tỷ lệ hiển thị của cửa sổ xem trước
img = None
disp = None
start = None
dragging = False


def copy_to_clipboard(txt: str):
    """Sao chép một chuỗi vào clipboard."""
    try:
        pyperclip.copy(txt)
        print(f"📋 Đã sao chép vào clipboard: {txt}")
    except Exception:
        print("(Cảnh báo: Không thể sao chép vào clipboard. Thư viện pyperclip có thể chưa được cài đặt.)")


def on_mouse(event, x, y, flags, param):
    """Hàm xử lý sự kiện chuột."""
    global start, dragging, disp, img

    # Chuyển tọa độ trên cửa sổ xem trước về tọa độ gốc của ảnh
    gx, gy = int(x / SCALE), int(y / SCALE)

    # Nhấn chuột phải: Lấy và sao chép tọa độ của một điểm
    if event == cv2.EVENT_RBUTTONDOWN:
        point_txt = f"{gx},{gy}"
        print(f"📍 Tọa độ điểm: {point_txt}")
        copy_to_clipboard(point_txt)

    # Nhấn chuột trái: Bắt đầu kéo
    if event == cv2.EVENT_LBUTTONDOWN:
        start = (gx, gy)
        dragging = True

    # Di chuyển chuột trong khi đang kéo: Vẽ hình chữ nhật
    elif event == cv2.EVENT_MOUSEMOVE and dragging:
        disp[:] = cv2.resize(img, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
        x1, y1 = start
        cv2.rectangle(disp, (int(x1 * SCALE), int(y1 * SCALE)), (x, y), (0, 255, 0), 2)

    # Thả chuột trái: Hoàn tất việc chọn vùng (ROI)
    elif event == cv2.EVENT_LBUTTONUP and dragging:
        dragging = False
        x1, y1 = start
        x2, y2 = gx, gy

        # Sắp xếp lại tọa độ để luôn có (x1, y1) là góc trên trái
        left, top = min(x1, x2), min(y1, y2)
        right, bottom = max(x1, x2), max(y1, y2)

        if right <= left or bottom <= top:
            print("⚠️ Vùng chọn (ROI) rỗng, vui lòng thử lại.")
            return

        # Cắt vùng ảnh đã chọn
        roi = img[top:bottom, left:right].copy()

        # Lưu file và thông báo
        Path(SHOT_DIR).mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        roi_filename = f"roi_{ts}_{left}-{top}_{right}-{bottom}.png"
        roi_path = Path(SHOT_DIR) / roi_filename
        cv2.imwrite(str(roi_path), roi)
        print(f"💾 Đã lưu vùng chọn (ROI): {roi_path.resolve()}")

        roi_txt = f"{left},{top},{right},{bottom}"
        print(f"📐 Tọa độ vùng chọn (ROI): {roi_txt}")
        copy_to_clipboard(roi_txt)


if __name__ == "__main__":
    try:
        ensure_connected()
        print("Đang chụp ảnh màn hình ban đầu...")
        img = screencap_cv()
        if img is None:
            raise RuntimeError("Không thể chụp ảnh màn hình ban đầu.")

        disp = cv2.resize(img, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)

        title = "Chon Vung ROI (Keo chuot trai = Cat anh, Chuot phai = Lay toa do, 'r' = Lam moi, 'q'/ESC = Thoat)"
        cv2.namedWindow(title)
        cv2.setMouseCallback(title, on_mouse)

        while True:
            cv2.imshow(title, disp)
            key = cv2.waitKey(20) & 0xFF

            # Thoát chương trình
            if key in (ord('q'), 27):  # 27 là mã của phím ESC
                break

            # Nhấn 'r' để làm mới ảnh
            if key == ord('r'):
                print("\n🔄 Đang làm mới ảnh màn hình...")
                new_img = screencap_cv()
                if new_img is not None:
                    img = new_img
                    disp = cv2.resize(img, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
                    print("Làm mới thành công!")
                else:
                    print("Làm mới thất bại, giữ lại ảnh cũ.")

        cv2.destroyAllWindows()

    except Exception as e:
        print(f"\n❌ Lỗi nghiêm trọng: {e}")
        input("Nhấn Enter để thoát.")
        sys.exit(1)