# config.py
# Cấu hình để sử dụng MỘT ADB DUY NHẤT và môi trường ổn định.

# ==== DEBUG ====
DEBUG = True
SHOT_DIR = "shots"

# ==== ADB (SỬ DỤNG PHIÊN BẢN ADB CHÍNH THỨC TỪ PLATFORM-TOOLS) ====
# Đường dẫn này sẽ được tự động cập nhật bởi main.py
PLATFORM_TOOLS_ADB_PATH = ""

# ==== Screen size (Android) ====
SCREEN_W, SCREEN_H = 900, 1600

# ==== Tesseract ====
TESSERACT_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSDATA_DIR  = r"C:\Program Files\Tesseract-OCR\tessdata"