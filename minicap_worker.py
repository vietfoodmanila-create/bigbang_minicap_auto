# minicap_worker.py
import queue
import logging
import cv2
import numpy as np

import adb_utils

class MinicapWorker:
    """
    Đây là lớp thay thế cho SimpleNoxWorker.
    Nó có các hàm tương tự nhưng sử dụng Minicap để lấy ảnh.
    """
    def __init__(self, device_worker, log_cb):
        self.device_worker = device_worker # Đây là DeviceWorker quản lý Minicap
        self.device_id = device_worker.device_id
        self._log_cb = log_cb
        # Gán các thuộc tính để tương thích với các file flows cũ
        self.game_package = "com.phsgdbz.vn"
        self.game_activity = "com.phsgdbz.vn/org.cocos2dx.javascript.GameTwActivity"
        self._abort = False # Biến để dừng các vòng lặp trong flows

    def _log(self, s: str):
        """Gửi log ra UI."""
        self._log_cb(s)

    def get_screen(self, timeout=5):
        """Hàm mới, cốt lõi: Lấy ảnh từ 'hộp thư' Minicap."""
        return self.device_worker.get_screen(timeout)

    # --- Các hàm sau đây là để tương thích 100% với SimpleNoxWorker cũ ---
    # Chúng chỉ đơn giản là gọi các hàm tương ứng trong adb_utils.

    def adb(self, *args, timeout=8):
        # Hàm này ít được dùng trực tiếp trong flows, nhưng vẫn giữ để tương thích
        _, stdout, stderr = adb_utils._run_adb_command(list(args), self.device_id, timeout)
        if stderr: self._log(f"ADB ERR: {stderr}")
        return _, stdout, stderr

    def tap(self, x, y):
        adb_utils.tap(self.device_id, x, y)

    def swipe(self, x1, y1, x2, y2, duration=300):
        adb_utils.swipe(self.device_id, x1, y1, x2, y2, duration)

    def input_text(self, text):
        adb_utils.input_text(self.device_id, text)

    def wait_app_ready(self, pkg: str, timeout_sec: int = 35) -> bool:
        # Logic này có thể được đơn giản hóa hoặc giữ nguyên nếu bạn cần
        import time
        end = time.time() + timeout_sec
        while time.time() < end:
            if self.device_worker.stop_event.is_set(): return False
            # Có thể thêm logic kiểm tra app ở đây nếu cần
            time.sleep(1.0)
        return True # Giả định là app luôn sẵn sàng