# main.py
# Phiên bản mới, thiết lập môi trường và khởi chạy ứng dụng một cách an toàn.

import sys
import os
import socket
import subprocess
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog
from PySide6.QtCore import Qt

# Import các thành phần của ứng dụng
import config
from module import resource_path
from ui_main import MainWindow
from ui_auth import CloudClient, AuthDialog


# --- CÁC HÀM TIỆN ÍCH KHỞI ĐỘNG ---

def get_bundled_adb_path() -> str:
    """
    Lấy đường dẫn tuyệt đối đến tệp adb.exe đi kèm trong thư mục vendor.
    Hoạt động cho cả chế độ phát triển và khi đã đóng gói bằng PyInstaller.
    """
    return resource_path(os.path.join("vendor", "adb.exe"))


def force_kill_adb_server():
    """Dừng tất cả các tiến trình adb.exe đang chạy để đảm bảo sự ổn định."""
    try:
        print("Đang buộc dừng tất cả các tiến trình adb.exe...")
        # Lệnh taskkill của Windows mạnh hơn adb kill-server
        subprocess.run(
            ["taskkill", "/F", "/IM", "adb.exe"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        print("OK: Đã dọn dẹp các tiến trình ADB cũ.")
    except Exception:
        # Nếu thất bại, thử dùng lệnh của ADB
        try:
            print("Không tìm thấy taskkill, đang dùng adb kill-server...")
            subprocess.run([config.PLATFORM_TOOLS_ADB_PATH, "kill-server"], timeout=5)
        except Exception as e:
            print(f"Lưu ý: Không thể dừng ADB server. Lỗi: {e}")


def check_for_updates(cloud_client):
    """Kiểm tra và xử lý cập nhật."""
    # (Giữ nguyên logic kiểm tra cập nhật của bạn ở đây)
    return False  # Tạm thời tắt


# --- CẬP NHẬT CẤU HÌNH TỰ ĐỘNG ---
# Ghi đè biến trong config bằng đường dẫn ADB đi kèm phần mềm.
config.PLATFORM_TOOLS_ADB_PATH = get_bundled_adb_path()
print(f"Đã tự động cấu hình ADB path: {config.PLATFORM_TOOLS_ADB_PATH}")

# --- ĐIỂM BẮT ĐẦU CHƯƠNG TRÌNH ---
if __name__ == "__main__":
    # --- CƠ CHẾ CHẶN KHỞI ĐỘNG NHIỀU LẦN ---
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock_socket.bind(("127.0.0.1", 60101))
    except OSError:
        error_app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(
            None, "Lỗi Khởi Động",
            "Chương trình BigBang Auto đã được khởi động."
        )
        sys.exit(1)
    # --- KẾT THÚC CƠ CHẾ CHẶN ---

    force_kill_adb_server()

    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    app = QApplication(sys.argv)
    cloud = CloudClient()

    # --- LOGIC ĐĂNG NHẬP ---
    td = cloud.load_token()
    if not td or not td.token:
        dlg = AuthDialog()
        if dlg.exec() != QDialog.Accepted:
            sys.exit(0)
        cloud = dlg.cloud

    # --- KHỞI TẠO CÁC THÀNH PHẦN CHÍNH ---
    import checkbox_actions
    from ui_main import AppController  # Import AppController từ ui_main

    win = MainWindow(cloud=cloud)
    ctrl = AppController(win)  # AppController giờ nằm trong ui_main

    try:
        from ui_license import attach_license_system

        lic_ctrl = attach_license_system(win, cloud)
        win._license_controller = lic_ctrl
    except Exception as e:
        print(f"attach_license_system failed: {e}")

    # Hiển thị cửa sổ chính trước
    win.show()

    # Sau đó mới kiểm tra cập nhật
    if check_for_updates(cloud):
        sys.exit(0)

    # Bắt đầu vòng lặp sự kiện của ứng dụng
    sys.exit(app.exec())