# File: test_snake_game_debug.py
# Kịch bản CHỈ DÙNG ĐỂ DEBUG: Chụp ảnh, vẽ lưới, nhận diện đối tượng và lưu kết quả.

import sys
import subprocess
import time
import os
import cv2
import numpy as np
from pathlib import Path

# ==============================================================================
# ## --- CẤU HÌNH (Hãy đảm bảo các thông số này chính xác) ---
# ==============================================================================
ADB_PATH = r"D:\Program Files\Nox\bin\nox_adb.exe"
DEVICE = "127.0.0.1:62025"
GAME_AREA_COORDS = (70, 404, 826, 1171)
GRID_DIMENSIONS = (15, 15)
TEMPLATE_THRESHOLD = 0.80  # Giảm nhẹ ngưỡng để dễ bắt hình hơn khi debug


# ==============================================================================
# ## --- CÁC HÀM TIỆN ÍCH (Mô phỏng module.py) ---
# ==============================================================================

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


SNAKE_IMAGES = {
    'head': resource_path("images/snake/head.png"),
    'food': resource_path("images/snake/bait.png"),
    'wall': resource_path("images/snake/ice.png")
}
DEBUG_COLORS = {
    'head': (0, 255, 255),  # Vàng
    'food': (0, 0, 255),  # Đỏ
    'wall': (255, 0, 0)  # Xanh dương
}


def log_wk(wk, msg: str):
    port = getattr(wk, 'port', 'DEBUG')
    print(f"[{port}] {msg}", flush=True)


def grab_screen_np(wk) -> np.ndarray | None:
    device_serial = getattr(wk, 'device', DEVICE)
    try:
        cmd = [ADB_PATH, "-s", device_serial, "exec-out", "screencap", "-p"]
        p = subprocess.run(cmd, capture_output=True, timeout=8)
        if p.returncode != 0: return None
        return cv2.imdecode(np.frombuffer(p.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        return None


def draw_grid_on_image(image, grid_dims, game_area):
    """Vẽ lưới lên vùng game của ảnh."""
    x1, y1, x2, y2 = game_area
    game_img_area = image[y1:y2, x1:x2]

    h, w, _ = game_img_area.shape
    rows, cols = grid_dims

    # Vẽ các đường dọc
    for i in range(1, cols):
        x = int(i * w / cols)
        cv2.line(game_img_area, (x, 0), (x, h), (0, 0, 255), 1)  # Màu đỏ

    # Vẽ các đường ngang
    for i in range(1, rows):
        y = int(i * h / rows)
        cv2.line(game_img_area, (0, y), (w, y), (0, 0, 255), 1)


def find_and_draw_objects(image, grid_dims, game_area):
    """Tìm và vẽ vòng tròn quanh các đối tượng được nhận diện."""
    x1, y1, x2, y2 = game_area
    game_img = image[y1:y2, x1:x2]

    h, w, _ = game_img.shape
    cell_w = w / grid_dims[1]
    cell_h = h / grid_dims[0]

    log_wk(None, "Bắt đầu nhận diện các đối tượng...")
    for name, path in SNAKE_IMAGES.items():
        template = cv2.imread(path, cv2.IMREAD_COLOR)
        if template is None:
            log_wk(None, f"  LỖI: Không tải được ảnh mẫu '{path}'")
            continue

        res = cv2.matchTemplate(game_img, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= TEMPLATE_THRESHOLD)

        count = 0
        for pt in zip(*loc[::-1]):
            center_x = int(pt[0] + template.shape[1] / 2)
            center_y = int(pt[1] + template.shape[0] / 2)

            # Vẽ vòng tròn lên ảnh
            cv2.circle(game_img, (center_x, center_y), int(cell_w / 2), DEBUG_COLORS[name], 2)
            count += 1
        log_wk(None, f"  Tìm thấy {count} đối tượng '{name}'")


# ==============================================================================
# ## --- PHẦN THỰC THI CHÍNH ---
# ==============================================================================

if __name__ == "__main__":
    class MockWorker:
        def __init__(self, port, device_serial):
            self.port = port
            self.device = device_serial


    mock_worker = MockWorker(port=int(DEVICE.split(':')[-1]), device_serial=DEVICE)

    log_wk(mock_worker, "Bắt đầu kịch bản DEBUG...")
    log_wk(mock_worker, "Bước 1: Chụp ảnh màn hình từ thiết bị...")
    screenshot = grab_screen_np(mock_worker)

    if screenshot is None:
        log_wk(mock_worker, "LỖI: Không thể chụp ảnh màn hình. Vui lòng kiểm tra kết nối ADB.")
    else:
        log_wk(mock_worker, "Chụp ảnh thành công.")

        # Bước 2: Vẽ lưới
        log_wk(mock_worker, f"Bước 2: Vẽ lưới {GRID_DIMENSIONS[0]}x{GRID_DIMENSIONS[1]} lên vùng {GAME_AREA_COORDS}...")
        draw_grid_on_image(screenshot, GRID_DIMENSIONS, GAME_AREA_COORDS)

        # Bước 3: Tìm và đánh dấu đối tượng
        log_wk(mock_worker, "Bước 3: Tìm và đánh dấu các đối tượng...")
        find_and_draw_objects(screenshot, GRID_DIMENSIONS, GAME_AREA_COORDS)

        # Bước 4: Lưu file ảnh kết quả
        output_filename = "debug_grid_and_objects.png"
        try:
            cv2.imwrite(output_filename, screenshot)
            log_wk(mock_worker,
                   f"Bước 4: THÀNH CÔNG! Đã lưu ảnh kết quả vào file: '{os.path.abspath(output_filename)}'")
            log_wk(mock_worker, "Vui lòng mở file ảnh này lên để kiểm tra.")
        except Exception as e:
            log_wk(mock_worker, f"LỖI: Không thể lưu file ảnh kết quả: {e}")