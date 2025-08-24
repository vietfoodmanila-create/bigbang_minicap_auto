# updater.py
# (NÂNG CẤP) Có giao diện người dùng (UI) với thanh tiến trình và log chi tiết.

import sys
import os
import time
import zipfile
import subprocess
import shutil
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget, QVBoxLayout, QProgressBar, QTextEdit, QLabel
from PySide6.QtCore import Qt, QThread, Signal


# Lớp Worker để thực hiện tác vụ cập nhật trong một luồng riêng, tránh làm treo UI
class UpdateWorker(QThread):
    progress_changed = Signal(int, int, str)  # min, max, text
    log_message = Signal(str)
    finished = Signal(bool, str)  # success, message

    def __init__(self, zip_path_str, pid_str, executable_path):
        super().__init__()
        self.zip_path_str = zip_path_str
        self.pid_str = pid_str
        self.executable_path = executable_path
        self.main_app_executable = executable_path

    def run(self):
        try:
            zip_path = Path(self.zip_path_str)
            app_dir = Path(self.executable_path).parent

            self.log_message.emit(f"Đang chờ ứng dụng chính (PID: {self.pid_str}) đóng...")
            time.sleep(3)

            self.log_message.emit("Bắt đầu giải nén file cập nhật...")

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                file_list = zip_ref.infolist()
                total_files = len(file_list)
                self.progress_changed.emit(0, total_files, f"Đang giải nén {total_files} file...")

                for i, file_info in enumerate(file_list):
                    self.log_message.emit(f"-> Ghi đè file: {file_info.filename}")
                    zip_ref.extract(file_info, app_dir)
                    self.progress_changed.emit(i + 1, total_files, f"Đang giải nén ({i + 1}/{total_files})...")
                    time.sleep(0.05)  # Thêm một chút delay để người dùng có thể thấy

            self.log_message.emit("Giải nén hoàn tất.")

            # Dọn dẹp file zip
            try:
                os.remove(zip_path)
                self.log_message.emit(f"Đã xóa file tạm: {zip_path.name}")
            except Exception as e:
                self.log_message.emit(f"Lỗi khi xóa file zip: {e}")

            self.log_message.emit("Cập nhật hoàn tất!")
            self.finished.emit(True, "success")

        except Exception as e:
            self.log_message.emit(f"Lỗi nghiêm trọng trong quá trình cập nhật: {e}")
            self.finished.emit(False, str(e))


# Lớp giao diện chính của Updater
class UpdaterWindow(QWidget):
    def __init__(self, zip_path, pid, executable_path):
        super().__init__()
        self.executable_path = executable_path
        self.setWindowTitle("Đang cập nhật...")
        self.setFixedSize(450, 300)

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Đang chuẩn bị cập nhật...")
        self.status_label.setStyleSheet("font-weight: bold;")
        self.progress_bar = QProgressBar()
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)

        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.log_edit)

        # Khởi tạo và chạy worker
        self.worker = UpdateWorker(zip_path, pid, executable_path)
        self.worker.progress_changed.connect(self.update_progress)
        self.worker.log_message.connect(self.log)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def update_progress(self, value, max_value, text):
        self.progress_bar.setRange(0, max_value)
        self.progress_bar.setValue(value)
        self.status_label.setText(text)

    def log(self, message):
        self.log_edit.append(message)

    def on_finished(self, success, message):
        if success:
            self.status_label.setText("Hoàn tất! Đang khởi động lại...")
            self.log("Đang khởi động lại ứng dụng chính...")
            # Chờ 2 giây để người dùng đọc thông báo
            time.sleep(2)
            try:
                if self.executable_path.lower().endswith(".py"):
                    subprocess.Popen([sys.executable, self.executable_path])
                else:
                    subprocess.Popen([self.executable_path])
                QApplication.quit()
            except Exception as e:
                self.log(f"Lỗi khởi động lại: {e}")
                QMessageBox.critical(self, "Lỗi", "Không thể tự khởi động lại. Vui lòng mở lại ứng dụng thủ công.")
        else:
            self.status_label.setText("Cập nhật thất bại!")
            QMessageBox.critical(self, "Lỗi cập nhật", f"Quá trình cập nhật đã xảy ra lỗi:\n{message}")


if __name__ == "__main__":
    app = QApplication(sys.argv)

    if len(sys.argv) < 4:
        QMessageBox.critical(None, "Lỗi", "Updater được chạy không đúng cách. Vui lòng chạy từ ứng dụng chính.")
        sys.exit(1)

    zip_file, pid, executable = sys.argv[1], sys.argv[2], sys.argv[3]

    window = UpdaterWindow(zip_file, pid, executable)
    window.show()

    sys.exit(app.exec())