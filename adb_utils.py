import subprocess
import logging
import time
import re
import platform
import os

# Import file config của bạn
try:
    import config
except ImportError:
    logging.error("KHÔNG TÌM THẤY FILE config.py.")
    config = type('Config', (object,), {'ADB_PATH': 'adb'})  # Fallback

# Cấu hình logging cơ bản
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')

# Sử dụng đường dẫn ADB từ file config (ví dụ: vendor/adb.exe)
ADB_EXECUTABLE = config.ADB_PATH

# Kiểm tra sự tồn tại của file ADB ngay khi import
if not os.path.exists(ADB_EXECUTABLE):
    logging.error(
        f"LỖI: Không tìm thấy file ADB tại đường dẫn đã cấu hình: {ADB_EXECUTABLE}. Kiểm tra thư mục vendor/.")
else:
    # Chỉ in log này nếu file tồn tại để tránh trùng lặp với log từ config.py
    pass
    # logging.info(f"Sử dụng ADB từ: {ADB_EXECUTABLE}")


def run_adb_command(device_id, command_list):
    """Chạy một lệnh adb cụ thể, sử dụng ADB đã cấu hình."""

    cmd = [ADB_EXECUTABLE]
    if device_id:
        cmd.extend(["-s", device_id])
    cmd.extend(command_list)

    try:
        # Ẩn cửa sổ console trên Windows (rất quan trọng khi dùng adb.exe bundled)
        creationflags = 0
        if platform.system() == "Windows":
            if hasattr(subprocess, 'CREATE_NO_WINDOW'):
                creationflags = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30,
                                creationflags=creationflags)
        return result.stdout.strip()

    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip()

        # CẬP NHẬT: Bỏ qua lỗi "listener not found" khi chạy forward --remove
        if command_list[0] == "forward" and command_list[1] == "--remove":
            if "listener" in stderr and "not found" in stderr:
                # Đây là lỗi không nghiêm trọng, có nghĩa là cổng chưa được forward trước đó.
                return None

        # pgrep/pidof thường trả về 1 nếu không tìm thấy tiến trình.
        if "pgrep" in command_list or "pidof" in command_list:
            return None

        # Xử lý trường hợp ADB daemon chưa chạy (thường gặp khi chạy lần đầu với ADB bundled)
        if "daemon not running" in stderr or "daemon started successfully" in stderr:
            logging.warning("ADB daemon có dấu hiệu chưa ổn định. Đang chờ và thử lại...")
            # Thường thì ADB tự khởi động, chúng ta chỉ cần chờ một chút và thử lại lệnh
            time.sleep(3)
            try:
                # Thử chạy lại lệnh ban đầu một lần nữa
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30,
                                        creationflags=creationflags)
                return result.stdout.strip()
            except subprocess.CalledProcessError as retry_e:
                logging.error(f"[{device_id}] Lệnh ADB thất bại sau khi chờ daemon: {retry_e.stderr.strip()}")
                return None

        if "unauthorized" in stderr or "offline" in stderr:
            logging.warning(f"[{device_id}] Thiết bị không được ủy quyền hoặc đang offline.")
        elif stderr:
            logging.warning(f"[{device_id}] Lệnh ADB thất bại: Lỗi: {stderr}")
        return None

    except FileNotFoundError:
        logging.error(f"Lỗi FileNotFoundError. Không tìm thấy file thực thi ADB tại: {ADB_EXECUTABLE}")
        return None
    except subprocess.TimeoutExpired:
        logging.error(f"[{device_id}] Lệnh ADB bị timeout: {' '.join(cmd)}")
        return None
    except Exception as e:
        logging.error(f"[{device_id}] Lỗi không xác định khi chạy lệnh ADB: {e}")
        return None


# --- Các hàm tiện ích giữ nguyên logic cũ ---
# (Phần còn lại của file adb_utils.py giữ nguyên như phiên bản trước)

def tap(device_id, x, y):
    run_adb_command(device_id, ["shell", "input", "tap", str(x), str(y)])


def swipe(device_id, x1, y1, x2, y2, duration=300):
    run_adb_command(device_id, ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration)])


def forward_port(device_id, local_port, remote_abstract_name="minicap"):
    return run_adb_command(device_id, ["forward", f"tcp:{local_port}", f"localabstract:{remote_abstract_name}"])


def remove_forward(device_id, local_port):
    run_adb_command(device_id, ["forward", "--remove", f"tcp:{local_port}"])


def get_resolution(device_id):
    # Lấy độ phân giải thực tế của thiết bị để cấu hình Minicap
    output = run_adb_command(device_id, ["shell", "wm", "size"])
    if output:
        match = re.search(r'(?:Physical|Override) size: (\d+)x(\d+)', output)
        if match:
            return int(match.group(1)), int(match.group(2))
    logging.error(f"[{device_id}] Không thể xác định độ phân giải màn hình từ output: {output}")
    return None, None


def start_minicap(device_id):
    """Khởi động Minicap trên thiết bị."""
    width, height = get_resolution(device_id)
    if not width:
        return None

    # Cấu hình Minicap sử dụng độ phân giải thực tế
    command = f"LD_LIBRARY_PATH=/data/local/tmp /data/local/tmp/minicap -P {width}x{height}@{width}x{height}/0"

    try:
        cmd = [ADB_EXECUTABLE, "-s", device_id, "shell", command]

        # Sử dụng Popen để chạy nền và ẩn cửa sổ console
        creationflags = 0
        if platform.system() == "Windows":
            if hasattr(subprocess, 'CREATE_NO_WINDOW'):
                creationflags = subprocess.CREATE_NO_WINDOW

        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=creationflags)
        logging.info(f"[{device_id}] Đang khởi động dịch vụ Minicap ({width}x{height})...")

        # Chờ và kiểm tra
        time.sleep(1.5)
        if process.poll() is not None:
            logging.error(
                f"[{device_id}] Dịch vụ Minicap không thể khởi động. Kiểm tra binaries/permissions tại /data/local/tmp.")
            return None

        return process
    except Exception as e:
        logging.error(f"[{device_id}] Lỗi khi khởi động Popen cho Minicap: {e}")
        return None


def stop_minicap(device_id):
    """Dừng tiến trình Minicap trên thiết bị."""
    try:
        # Sử dụng pgrep hoặc pidof để tìm PID
        result = run_adb_command(device_id, ["shell", "pgrep", "minicap"])
        if not result:
            result = run_adb_command(device_id, ["shell", "pidof", "minicap"])

        if result:
            pids = result.strip().split()
            valid_pids = [pid for pid in pids if pid.isdigit()]

            if valid_pids:
                logging.info(f"[{device_id}] Tìm thấy tiến trình Minicap (PIDs: {valid_pids}). Đang dừng...")
                run_adb_command(device_id, ["shell", "kill", "-9"] + valid_pids)

    except Exception as e:
        logging.warning(f"[{device_id}] Lỗi không mong muốn khi cố gắng dừng Minicap: {e}")


def get_device_list():
    """Lấy danh sách các thiết bị đang kết nối."""
    output = run_adb_command(None, ["devices"])

    if output is None:
        return []

    devices = []
    if output:
        # Bắt đầu từ dòng thứ 2 (sau "List of devices attached")
        for line in output.splitlines()[1:]:
            line = line.strip()
            if line and "\tdevice" in line:
                devices.append(line.split("\t")[0])
    return devices