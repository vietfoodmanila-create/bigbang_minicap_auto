import socket
import struct
import logging
import time

logger = logging.getLogger(__name__)

class MinicapStream:
    def __init__(self, host='127.0.0.1', port=1313):
        self.host = host
        self.port = port
        self.socket = None
        self.banner = {}
        self.connected = False

    def connect(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5.0)
            self.socket.connect((self.host, self.port))
            self.socket.settimeout(None)
            self._read_banner()
            self.connected = True
            logger.info(f"Connected to Minicap stream at {self.host}:{self.port}")
            return True
        except (ConnectionRefusedError, socket.timeout, ConnectionError) as e:
            logger.error(f"Failed to connect to Minicap: {e}")
            self.close()
            return False
        except Exception as e:
            logger.error(f"Unexpected error during Minicap connection: {e}")
            self.close()
            return False

    def _read_banner(self):
        data = self._read_exact(24)
        if not data or len(data) < 24:
            raise ConnectionError("Failed to read Minicap banner")
        (version, length, pid, real_width, real_height,
         virtual_width, virtual_height, orientation, quirks) = struct.unpack('<BBIIIIIBB', data)
        self.banner = {'version': version, 'pid': pid}

    def read_frame_bytes(self):
        if not self.connected:
            return None
        try:
            header = self._read_exact(4)
            if not header: return None
            frame_length = struct.unpack('<I', header)[0]
            frame_data = self._read_exact(frame_length)
            return frame_data
        except ConnectionError as e:
            logger.warning(f"Minicap connection lost: {e}")
            self.close()
            return None
        except Exception as e:
            if self.connected:
                 logger.error(f"Error reading frame from Minicap: {e}")
            self.close()
            return None

    def _read_exact(self, length):
        data = b''
        while len(data) < length:
            if not self.socket: return None
            try:
                chunk = self.socket.recv(length - len(data))
                if not chunk:
                    raise ConnectionError("Socket connection broken")
                data += chunk
            except BlockingIOError:
                time.sleep(0.001)
                continue
        return data

    def close(self):
        self.connected = False
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
                self.socket.close()
            except Exception:
                pass
            self.socket = None
            logger.info("Minicap stream connection closed.")