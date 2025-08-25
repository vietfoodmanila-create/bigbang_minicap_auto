import cv2
import numpy as np
import logging
import os

logger = logging.getLogger(__name__)

class ScreenUtils:
    def __init__(self, template_dir="templates"):
        self.template_dir = template_dir

    def _load_template(self, template_name):
        """Tải ảnh mẫu từ file. Có thể mở rộng để caching nếu cần."""
        # Hỗ trợ gọi bằng tên file (vd: "login_button.png") hoặc chỉ tên (vd: "login_button")
        if not template_name.lower().endswith(('.png', '.jpg', '.jpeg')):
            template_path = os.path.join(self.template_dir, template_name + ".png")
        else:
            template_path = os.path.join(self.template_dir, template_name)

        template = cv2.imread(template_path)
        if template is None:
            logger.error(f"Template not found or failed to load at {template_path}")
        return template

    def find_template(self, screen_np, template_name, threshold=0.8):
        """
        Tìm kiếm template trên ảnh màn hình.

        Args:
            screen_np: Ảnh màn hình (NumPy array).
            template_name: Tên của template trong thư mục templates.
            threshold: Ngưỡng nhận diện.
        Returns:
            Tọa độ (x, y) tâm điểm vùng khớp, hoặc None.
        """
        if screen_np is None:
            return None

        template = self._load_template(template_name)

        if template is None:
            return None

        try:
            # Sử dụng phương pháp so khớp chuẩn hóa
            result = cv2.matchTemplate(screen_np, template, cv2.TM_CCOEFF_NORMED)
        except cv2.error as e:
            logger.error(f"Error during template matching for '{template_name}': {e}")
            return None

        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        if max_val >= threshold:
            h, w = template.shape[:2]
            center_x = max_loc[0] + w // 2
            center_y = max_loc[1] + h // 2
            return center_x, center_y
        else:
            return None