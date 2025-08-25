import threading
import time
import logging
from core.adb_client import ADBClient
from core.minicap_stream import MinicapStream
from core.base_runner import BaseRunner

logger = logging.getLogger(__name__)


class DeviceState:
    def __init__(self):
        self._lock = threading.Lock()
        self._latest_frame_bytes = None
        self.initialized = threading.Event()

    def update_frame(self, frame_bytes):
        with self._lock:
            self._latest_frame_bytes = frame_bytes
        if not self.initialized.is_set():
            self.initialized.set()

    def get_latest_frame_bytes(self):
        if not self.initialized.wait(timeout=15):
            logger.error("Timeout waiting for the first frame.")
            return None
        with self._lock:
            return self._latest_frame_bytes[:] if self._latest_frame_bytes else None


class CaptureThread(threading.Thread):
    def __init__(self, state, stream, device_id):
        super().__init__(name=f"Capture-{device_id}", daemon=True)
        self.state = state
        self.stream = stream
        self.running = False

    def run(self):
        self.running = True
        logger.info(f"{self.name} started.")
        if not self.stream.connected:
            self.running = False
            return
        while self.running:
            frame_bytes = self.stream.read_frame_bytes()
            if frame_bytes:
                self.state.update_frame(frame_bytes)
            else:
                if self.running: logger.error("Stream disconnected.")
                break
        self.running = False
        logger.info(f"{self.name} stopped.")

    def stop(self):
        self.running = False
        self.stream.close()


class AutoThread(BaseRunner, threading.Thread):
    def __init__(self, device_id, state, adb_client, flows, config):
        BaseRunner.__init__(self, device_id, state, adb_client, config)
        threading.Thread.__init__(self, name=f"Auto-{device_id}", daemon=True)
        self.flows = flows

    def run(self):
        logger.info(f"{self.name} started.")
        if not self.state.initialized.wait(timeout=15):
            logger.error(f"{self.name} failed to start: No first frame.")
            self.running = False
            return
        try:
            # Chạy tuần tự các flow được giao
            for flow_func in self.flows:
                if not self.running:
                    logger.info("AutoThread received stop signal. Aborting flow sequence.")
                    break
                logger.info(f"Executing flow: {flow_func.__name__}")
                flow_func(self)  # Truyền chính nó (BaseRunner) vào hàm flow
        except Exception as e:
            logger.exception(f"An unexpected error occurred in {self.name}: {e}")
        finally:
            self.running = False
            logger.info(f"{self.name} finished.")


class Worker:
    def __init__(self, device_id, adb_path, minicap_port=1313, config=None):
        self.device_id = device_id
        self.minicap_port = minicap_port
        self.config = config or {}
        self.adb = ADBClient(device_id, adb_path=adb_path)
        self.stream = MinicapStream(port=minicap_port)
        self.state = DeviceState()
        self.capture_thread = None
        self.auto_thread = None
        self.is_running = False

    def start(self, flows_to_run):
        if self.is_running:
            logger.warning("Worker is already running.")
            return False

        logger.info(f"Starting worker for {self.device_id}")
        if not self.adb.start_minicap_service(): return False
        if self.adb.forward(self.minicap_port) is None: return False
        time.sleep(0.5)
        if not self.stream.connect(): return False

        self.capture_thread = CaptureThread(self.state, self.stream, self.device_id)
        self.auto_thread = AutoThread(self.device_id, self.state, self.adb, flows_to_run, self.config)

        self.capture_thread.start()
        self.auto_thread.start()
        self.is_running = True
        return True

    def stop(self):
        if not self.is_running:
            return

        logger.info(f"Stopping worker for {self.device_id}...")
        if self.auto_thread: self.auto_thread.stop()
        if self.capture_thread: self.capture_thread.stop()

        # Chờ các luồng kết thúc
        if self.auto_thread and self.auto_thread.is_alive(): self.auto_thread.join(timeout=3)
        if self.capture_thread and self.capture_thread.is_alive(): self.capture_thread.join(timeout=3)

        self.adb.remove_forward(self.minicap_port)
        self.adb.stop_minicap_service()
        self.is_running = False
        logger.info("Worker stopped.")