import time
import logging


# 'worker' ở đây chính là instance của DeviceWorker được truyền vào
def run(worker):
    logging.info(f"--- Bắt đầu kịch bản ví dụ trên {worker.device_id} ---")

    # Chạy vòng lặp 10 lần
    for i in range(10):
        # Luôn kiểm tra cờ dừng
        if worker.stop_event.is_set():
            logging.info("Kịch bản nhận được yêu cầu dừng.")
            break

        logging.info(f"[{worker.device_id}] Vòng lặp nhiệm vụ {i + 1}/10")

        # Lấy ảnh màn hình (Rất nhanh vì ảnh đã được chụp sẵn)
        start_time = time.time()
        screen = worker.grab_screen_np()
        latency = (time.time() - start_time) * 1000

        if screen is not None:
            logging.info(
                f"[{worker.device_id}] Đã lấy ảnh màn hình. Kích thước: {screen.shape}. Độ trễ lấy/giải mã: {latency:.2f}ms")
        else:
            # grab_screen_np trả về None nếu có lỗi hoặc timeout
            logging.error(f"[{worker.device_id}] Không lấy được ảnh màn hình. Dừng kịch bản.")
            break

        # Tạm dừng giữa các hành động
        time.sleep(1.5)

    logging.info(f"--- Kết thúc kịch bản ví dụ trên {worker.device_id} ---")