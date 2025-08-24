# worker.py
# Bộ khung mới, ổn định cho việc chạy auto với Minicap. (Phiên bản hoàn thiện)

import threading
import time
from queue import Queue, Empty
from datetime import datetime, timedelta
import numpy as np

# Import các thành phần cần thiết từ dự án của bạn
from minicap_manager import MinicapManager
from module import log_wk
from flows_logout import logout_once
from flows_login import login_once
from flows_lien_minh import join_guild_once, ensure_guild_inside
from flows_thoat_lien_minh import run_guild_leave_flow
from flows_xay_dung_lien_minh import run_guild_build_flow
from flows_vien_chinh import run_guild_expedition_flow
from flows_chuc_phuc import run_bless_flow
from utils_crypto import decrypt


# <<< BỔ SUNG: Lớp SimpleNoxWorker để tương thích với các file flows_*.py
class SimpleNoxWorker:
    """Một lớp worker đơn giản để bao bọc các lệnh ADB và logging."""

    def __init__(self, adb_path, device_id, logger_func):
        self.adb_path = adb_path
        self.device_id = device_id
        self.log = logger_func
        self._abort = False

    def adb(self, *args, timeout=6):
        import subprocess
        cmd = [self.adb_path, "-s", self.device_id, *args]
        try_count = 3
        for i in range(try_count):
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding='utf-8',
                                   errors='ignore',
                                   creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess,
                                                                                        'CREATE_NO_WINDOW') else 0)
                if p.returncode == 0:
                    return p.returncode, p.stdout.strip(), p.stderr.strip()
            except subprocess.TimeoutExpired:
                if i == try_count - 1:
                    return -1, "", "Timeout"
            except Exception as e:
                return -1, "", f"ERR:{e}"
        return -1, "", "Failed after retries"


# <<< BỔ SUNG: Hàm _ui_log để nhất quán với checkbox_actions.py
def _ui_log(ctrl, device_id: str, msg: str):
    """Gửi log ra giao diện chính."""
    try:
        ctrl.w.log_msg(f"[{device_id}] {msg}")
    except Exception:
        print(f"[{device_id}] {msg}")


# <<< BỔ SUNG: Các hàm lập kế hoạch đã bị thiếu
def _scan_eligible_accounts(accounts: list, features: dict) -> list:
    """Quét và trả về danh sách các tài khoản đủ điều kiện chạy xây dựng/viễn chinh."""
    eligible = []
    now = datetime.now()
    check_build = features.get("build", False)
    check_expe = features.get("expe", False)

    for acc in accounts:
        try:
            last_build_str = acc.get("last_build")
            last_expe_str = acc.get("last_expe")
            is_eligible = False

            if check_build:
                if not last_build_str or (now - datetime.fromisoformat(last_build_str)) > timedelta(hours=8.1):
                    is_eligible = True

            if not is_eligible and check_expe:
                if not last_expe_str or (now - datetime.fromisoformat(last_expe_str)) > timedelta(hours=8.1):
                    is_eligible = True

            if is_eligible:
                eligible.append(acc)
        except Exception:
            # Lỗi parse thời gian, coi như đủ điều kiện
            eligible.append(acc)
    return eligible


def _plan_online_blessings(accounts: list, bless_config: dict, bless_targets: list, exclude_emails: list) -> dict:
    """Lập kế hoạch chúc phúc, trả về dict {email: [target_emails]}."""
    plan = {}
    if not bless_config.get("enabled") or not bless_targets:
        return {}

    online_accounts = [acc for acc in accounts if acc.get("game_email") not in exclude_emails]
    if not online_accounts:
        return {}

    num_targets_per_acc = bless_config.get("targets_per_blessing", 3)

    for i, acc in enumerate(online_accounts):
        email = acc.get("game_email")
        # Chọn các target xoay vòng
        start_index = (i * num_targets_per_acc) % len(bless_targets)
        targets_for_this_acc = [bless_targets[j % len(bless_targets)] for j in
                                range(start_index, start_index + num_targets_per_acc)]
        plan[email] = targets_for_this_acc

    return plan


class CaptureThread(threading.Thread):
    """Luồng chuyên dụng chỉ để lấy ảnh từ Minicap."""

    def __init__(self, minicap_manager, frame_queue, stop_event):
        super().__init__(daemon=True)
        self.minicap = minicap_manager
        self.frame_queue = frame_queue
        self.stop_event = stop_event

    def run(self):
        while not self.stop_event.is_set():
            frame = self.minicap.get_frame()
            if frame is not None:
                try:
                    self.frame_queue.get_nowait()
                except Empty:
                    pass
                self.frame_queue.put(frame)
            else:
                if not self.stop_event.is_set():
                    self.minicap.wk.log("Cảnh báo: Mất kết nối Minicap, đang thử kết nối lại...")
                    # Thử khởi động lại stream một cách an toàn
                    self.minicap.teardown()
                    self.minicap.start_stream()
                    time.sleep(2)


class AutoThread(threading.Thread):
    """Luồng chuyên dụng chỉ để chạy logic auto."""

    def __init__(self, worker_instance):
        super().__init__(daemon=True)
        self.w = worker_instance
        self.stop_event = worker_instance.stop_event
        self.wk = self.w.wk

    def run(self):
        """Đây là nơi logic của lớp AccountRunner cũ được chuyển vào."""
        self.w._sleep_coop(2)  # Chờ một chút để giao diện ổn định

        while not self.stop_event.is_set():
            try:
                self.w.log("Đang làm mới danh sách tài khoản từ server...")
                selected_ids = {acc.get('id') for acc in self.w.master_account_list}
                all_accounts_fresh = self.w.cloud.get_game_accounts()
                current_master_list = [acc for acc in all_accounts_fresh if acc.get('id') in selected_ids]

                if not current_master_list:
                    self.w.log("Không có tài khoản nào được chọn. Tạm nghỉ 10 phút.")
                    self.w._sleep_coop(600)
                    continue

                features = self.w._get_features()
                eligible_for_build_expe = _scan_eligible_accounts(current_master_list, features)
                emails_for_build_expe = {acc.get('game_email') for acc in eligible_for_build_expe}

                bless_plan = {}
                if features.get("bless"):
                    bless_config = self.w.cloud.get_blessing_config()
                    bless_targets = self.w.cloud.get_blessing_targets()
                    bless_plan = _plan_online_blessings(current_master_list, bless_config, bless_targets,
                                                        list(emails_for_build_expe))

                all_emails_to_run = emails_for_build_expe.union(set(bless_plan.keys()))
                if not all_emails_to_run:
                    self.w.log("Không có tài khoản nào đủ điều kiện. Tạm nghỉ 1 giờ...")
                    self.w._sleep_coop(3600)
                    continue

                accounts_to_run = sorted(
                    [acc for acc in current_master_list if acc.get('game_email') in all_emails_to_run],
                    key=lambda x: x.get('game_email'))
                if self.w.current_account_index >= len(accounts_to_run):
                    self.w.current_account_index = 0

                rec = accounts_to_run[self.w.current_account_index]
                self.w.current_account_index += 1

                email = rec.get('game_email')
                password = decrypt(rec.get("game_password_encrypted"), self.w.cloud.get_key())

                self.w.log(f"Bắt đầu xử lý tài khoản: {email}")

                # --- <<< BỔ SUNG: Logic thực thi tác vụ ---
                # 1. Đăng nhập
                login_ok = login_once(self.wk, email, password)
                if not login_ok:
                    self.w.log(f"Đăng nhập thất bại cho {email}, chuyển tài khoản tiếp theo.")
                    logout_once(self.wk)  # Cố gắng thoát ra để chuẩn bị cho lần sau
                    continue

                # 2. Thực hiện các tác vụ
                guild_name = self.w.cloud.get_guild_name_to_join()
                join_guild_once(self.wk, guild_name)

                if email in emails_for_build_expe:
                    if features.get("build"):
                        run_guild_build_flow(self.wk)
                        self.w.cloud.update_account_ts(rec.get("id"), "build")
                    if features.get("expe"):
                        run_guild_expedition_flow(self.wk)
                        self.w.cloud.update_account_ts(rec.get("id"), "expe")

                if email in bless_plan:
                    targets = bless_plan[email]
                    run_bless_flow(self.wk, targets)

                # 3. Đăng xuất
                self.w.log(f"Hoàn thành tác vụ cho {email}, đang đăng xuất.")
                logout_once(self.wk)
                self.w._sleep_coop(5)  # Nghỉ 5 giây giữa các tài khoản

            except Exception as e:
                import traceback
                self.w.log(f"Lỗi nghiêm trọng trong luồng auto: {e}\n{traceback.format_exc()}")
                self.w._sleep_coop(300)

    def stop(self):
        self.stop_event.set()
        setattr(self.wk, "_abort", True)


class Worker:
    """Lớp quản lý chính, điều phối các luồng."""

    def __init__(self, ctrl, device_id, adb_path, cloud, accounts, user_login_email):
        self.ctrl = ctrl
        self.device_id = device_id
        self.cloud = cloud
        self.master_account_list = list(accounts)
        self.user_login_email = user_login_email
        self.current_account_index = 0

        self.wk = SimpleNoxWorker(adb_path, device_id, self.log)
        self.minicap = MinicapManager(self.wk)

        self.frame_queue = Queue(maxsize=1)
        self.stop_event = threading.Event()

        self.capture_thread = None
        self.auto_thread = None

    def log(self, msg: str):
        _ui_log(self.ctrl, self.device_id, msg)

    def start(self):
        self.log("Worker đang khởi động...")
        if not self.minicap.setup() or not self.minicap.start_stream():
            self.log("KHỞI ĐỘNG MINICAP THẤT BẠI. Không thể bắt đầu auto.")
            self.minicap.teardown()
            return False

        setattr(self.wk, "grab_screen_np", self.get_latest_frame)
        setattr(self.wk, "_abort", False)

        self.capture_thread = CaptureThread(self.minicap, self.frame_queue, self.stop_event)
        self.auto_thread = AutoThread(self)

        self.capture_thread.start()
        self.auto_thread.start()

        self.log("Worker đã khởi động thành công.")
        return True

    def stop(self):
        self.log("Đang gửi yêu cầu dừng đến các luồng...")
        self.stop_event.set()

        if self.auto_thread:
            setattr(self.wk, "_abort", True)
            self.auto_thread.join(timeout=5)
        if self.capture_thread:
            self.capture_thread.join(timeout=5)

        self.minicap.teardown()
        self.log("Worker đã dừng hoàn toàn.")

    def get_latest_frame(self, wk_instance=None) -> np.ndarray | None:
        try:
            return self.frame_queue.get(timeout=5.0)  # Chờ tối đa 5s để có ảnh mới
        except Empty:
            self.log("Cảnh báo: Không nhận được frame mới từ CaptureThread trong 5 giây.")
            return None

    def _get_features(self):
        return self.ctrl.w.get_features()  # Lấy features từ MainWindow

    def _sleep_coop(self, secs):
        end_time = time.time() + secs
        while time.time() < end_time:
            if self.stop_event.is_set(): return False
            time.sleep(min(1.0, end_time - time.time()))
        return True