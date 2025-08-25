# File: flows_snake_game.py
# Bot tự động chơi game rắn săn mồi, phiên bản cuối cùng.
# - Sử dụng nhận diện bằng hình ảnh (Template Matching).
# - Tích hợp chiến lược "Vòng lặp khép kín" thông minh.
# - Tương thích hoàn toàn với cấu trúc project của bạn.

from __future__ import annotations
import time
import cv2
import numpy as np
import heapq

# ====== Import các hàm dùng chung từ module.py của bạn ======
from module import (
    log_wk,
    adb_safe,
    grab_screen_np,
    find_on_frame,
    tap,
    swipe,
    sleep_coop,
    aborted,
    free_img,
    mem_relief,
    resource_path
)

# ==============================================================================
# ## --- CẤU HÌNH --- (PHẦN BẠN CẦN CHỈNH SỬA)
# ==============================================================================

# 1. Vùng màn hình chứa lưới game (x1, y1, x2, y2)
GAME_AREA_COORDS = (70, 411, 826, 1178)  # Tọa độ bạn cung cấp

# 2. Kích thước của lưới game (số ô ngang x số ô dọc)
GRID_DIMENSIONS = (15, 15)  # 15 hàng, 15 cột

# 3. Đường dẫn đến các ảnh mẫu (template)
#    Hãy tạo thư mục images/snake và đặt các file ảnh này vào
SNAKE_IMAGES = {
    'head': resource_path("images/snake/head.png"),
    'food': resource_path("images/snake/bait.png"),
    'wall': resource_path("images/snake/ice.png")
}
# Ngưỡng nhận diện (có thể tinh chỉnh nếu cần)
TEMPLATE_THRESHOLD = 0.85

# 4. Tọa độ các cửa (theo ô lưới, bắt đầu từ 0)
#   Hàng và cột 7,8,9 tương ứng với index 6,7,8 trong lập trình
GATES = {
    'LEFT': [(7, 0), (8, 0), (9, 0)],
    'RIGHT': [(7, 14), (8, 14), (9, 14)],
    'UP': [(0, 7), (0, 8), (0, 9)],
    'DOWN': [(14, 7), (14, 8), (14, 9)]
}


# ==============================================================================
# ## --- CÁC HÀM CỐT LÕI CỦA BOT (Thuật toán và Phân tích) ---
# ==============================================================================

def analyze_scene_with_templates(image, grid_dims, game_area):
    """Phân tích ảnh bằng Template Matching, trả về grid và vị trí các đối tượng."""
    x1, y1, x2, y2 = game_area
    game_img = image[y1:y2, x1:x2]

    h, w, _ = game_img.shape
    cell_w = w / grid_dims[1]
    cell_h = h / grid_dims[0]

    grid = np.zeros(grid_dims, dtype=int)
    objects = {'snake_head': None, 'snake_body': [], 'food': [], 'wall': []}

    # Đánh dấu viền là tường
    grid[0, :] = 1
    grid[grid_dims[0] - 1, :] = 1
    grid[:, 0] = 1
    grid[:, grid_dims[1] - 1] = 1

    for name, path in SNAKE_IMAGES.items():
        template = cv2.imread(path, cv2.IMREAD_COLOR)
        if template is None:
            log_wk(None, f"LỖI: Không thể tải ảnh mẫu: {path}")
            continue

        # Dùng hàm find_on_frame của bạn để tìm tất cả các vị trí khớp
        # (Lưu ý: find_on_frame chỉ trả về 1 kết quả, cần sửa đổi để trả về nhiều)
        # Tạm thời, chúng ta sẽ quét thủ công để tìm nhiều đối tượng
        res = cv2.matchTemplate(game_img, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= TEMPLATE_THRESHOLD)

        for pt in zip(*loc[::-1]):  # pt là (x, y) của góc trên trái
            center_x = pt[0] + template.shape[1] / 2
            center_y = pt[1] + template.shape[0] / 2

            grid_c = int(center_x / cell_w)
            grid_r = int(center_y / cell_h)
            pos = (grid_r, grid_c)

            # Tránh thêm trùng lặp vị trí
            is_duplicate = False
            for obj_list in objects.values():
                if isinstance(obj_list, list) and pos in obj_list:
                    is_duplicate = True
                    break
            if pos == objects['snake_head']: is_duplicate = True
            if is_duplicate: continue

            if name == 'snake_head':
                objects['snake_head'] = pos
            else:
                objects[name].append(pos)
                if name == 'wall':
                    grid[pos] = 1

    # Thân rắn sẽ được suy luận từ vị trí đầu rắn và đường đi
    return grid, objects


# Các hàm heuristic, a_star_pathfinding, path_to_moves giữ nguyên
def heuristic(a, b): return abs(a[0] - b[0]) + abs(a[1] - b[1])


def a_star_pathfinding(grid, start, end, snake_body=[]):
    temp_grid = grid.copy()
    for pos in snake_body:
        temp_grid[pos] = 1  # Coi thân rắn là tường

    neighbors = [(0, 1), (0, -1), (1, 0), (-1, 0)]
    close_set, came_from, gscore = set(), {}, {start: 0}
    fscore = {start: heuristic(start, end)}
    oheap = []
    heapq.heappush(oheap, (fscore[start], start))
    while oheap:
        current = heapq.heappop(oheap)[1]
        if current == end:
            data = []
            while current in came_from:
                data.append(current)
                current = came_from[current]
            return data[::-1]
        close_set.add(current)
        for i, j in neighbors:
            neighbor = current[0] + i, current[1] + j
            if not (0 <= neighbor[0] < temp_grid.shape[0] and 0 <= neighbor[1] < temp_grid.shape[1]) or \
                    temp_grid[neighbor[0]][neighbor[1]] == 1:
                continue
            tentative_g_score = gscore[current] + 1
            if neighbor in close_set and tentative_g_score >= gscore.get(neighbor, 0): continue
            if tentative_g_score < gscore.get(neighbor, 0) or neighbor not in [i[1] for i in oheap]:
                came_from[neighbor], gscore[neighbor] = current, tentative_g_score
                fscore[neighbor] = tentative_g_score + heuristic(neighbor, end)
                heapq.heappush(oheap, (fscore[neighbor], neighbor))
    return None


def path_to_moves(path):
    if not path or len(path) < 2: return []
    moves = []
    for i in range(len(path) - 1):
        y1, x1 = path[i];
        y2, x2 = path[i + 1]
        if y2 < y1:
            moves.append('UP')
        elif y2 > y1:
            moves.append('DOWN')
        elif x2 < x1:
            moves.append('LEFT')
        elif x2 > x1:
            moves.append('RIGHT')
    return moves


def plan_circular_route(grid, snake_start, all_food, entry_gate_side):
    """Lập kế hoạch ăn hết mồi và quay về cửa vào."""
    full_path = []
    current_pos = snake_start
    snake_body = []  # Giả lập thân rắn mọc dài ra
    remaining_food = all_food.copy()

    # Giai đoạn 1: Ăn hết mồi
    while remaining_food:
        remaining_food.sort(key=lambda f: heuristic(current_pos, f))
        target_food = None
        path_segment = None

        # Tìm miếng mồi gần nhất có đường đi tới
        for food in remaining_food:
            path_segment = a_star_pathfinding(grid, current_pos, food, snake_body)
            if path_segment:
                target_food = food
                break

        if not target_food:
            log_wk(None, "CẢNH BÁO: Không tìm thấy đường đến bất kỳ miếng mồi nào.")
            return None

        full_path.extend(path_segment[1:])
        current_pos = target_food

        # Cập nhật thân rắn (đơn giản hóa)
        snake_body = path_segment[:-1]
        remaining_food.remove(target_food)

    # Giai đoạn 2: Quay về cửa vào
    exit_gates = GATES[entry_gate_side]
    exit_gates.sort(key=lambda g: heuristic(current_pos, g))
    target_gate = exit_gates[0]

    path_to_exit = a_star_pathfinding(grid, current_pos, target_gate, snake_body)
    if path_to_exit:
        full_path.extend(path_to_exit[1:])
    else:
        log_wk(None, f"CẢNH BÁO: Ăn xong nhưng không tìm thấy đường ra cửa {entry_gate_side}.")

    return full_path


# ==============================================================================
# ## --- ENTRY POINT ---
# ==============================================================================

def run_snake_game_flow(wk) -> bool:
    """Hàm chính để chạy auto game rắn."""
    if aborted(wk):
        log_wk(wk, "⛔ Hủy trước khi chạy game rắn.")
        return False

    log_wk(wk, "➡️ Bắt đầu Auto Game Rắn - Phiên bản Template Matching & Vòng lặp khép kín")

    # Xác định cửa vào ban đầu, mặc định là TRÁI
    entry_side = 'LEFT'

    try:
        while not aborted(wk):
            log_wk(wk, f"\n================ Chuẩn bị màn chơi mới (Vào từ cửa: {entry_side}) ================")

            # Chờ một chút để màn chơi tải xong
            if not sleep_coop(wk, 2.0): return False

            log_wk(wk, "Chụp và phân tích màn chơi...")
            screenshot = grab_screen_np(wk)
            if screenshot is None:
                log_wk(wk, "Lỗi chụp ảnh, thử lại sau 5 giây.")
                if not sleep_coop(wk, 5): return False
                continue

            grid, objects = analyze_scene_with_templates(screenshot, GRID_DIMENSIONS, GAME_AREA_COORDS)
            snake_head = objects.get('snake_head')
            all_food = objects.get('food', [])

            free_img(screenshot)

            if not snake_head:
                log_wk(wk, "Không tìm thấy đầu rắn bằng ảnh mẫu. Kiểm tra lại file 'head.png' và ngưỡng nhận diện.")
                if not sleep_coop(wk, 5): return False
                continue

            if not all_food:
                log_wk(wk, "Không tìm thấy mồi. Có thể đã qua màn. Chờ 5 giây.")
                if not sleep_coop(wk, 5): return False
                entry_side = 'RIGHT' if entry_side == 'LEFT' else 'LEFT'  # Đảo cửa cho màn tiếp theo
                continue

            log_wk(wk, f"Đã tìm thấy rắn tại {snake_head} và {len(all_food)} miếng mồi. Bắt đầu lập kế hoạch...")

            # Lập kế hoạch tổng thể
            master_path = plan_circular_route(grid, snake_head, all_food, entry_side)
            if not master_path:
                log_wk(wk, "Không thể lập kế hoạch cho màn này. Bỏ qua.")
                if not sleep_coop(wk, 5): return False
                continue

            all_moves = path_to_moves([snake_head] + master_path)
            log_wk(wk, f"Đã lập kế hoạch hoàn chỉnh với {len(all_moves)} nước đi.")

            # Thực thi kế hoạch
            current_head_pos = snake_head
            for i, move in enumerate(all_moves):
                if aborted(wk): return False

                center_x, center_y = 450, 800
                end_x, end_y = center_x, center_y
                distance = 150  # Có thể cần tinh chỉnh
                if move == 'UP':
                    end_y -= distance
                elif move == 'DOWN':
                    end_y += distance
                elif move == 'LEFT':
                    end_x -= distance
                elif move == 'RIGHT':
                    end_x += distance
                swipe(wk, center_x, center_y, end_x, end_y, dur_ms=100)

                # Chờ cho đến khi rắn di chuyển xong
                start_wait = time.time()
                moved = False
                while time.time() - start_wait < 2:
                    new_img = grab_screen_np(wk)
                    if new_img is None: continue
                    # Chỉ cần tìm đầu rắn để xác nhận di chuyển
                    _, new_objects = analyze_scene_with_templates(new_img, GRID_DIMENSIONS, GAME_AREA_COORDS)
                    new_head_pos = new_objects.get('snake_head')
                    free_img(new_img)

                    if new_head_pos and new_head_pos != current_head_pos:
                        log_wk(wk, f"  ({i + 1}/{len(all_moves)}) Di chuyển {move} thành công -> {new_head_pos}")
                        current_head_pos = new_head_pos
                        moved = True
                        break
                    if not sleep_coop(wk, 0.1): return False

                if not moved:
                    log_wk(wk, "LỖI: Rắn không di chuyển! Hủy bỏ kế hoạch.")
                    break

            log_wk(wk, "Hoàn thành kế hoạch! Chờ màn chơi tiếp theo...")

            # Đảo cửa vào cho màn tiếp theo
            if entry_side == 'LEFT':
                entry_side = 'RIGHT'
            elif entry_side == 'RIGHT':
                entry_side = 'LEFT'
            elif entry_side == 'UP':
                entry_side = 'DOWN'
            elif entry_side == 'DOWN':
                entry_side = 'UP'

            if not sleep_coop(wk, 5): return False  # Đợi 5 giây để game chuyển màn

    except Exception as e:
        log_wk(wk, f"Đã xảy ra lỗi nghiêm trọng trong flow game rắn: {e}")
        return False

    return True