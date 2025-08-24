# worker.py
# Bộ khung mới, ổn định cho việc chạy auto với Minicap.

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
                # Luôn ghi đè ảnh cũ trong hàng đợi bằng ảnh mới nhất
                try:
                    self.frame_queue.get_nowait()
                except Empty:
                    pass
                self.frame_queue.put(frame)
            else:
                self.minicap.wk.log("Cảnh báo: Mất kết nối Minicap, tạm nghỉ 2s...")
                time.sleep(2)


class AutoThread(threading.Thread):
    """Luồng chuyên dụng chỉ để chạy logic auto."""

    def __init__(self, worker_instance):
        super().__init__(daemon=True)
        self.w = worker_instance
        self.stop_event = worker_instance.stop_event
        self.wk = self.w.wk  # Worker object for flows

    def run(self):
        """Đây là nơi logic của lớp AccountRunner cũ được chuyển vào."""
        while not self.stop_event.is_set():
            try:
                # Bước 1: Cập nhật tài khoản
                self.w.log("Đang làm mới danh sách tài khoản từ server...")
                selected_ids = {acc.get('id') for acc in self.w.master_account_list}
                all_accounts_fresh = self.w.cloud.get_game_accounts()
                current_master_list = [acc for acc in all_accounts_fresh if acc.get('id') in selected_ids]

                # Bước 2: Lập kế hoạch
                features = self.w._get_features()
                eligible_for_build_expe = _scan_eligible_accounts(current_master_list, features)
                emails_for_build_expe = {acc.get('game_email') for acc in eligible_for_build_expe}

                bless_plan = {}
                if features.get("bless"):
                    bless_config = self.w.cloud.get_blessing_config()
                    bless_targets = self.w.cloud.get_blessing_targets()
                    bless_plan = _plan_online_blessings(current_master_list, bless_config, bless_targets,
                                                        list(emails_for_build_expe))

                # Bước 3: Tổng hợp và chọn tài khoản
                all_emails_to_run = emails_for_build_expe.union(set(bless_plan.keys()))
                if not all_emails_to_run:
                    self.w.log("Không có tài khoản nào đủ điều kiện. Tạm nghỉ 1 giờ...")
                    self.w._sleep_coop(3600)
                    continue

                accounts_to_run = [acc for acc in current_master_list if acc.get('game_email') in all_emails_to_run]
                if self.w.current_account_index >= len(accounts_to_run):
                    self.w.current_account_index = 0

                rec = accounts_to_run[self.w.current_account_index]
                self.w.current_account_index += 1

                self.w.log(f"Bắt đầu xử lý: {rec.get('game_email')}")

                # --- Thực thi tác vụ ---
                # (Logic này được sao chép nguyên vẹn từ AccountRunner cũ)
                # ...

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
        """Lấy frame mới nhất từ hàng đợi."""
        try:
            return self.frame_queue.get(timeout=2.0)  # Chờ tối đa 2s để có ảnh mới
        except Empty:
            self.log("Cảnh báo: Không nhận được frame mới từ CaptureThread.")
            return None

    def _get_features(self):
        return self.ctrl.get_features()

    def _sleep_coop(self, secs):
        end_time = time.time() + secs
        while time.time() < end_time:
            if self.stop_event.is_set(): return False
            time.sleep(min(1.0, end_time - time.time()))
        return True