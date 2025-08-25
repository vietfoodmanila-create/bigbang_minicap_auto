import socket
import struct
import logging
import time


class MinicapStreamParser:
    """
    Xử lý kết nối và phân tích cú pháp luồng dữ liệu từ Minicap.
    """

    def __init__(self, host='127.0.0.1', port=1313):
        self.host = host
        self.port = port
        self.socket = None
        self.read_buffer = b''
        self.banner_read = False
        self.read_timeout = 10.0  # CẬP NHẬT: Thời gian tối đa chờ dữ liệu (giây)

    def connect(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5.0)  # Timeout kết nối ban đầu 5s
            self.socket.connect((self.host, self.port))

            # CẬP NHẬT: Đặt timeout cho các thao tác đọc (recv)
            # Điều này giúp phát hiện khi dịch vụ Minicap bị treo nhưng kết nối vẫn mở.
            self.socket.settimeout(self.read_timeout)

            logging.info(f"Đã kết nối tới socket Minicap tại {self.host}:{self.port}")
            return True
        except (ConnectionRefusedError, socket.timeout) as e:
            logging.error(f"Không thể kết nối tới Minicap: {e}. Đảm bảo dịch vụ đang chạy và cổng đã được forward.")
            self.close()
            return False
        except Exception as e:
            logging.error(f"Lỗi không xác định khi kết nối Minicap: {e}")
            self.close()
            return False

    def get_next_frame(self):
        """Đọc luồng dữ liệu và trả về khung hình JPEG tiếp theo."""
        while True:
            if self.socket is None:
                return None

            try:
                # Đọc dữ liệu từ socket
                data = self.socket.recv(16384)
                if not data:
                    # Nếu nhận được dữ liệu rỗng, kết nối đã bị đóng bởi phía bên kia
                    logging.warning("Kết nối socket Minicap bị đóng bởi remote host.")
                    self.close()
                    return None
                self.read_buffer += data

            except socket.timeout:
                # CẬP NHẬT: Xử lý timeout khi đọc
                logging.error(
                    f"Timeout ({self.read_timeout}s) khi đọc dữ liệu từ socket. Luồng Minicap có thể bị treo.")
                self.close()
                return None
            except (ConnectionResetError, ConnectionAbortedError) as e:
                logging.error(f"Kết nối socket bị reset/aborted: {e}")
                self.close()
                return None
            except Exception as e:
                logging.error(f"Lỗi không xác định khi đọc từ socket: {e}")
                self.close()
                return None

            # Xử lý buffer
            frame = self._process_buffer()
            if frame:
                return frame

    def _process_buffer(self):
        # Bước 1: Đọc Banner (24 bytes, chỉ 1 lần)
        if not self.banner_read:
            if len(self.read_buffer) >= 24:
                self.read_buffer = self.read_buffer[24:]
                self.banner_read = True
            else:
                return None

        # Bước 2: Đọc Frame (4-byte header + dữ liệu JPEG)
        if len(self.read_buffer) < 4:
            return None

        # Đọc kích thước frame (little-endian unsigned int)
        try:
            frame_size = struct.unpack('<I', self.read_buffer[:4])[0]
        except struct.error:
            logging.error("Lỗi khi phân tích kích thước frame. Reset buffer.")
            self.read_buffer = b''
            self.banner_read = False
            return None

        # Kiểm tra xem buffer đã chứa đủ dữ liệu chưa
        if len(self.read_buffer) < 4 + frame_size:
            return None

        # Trích xuất dữ liệu frame (JPEG bytes)
        frame_data = self.read_buffer[4:4 + frame_size]

        # Cập nhật buffer
        self.read_buffer = self.read_buffer[4 + frame_size:]

        return frame_data

    def close(self):
        if self.socket:
            try:
                # Gửi tín hiệu đóng kết nối một cách lịch sự
                if hasattr(socket, 'SHUT_RDWR'):
                    self.socket.shutdown(socket.SHUT_RDWR)
                self.socket.close()
            except Exception:
                pass
            self.socket = None
        self.read_buffer = b''
        self.banner_read = False