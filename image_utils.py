import cv2
import numpy as np
import os
import logging

# Import resource_path từ module của bạn
try:
    from module import resource_path
except ImportError:
    logging.error("Không thể import resource_path từ module.py.")


    def resource_path(relative_path):
        return os.path.join(os.path.abspath("."), relative_path)


def load_template(template_name):
    """Tải ảnh mẫu từ thư mục templates, sử dụng resource_path."""
    template_path = resource_path(os.path.join("templates", template_name))

    if not os.path.exists(template_path):
        # logging.warning(f"Không tìm thấy template: {template_path}")
        return None
    # Đọc ảnh màu
    return cv2.imread(template_path, cv2.IMREAD_COLOR)


def find_template(screen_np, template, threshold=0.8):
    """
    Tìm kiếm template trong ảnh màn hình (screen_np).
    """
    if screen_np is None or template is None:
        return None

    try:
        result = cv2.matchTemplate(screen_np, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        if max_val >= threshold:
            h, w = template.shape[:2]
            center_x = max_loc[0] + w // 2
            center_y = max_loc[1] + h // 2
            return center_x, center_y
        else:
            return None
    except cv2.error as e:
        logging.error(
            f"Lỗi OpenCV trong quá trình matchTemplate. Kích thước ảnh: {screen_np.shape if screen_np is not None else 'None'}. Lỗi: {e}")
        return None