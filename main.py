import logging
import time
from worker import DeviceWorker
import adb_utils
import os

# Cấu hình logging
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')


def main():
    logging.info("Bắt đầu chương trình Automation (Kiến trúc mới).")

    # Kiểm tra sự tồn tại của ADB đã cấu hình
    if not os.path.exists(adb_utils.ADB_EXECUTABLE):
        logging.error(f"Dừng chương trình: Không tìm thấy ADB tại {adb_utils.ADB_EXECUTABLE}")
        return

    print("\nLƯU Ý: Đảm bảo Minicap binaries (/data/local/tmp/minicap và minicap.so) đã được cài đặt trên thiết bị.\n")

    # Lấy danh sách thiết bị (sử dụng logic trong adb_utils)
    devices = adb_utils.get_device_list()
    if not devices:
        logging.error("Không tìm thấy thiết bị nào được kết nối. Vui lòng kiểm tra kết nối và cấu hình giả lập.")
        return

    logging.info(f"Tìm thấy {len(devices)} thiết bị: {devices}")

    workers = []
    base_port = 1717  # Cổng local bắt đầu cho Minicap

    # CẤU HÌNH QUAN TRỌNG:
    # Nếu flows cũ của bạn phụ thuộc vào kích thước cố định trong config.py (900x1600), đặt RESIZE = True.
    # Nếu flows cũ của bạn sử dụng độ phân giải thực tế của thiết bị, đặt RESIZE = False.
    RESIZE = False

    # Khởi động Worker cho từng thiết bị
    for i, device_id in enumerate(devices):
        port = base_port + i
        worker = DeviceWorker(device_id, minicap_port=port, resize_to_config=RESIZE)
        worker.start()
        workers.append(worker)
        # Khởi động tuần tự
        time.sleep(1)

        # Chờ cho đến khi tất cả các worker hoàn thành công việc hoặc bị ngắt
    try:
        while True:
            all_done = True
            for w in workers:
                # Nếu luồng auto đang chạy, chúng ta chưa xong
                if w.auto_thread and w.auto_thread.is_alive():
                    all_done = False
                    break
                # Nếu luồng auto chưa khởi động và cũng chưa có lệnh dừng
                if w.auto_thread is None and not w.stop_event.is_set():
                    all_done = False
                    break

            if all_done:
                logging.info("Tất cả các worker đã hoàn thành công việc hoặc dừng lại.")
                break

            time.sleep(2)
    except KeyboardInterrupt:
        logging.info("Nhận được tín hiệu ngắt (Ctrl+C). Đang dừng tất cả các worker...")
        # Ra lệnh dừng cho tất cả
        for worker in workers:
            worker.stop()

    # Đảm bảo tất cả worker đã được dọn dẹp hoàn toàn
    for worker in workers:
        worker.stop()

    logging.info("Chương trình kết thúc.")


if __name__ == "__main__":
    # Yêu cầu cài đặt: pip install opencv-python numpy
    main()