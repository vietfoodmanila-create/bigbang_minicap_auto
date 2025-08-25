import threading
import queue
import time
import logging
import cv2
import numpy as np
import subprocess

# Import các utilities (đã được cập nhật để dùng config.py)
import adb_utils
import image_utils

try:
    import config  # Import cấu hình để sử dụng SCREEN_W/H
except ImportError:
    logging.error("Không tìm thấy config.py trong worker.py. Sử dụng giá trị mặc định.")
    config = type('Config', (object,), {'SCREEN_W': 900, 'SCREEN_H': 1600})

from minicap_stream import MinicapStreamParser

# Import các kịch bản auto (ví dụ)
# Đảm bảo các file flows của bạn được import tại đây
try:
    from flows import example_flow
except ImportError:
    example_flow = None


class CaptureThread(threading.Thread):
    """
    "Người Quay Phim" (Producer) - Liên tục lấy khung hình từ Minicap.
    """

    def __init__(self, worker):
        super().__init__(name=f"Capture-{worker.device_id}")
        self.worker = worker
        self.stream_parser = MinicapStreamParser(port=self.worker.minicap_port)
        self.daemon = True

    def run(self):
        logging.info(f"[{self.worker.device_id}] Bắt đầu CaptureThread.")

        while not self.worker.stop_event.is_set():
            # 1. Xử lý kết nối
            if not self.stream_parser.socket:
                if not self.stream_parser.connect():
                    time.sleep(3)
                    continue

                logging.info(f"[{self.worker.device_id}] Đã thiết lập luồng Minicap.")

            # 2. Lấy khung hình
            # Hàm này bây giờ có timeout (xem minicap_stream.py) để phát hiện treo
            frame_data_jpeg = self.stream_parser.get_next_frame()

            # 3. Cập nhật Queue
            if frame_data_jpeg:
                self._update_queue(frame_data_jpeg)
            else:
                # Nếu trả về None, kết nối đã mất hoặc bị timeout. stream_parser đã tự đóng socket.
                logging.warning(
                    f"[{self.worker.device_id}] Mất kết nối hoặc Timeout luồng Minicap. Chuẩn bị kết nối lại.")
                time.sleep(1)

        self.stream_parser.close()
        logging.info(f"[{self.worker.device_id}] Đã dừng CaptureThread.")

    def _update_queue(self, frame_data):
        """Đảm bảo hàng đợi luôn chỉ chứa khung hình mới nhất (Queue maxsize=1)."""
        # 1. Xóa queue nếu nó đang đầy (để không bao giờ bị block)
        try:
            self.worker.frame_queue.get_nowait()
        except queue.Empty:
            pass

        # 2. Đặt frame mới vào
        try:
            self.worker.frame_queue.put_nowait(frame_data)
        except queue.Full:
            pass


class AutoThread(threading.Thread):
    """
    "Đạo Diễn" (Consumer/AccountRunner) - Chứa logic auto.
    """

    def __init__(self, worker):
        super().__init__(name=f"Auto-{worker.device_id}")
        self.worker = worker

    def run(self):
        logging.info(f"[{self.worker.device_id}] Bắt đầu AutoThread.")

        try:
            # --- TÍCH HỢP LOGIC AUTO CỦA BẠN TẠI ĐÂY ---
            # Giữ nguyên logic gọi các file flows của bạn.

            if example_flow:
                # Truyền 'self.worker' vào để kịch bản sử dụng các hàm tương thích
                example_flow.run(self.worker)
            else:
                logging.warning(
                    f"[{self.worker.device_id}] Không có kịch bản auto mẫu. Tích hợp kịch bản chính của bạn tại đây.")

        except Exception as e:
            logging.exception(f"[{self.worker.device_id}] Lỗi nghiêm trọng trong AutoThread: {e}")

        finally:
            # Khi luồng Auto kết thúc, ra hiệu lệnh dừng toàn bộ worker
            logging.info(f"[{self.worker.device_id}] Hoàn thành AutoThread. Ra hiệu lệnh dừng Worker.")
            self.worker.stop()


class DeviceWorker:
    """
    Quản lý các luồng và cung cấp các hàm tương thích cho Flows.
    """

    def __init__(self, device_id, minicap_port=1313, resize_to_config=False):
        self.device_id = device_id
        self.minicap_port = minicap_port
        self.resize_to_config = resize_to_config  # Tùy chọn để bật/tắt resize

        # Tài nguyên dùng chung
        self.frame_queue = queue.Queue(maxsize=1)  # "Hòm thư"
        self.stop_event = threading.Event()

        # Các luồng và tiến trình
        self.capture_thread = None
        self.auto_thread = None
        self.minicap_process = None

        # Lưu độ phân giải thực tế (dùng cho việc scale tọa độ nếu resize_to_config=True)
        self.real_resolution = (None, None)

    def start(self):
        logging.info(f"Khởi động Worker cho thiết bị {self.device_id} (Cổng: {self.minicap_port})...")

        # 1. Khởi tạo Minicap
        if not self._initialize_minicap():
            logging.error(f"[{self.device_id}] Không thể khởi tạo Minicap. Dừng Worker.")
            self.stop()
            return

        # 2. Bắt đầu CaptureThread
        self.capture_thread = CaptureThread(self)
        self.capture_thread.start()

        # 3. Chờ khung hình đầu tiên
        if not self._wait_for_first_frame():
            logging.error(f"[{self.device_id}] Timeout hoặc lỗi khi chờ khung hình đầu tiên. Dừng Worker.")
            self.stop()
            return

        # 4. Bắt đầu AutoThread
        self.auto_thread = AutoThread(self)
        self.auto_thread.start()

    def _initialize_minicap(self):
        # Dọn dẹp các phiên cũ
        adb_utils.stop_minicap(self.device_id)
        adb_utils.remove_forward(self.device_id, self.minicap_port)

        # Lấy độ phân giải thực tế
        self.real_resolution = adb_utils.get_resolution(self.device_id)
        if self.real_resolution[0] is None:
            return False

        # Forward cổng
        if adb_utils.forward_port(self.device_id, self.minicap_port) is None:
            return False

        # Khởi động dịch vụ Minicap (Hàm start_minicap sử dụng độ phân giải thực tế)
        self.minicap_process = adb_utils.start_minicap(self.device_id)
        if self.minicap_process is None:
            adb_utils.remove_forward(self.device_id, self.minicap_port)
            return False

        return True

    def _wait_for_first_frame(self, timeout=15):
        logging.info(f"[{self.device_id}] Đang chờ khung hình đầu tiên...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not self.frame_queue.empty():
                logging.info(f"[{self.device_id}] Đã nhận khung hình đầu tiên. Hệ thống sẵn sàng.")
                return True

            if self.capture_thread and not self.capture_thread.is_alive():
                logging.error(f"[{self.device_id}] CaptureThread đã dừng đột ngột.")
                return False

            if self.stop_event.is_set():
                return False
            time.sleep(0.1)
        return False

    def stop(self):
        # Đảm bảo hàm stop chỉ chạy một lần
        if self.stop_event.is_set():
            return

        logging.info(f"Dừng Worker cho thiết bị {self.device_id}...")
        self.stop_event.set()

        # CẬP NHẬT: Lấy thông tin luồng hiện tại để tránh lỗi "cannot join current thread"
        current_thread = threading.current_thread()

        # Chờ các luồng kết thúc
        # Chỉ join nếu luồng đang sống VÀ nó không phải là luồng hiện tại
        if self.auto_thread and self.auto_thread.is_alive() and self.auto_thread != current_thread:
            logging.debug(f"[{self.device_id}] Chờ AutoThread kết thúc...")
            self.auto_thread.join(timeout=5)

        if self.capture_thread and self.capture_thread.is_alive() and self.capture_thread != current_thread:
            logging.debug(f"[{self.device_id}] Chờ CaptureThread kết thúc...")
            self.capture_thread.join(timeout=5)

        # Dọn dẹp tài nguyên (Luôn thực hiện)
        if self.minicap_process:
            self.minicap_process.terminate()
            try:
                self.minicap_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.minicap_process.kill()

        adb_utils.stop_minicap(self.device_id)
        adb_utils.remove_forward(self.device_id, self.minicap_port)

        logging.info(f"Worker cho thiết bị {self.device_id} đã dừng hoàn toàn.")

    # --- Lớp Tương Thích (API cho các file flows_*.py) ---

    def grab_screen_np(self, timeout=5):
        """
        (Tương thích flows cũ) Lấy ảnh màn hình mới nhất từ Queue.
        """
        if self.stop_event.is_set():
            return None

        try:
            # Lấy dữ liệu JPEG từ Queue (Rất nhanh)
            # Timeout này là thời gian tối đa AutoThread chờ CaptureThread cung cấp ảnh mới.
            frame_data_jpeg = self.frame_queue.get(block=True, timeout=timeout)

            # Giải mã JPEG thành NumPy array (OpenCV BGR format)
            image_np = cv2.imdecode(np.frombuffer(frame_data_jpeg, np.uint8), cv2.IMREAD_COLOR)

            if image_np is None:
                logging.warning(f"[{self.device_id}] Không thể giải mã khung hình.")
                return None

            # Xử lý Resize để tương thích với flows cũ
            if self.resize_to_config:
                target_w, target_h = config.SCREEN_W, config.SCREEN_H
                # Kiểm tra xem có cần resize không (tránh resize nếu kích thước đã khớp)
                if image_np.shape[1] != target_w or image_np.shape[0] != target_h:
                    image_np = cv2.resize(image_np, (target_w, target_h), interpolation=cv2.INTER_AREA)

            return image_np

        except queue.Empty:
            # Lỗi này xảy ra nếu AutoThread không nhận được ảnh trong vòng 'timeout' giây.
            logging.error(
                f"[{self.device_id}] Timeout ({timeout}s) khi chờ ảnh màn hình. CaptureThread có thể đang gặp sự cố hoặc đang kết nối lại.")

            # CẬP NHẬT: Không gọi self.stop() tại đây. Chỉ trả về None và để kịch bản (flows) quyết định.
            # Điều này cho phép CaptureThread có thời gian tự phục hồi (kết nối lại).
            return None
        except Exception as e:
            logging.error(f"[{self.device_id}] Lỗi không mong muốn trong grab_screen_np: {e}")
            return None

    def _scale_coords(self, x, y):
        """Chuyển đổi tọa độ từ kích thước config sang kích thước thực tế nếu đang bật resize."""
        if not self.resize_to_config or self.real_resolution[0] is None:
            return x, y

        real_w, real_h = self.real_resolution
        config_w, config_h = config.SCREEN_W, config.SCREEN_H

        if config_w == 0 or config_h == 0: return x, y

        scale_x = real_w / config_w
        scale_y = real_h / config_h

        return int(x * scale_x), int(y * scale_y)

    def tap(self, x, y):
        if self.stop_event.is_set(): return
        scaled_x, scaled_y = self._scale_coords(x, y)
        adb_utils.tap(self.device_id, scaled_x, scaled_y)

    def swipe(self, x1, y1, x2, y2, duration=300):
        if self.stop_event.is_set(): return
        scaled_x1, scaled_y1 = self._scale_coords(x1, y1)
        scaled_x2, scaled_y2 = self._scale_coords(x2, y2)
        adb_utils.swipe(self.device_id, scaled_x1, scaled_y1, scaled_x2, scaled_y2, duration)

    # Các hàm tiện ích khác (ví dụ)
    def find_template(self, template_name, threshold=0.8):
        screen = self.grab_screen_np()
        if screen is None:
            return None
        template = image_utils.load_template(template_name)
        return image_utils.find_template(screen, template, threshold)

    def click_on_template(self, template_name, threshold=0.8, max_attempts=3, delay=1):
        """Tìm kiếm và click vào template."""
        for attempt in range(max_attempts):
            if self.stop_event.is_set():
                return False

            coords = self.find_template(template_name, threshold)
            if coords:
                logging.info(f"[{self.device_id}] Đã tìm thấy '{template_name}' tại {coords}. Đang click.")
                self.tap(coords[0], coords[1])
                return True

            # Nếu không lấy được ảnh (coords=None) và queue đang rỗng, có thể CaptureThread đang gặp sự cố.
            if coords is None and self.frame_queue.empty():
                logging.info(f"[{self.device_id}] Chờ đợi thêm do Queue ảnh đang rỗng.")
                time.sleep(max(delay, 2))  # Chờ lâu hơn một chút
            else:
                time.sleep(delay)
        return False