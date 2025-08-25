import time
import logging

logger = logging.getLogger(__name__)


# Hàm này sẽ được truyền vào Worker khi khởi động
def run_automation_logic(runner):
    """
    Logic auto chính.
    runner: Đối tượng AutoThread cung cấp các hàm API (grab_screen_np, tap, wait_and_click...)
    """
    logger.info("--- Starting Automation Logic (Example Flow) ---")

    # Ví dụ: Chạy 30 giây để kiểm tra hệ thống
    start_time = time.time()

    # Kiểm tra runner.running để cho phép dừng luồng một cách an toàn
    while runner.running and (time.time() - start_time < 30):

        # 1. Lấy ảnh màn hình (gần như tức thì)
        loop_start = time.time()
        screen = runner.grab_screen_np()

        if screen is not None:
            h, w = screen.shape[:2]

            # 2. Xử lý logic (Ví dụ: Tìm kiếm và nhấn)
            # Giả sử bạn có file 'templates/start_button.png'
            # if runner.wait_and_click('start_button.png', timeout=2):
            #     logger.info("Clicked start button.")
            # else:
            #     logger.info("Start button not found, tapping center screen.")
            #     runner.tap(w//2, h//2)

            loop_duration = time.time() - loop_start
            logger.info(f"Screen captured: {w}x{h}. Logic loop time: {loop_duration * 1000:.2f} ms")

        # Tạm dừng giữa các bước logic
        time.sleep(1)

    logger.info("--- Automation Logic Finished ---")