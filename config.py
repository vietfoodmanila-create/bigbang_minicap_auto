# config.py
# Cấu hình để sử dụng MỘT ADB DUY NHẤT cho cả Nox và LDPlayer

# ==== DEBUG ====
DEBUG = True
SHOT_DIR = "shots"
import os
# Import resource_path từ module.py
from module import resource_path

def get_bundled_adb_path() -> str:
    # Đường dẫn tương đối đến adb.exe trong thư mục vendor
    return resource_path(os.path.join("vendor", "adb.exe"))

# ==== ADB (SỬ DỤNG PHIÊN BẢN ADB CHÍNH THỨC TỪ PLATFORM-TOOLS) ====
PLATFORM_TOOLS_ADB_PATH = get_bundled_adb_path()
NOX_ADB_PATH = get_bundled_adb_path()
LDPLAYER_ADB_PATH = get_bundled_adb_path()

# In ra đường dẫn để kiểm tra khi khởi động
print(f"Đang tải cấu hình. ADB path: {PLATFORM_TOOLS_ADB_PATH}")

# Biến này cho phép quét cả hai loại máy ảo
EMULATOR_TYPE = "BOTH"

# Các biến cũ để tương thích
# Đây là biến quan trọng nhất mà adb_utils.py sẽ sử dụng
ADB_PATH = PLATFORM_TOOLS_ADB_PATH
DEVICE = ""

# ==== Screen size (Android) ====
# Kích thước màn hình chuẩn (sẽ dùng để resize ảnh nếu cần)
SCREEN_W, SCREEN_H = 900, 1600

# ==== Tesseract ====
# (Giữ nguyên cấu hình Tesseract của bạn nếu cần)
TESSERACT_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSDATA_DIR  = r"C:\Program Files\Tesseract-OCR\tessdata"