import cv2
import numpy as np
import time
import logging
import os
from collections import namedtuple

logger = logging.getLogger(__name__)
Point = namedtuple('Point', ['x', 'y'])


class BaseRunner:
    def __init__(self, device_id, device_state, adb_client, config=None):
        self.device_id = device_id
        self.state = device_state
        self.adb = adb_client
        self.config = config or {}
        self.image_path = "images"
        self.running = True  # Thêm cờ running để các flows có thể kiểm tra

    def grab_screen_np(self):
        frame_bytes = self.state.get_latest_frame_bytes()
        if frame_bytes is None:
            logger.warning("Failed to grab screen: No frame available.")
            return None
        try:
            image_np = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
            if image_np is None:
                raise ValueError("cv2.imdecode failed, frame might be corrupted.")
            return image_np
        except Exception as e:
            logger.error(f"Failed to decode frame: {e}")
            return None

    # --- CÁC HÀM API TƯƠNG THÍCH 100% VỚI ACCOUNT RUNNER CŨ ---
    def stop(self):
        self.running = False
        logger.info("Runner stop signal received.")

    def tap(self, x, y):
        logger.debug(f"Tapping at ({x}, {y})")
        self.adb.tap(x, y)

    def swipe(self, x1, y1, x2, y2, duration=300):
        logger.debug(f"Swiping from ({x1}, {y1}) to ({x2}, {y2})")
        self.adb.swipe(x1, y1, x2, y2, duration)

    def find_template(self, template_name, threshold=0.8, screen=None):
        template_path = os.path.join(self.image_path, template_name)
        if not os.path.exists(template_path):
            logger.error(f"Template image not found at: {template_path}")
            return None

        template = cv2.imread(template_path)
        if screen is None:
            screen = self.grab_screen_np()
        if screen is None:
            return None

        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= threshold:
            h, w, _ = template.shape
            return Point(max_loc[0] + w // 2, max_loc[1] + h // 2)
        return None

    def wait_for_template(self, template_name, timeout=10, threshold=0.8, interval=0.1):
        logger.info(f"Waiting for '{template_name}' (Timeout: {timeout}s)")
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not self.running: return None  # Kiểm tra cờ dừng
            coords = self.find_template(template_name, threshold)
            if coords:
                logger.info(f"Found '{template_name}' at {coords}.")
                return coords
            time.sleep(interval)
        logger.warning(f"Timeout waiting for '{template_name}'.")
        return None

    def click_if_exists(self, template_name, threshold=0.8, timeout=1):
        coords = self.wait_for_template(template_name, timeout=timeout, threshold=threshold)
        if coords:
            self.tap(coords.x, coords.y)
            return True
        return False