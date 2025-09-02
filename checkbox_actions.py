# checkbox_actions.py
# (HOÀN CHỈNH) Đã online hóa hoàn toàn chức năng Chúc phúc.

from __future__ import annotations
import os
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QCheckBox, QMessageBox
from ui_main import MainWindow
# (SỬA ĐỔI) Import các biến config mới
from config import LDPLAYER_ADB_PATH,SCREEN_W, SCREEN_H
from flows_logout import logout_once
from flows_login import login_once
from flows_lien_minh import join_guild_once, ensure_guild_inside
from flows_thoat_lien_minh import run_guild_leave_flow
from flows_xay_dung_lien_minh import run_guild_build_flow
from flows_vien_chinh import run_guild_expedition_flow
from flows_chuc_phuc import run_bless_flow
from ui_auth import CloudClient
from utils_crypto import decrypt
from minicap_worker import MinicapWorker
from ui_main import MainWindow, BLESS_COL_CHECK, BLESS_COL_NAME

GAME_PKG = "com.phsgdbz.vn"
GAME_ACT = "com.phsgdbz.vn/org.cocos2dx.javascript.GameTwActivity"
_RUNNERS: Dict[str, "AccountRunner"] = {}  # Sửa: Key là device_id (str)


# ====== Tiện ích UI (SỬA ĐỔI) ======
def _table_row_for_device_id(ctrl, device_id: str) -> int:  # Sửa: Tìm theo device_id
    tv = ctrl.w.tbl_nox
    for r in range(tv.rowCount()):
        it = tv.item(r, 2)  # Cột 2 là Device ID
        if it and it.text().strip() == device_id:
            return r
    return -1


def _plan_online_blessings(
    accounts_selected: List[Dict],
    config: Dict,
    targets: List[Dict],
    accounts_already_running: List[str]
) -> Dict[str, List[Dict]]:
    """
    Lập kế hoạch Chúc phúc đúng semantics:
      - Server trả sẵn các target 'đến hạn' / 'chưa đủ trong chu kỳ' + 'cycle_count'.
      - Mỗi target cần thêm (per_run - cycle_count) tài khoản khác nhau trong CHU KỲ.
      - Một account không được chúc cùng target > 1 lần trong NGÀY.
      - Một account tối đa 20 lượt/ngày (tổng mọi target).
    Trả về: { email_account: [ {id, name}, ... ] }
    """
    def _normalize_emails(items) -> List[str]:
        res: List[str] = []
        for x in (items or []):
            if isinstance(x, dict):
                e = x.get('email') or x.get('game_email')
                if e: res.append(str(e))
            elif x:
                res.append(str(x))
        return res

    plan: Dict[str, List[Dict]] = {}
    per_run = int(config.get('per_run') or 0)
    if per_run <= 0 or not targets or not accounts_selected:
        return plan

    # Ưu tiên các account đã có nhiệm vụ build/expe
    priority = [e for e in accounts_already_running if e]
    others   = [a.get('game_email') for a in accounts_selected if a.get('game_email') and a.get('game_email') not in priority]
    email_order = priority + others

    # Tổng số lượt/ngày của từng email (trên mọi target)
    used_today: Dict[str, int] = {}
    for t in targets:
        for e in set(_normalize_emails(t.get('blessed_today_by'))):
            used_today[e] = used_today.get(e, 0) + 1

    # Phân bổ theo từng target
    for t in targets:
        try:
            tid = int(t.get('id'))
        except Exception:
            continue
        tname        = t.get('target_name') or t.get('name') or ""
        cycle_count  = int(t.get('cycle_count') or 0)
        need         = per_run - cycle_count
        if need <= 0:
            continue

        blessed_today = set(_normalize_emails(t.get('blessed_today_by')))

        for email in email_order:
            if need <= 0:
                break
            if not email:
                continue
            if email in blessed_today:
                continue
            if used_today.get(email, 0) >= 20:
                continue

            plan.setdefault(email, []).append({'id': tid, 'name': tname})
            used_today[email] = used_today.get(email, 0) + 1
            blessed_today.add(email)   # tránh gán trùng trong chính kế hoạch
            need -= 1

    return plan



def _get_ui_state(ctrl, row: int) -> str:
    it = ctrl.w.tbl_nox.item(row, 3)
    return it.text().strip().lower() if it else ""


def _set_checkbox_state_silent(ctrl, row: int, checked: bool):
    chk_container = ctrl.w.tbl_nox.cellWidget(row, 0)
    if chk_container and (chk := chk_container.findChild(QCheckBox)):
        try:
            chk.blockSignals(True)
            chk.setChecked(checked)
        finally:
            chk.blockSignals(False)


def _ui_log(ctrl, device_id: str, msg: str):  # Sửa: Nhận device_id
    try:
        ctrl.w.log_msg(f"[{device_id}] {msg}")
    except Exception:
        print(f"[{device_id}] {msg}")


# ====== Helpers: ngày/giờ & điều kiện (Giữ nguyên) ======
def _today_str_for_build() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now_dt_str_for_api() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_datetime_str(s: str | None) -> Optional[datetime]:
    if not s: return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        for fmt in ("%Y%m%d:%H%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt)
            except (ValueError, TypeError):
                continue
    return None


def _leave_cooldown_passed(last_leave_str: str | None, minutes: int = 61) -> bool:
    if not last_leave_str: return True
    last_leave_dt = _parse_datetime_str(last_leave_str)
    if not last_leave_dt: return True
    return (datetime.now() - last_leave_dt) >= timedelta(minutes=minutes)


def _expe_cooldown_passed(last_expe_str: str | None, hours: int = 12) -> bool:
    if not last_expe_str: return True
    last_expe_dt = _parse_datetime_str(last_expe_str)
    if not last_expe_dt: return True
    return (datetime.now() - last_expe_dt) >= timedelta(hours=hours)


def _scan_eligible_accounts(accounts_selected: List[Dict], features: dict) -> List[Dict]:
    eligible = []
    today = _today_str_for_build()
    for rec in accounts_selected:
        build_date = rec.get('last_build_date', '')
        last_leave = rec.get('last_leave_time', '')
        last_expe = rec.get('last_expedition_time', '')
        want_build = features.get("build", False)
        want_expe = features.get("expedition", False)
        cool_ok = _leave_cooldown_passed(last_leave)
        build_due = want_build and (build_date != today)
        expe_due = want_expe and _expe_cooldown_passed(last_expe)
        if (build_due and cool_ok) or (expe_due and cool_ok):
            eligible.append(rec)
    return eligible


# ====== Wrapper ADB cho flows_* (Đã sửa lỗi) ======
class SimpleNoxWorker:
    def __init__(self, adb_path: str, device_id: str, log_cb):  # Sửa: Nhận device_id
        self.device_id = device_id
        self._adb = adb_path
        self._serial = device_id  # Sử dụng device_id trực tiếp làm serial
        self.game_package = GAME_PKG;
        self.game_activity = GAME_ACT;
        self._log_cb = log_cb

    def _log(self, s: str):
        self._log_cb(f"{s}")

    def _run(self, args: List[str], timeout=8, text=True):
        import subprocess
        try:
            # Ẩn hoàn toàn cửa sổ tiến trình con trên Windows
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE
                if hasattr(subprocess, "CREATE_NO_WINDOW"):
                    creationflags = subprocess.CREATE_NO_WINDOW

            # Khi text=True thì trả str (UTF-8, bỏ lỗi); text=False trả bytes
            run_kwargs = dict(
                capture_output=True,
                timeout=timeout,
                startupinfo=startupinfo,
                creationflags=creationflags,
                stdin=subprocess.DEVNULL,  # không mở console để chờ input
            )
            if text:
                run_kwargs.update(text=True, encoding='utf-8', errors='ignore')
            else:
                run_kwargs.update(text=False)

            p = subprocess.run([self._adb, "-s", self._serial, *args], **run_kwargs)
            if text:
                return p.returncode, (p.stdout or ""), (p.stderr or "")
            else:
                # Nhánh này hiếm dùng vì hàm này mặc định text=True
                return p.returncode, (p.stdout or b""), (p.stderr or b"")
        except subprocess.TimeoutExpired:
            return (124, "" if text else b"", "timeout" if text else b"timeout")
        except Exception as e:
            return (125, "" if text else b"", (str(e) if text else str(e).encode()))

    def _run_raw(self, args: List[str], timeout=8):
        import subprocess
        try:
            # Ẩn hoàn toàn cửa sổ tiến trình con trên Windows
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE
                if hasattr(subprocess, "CREATE_NO_WINDOW"):
                    creationflags = subprocess.CREATE_NO_WINDOW

            p = subprocess.run(
                [self._adb, "-s", self._serial, *args],
                capture_output=True,
                timeout=timeout,
                startupinfo=startupinfo,
                creationflags=creationflags,
                stdin=subprocess.DEVNULL,  # không mở console để chờ input
            )
            return p.returncode, (p.stdout or b""), (p.stderr or b"")
        except subprocess.TimeoutExpired:
            return 124, b"", b"timeout"
        except Exception as e:
            return 125, b"", str(e).encode()

    def adb(self, *args, timeout=8):
        return self._run(list(args), timeout=timeout, text=True)

    def adb_bin(self, *args, timeout=8):
        return self._run_raw(list(args), timeout=timeout)

    def app_in_foreground(self, pkg: str) -> bool:
        code, out, _ = self.adb("shell", "cmd", "activity", "get-foreground-activity", timeout=6)
        if code == 0 and out and "ComponentInfo{" in out:
            comp = out.split("ComponentInfo{", 1)[1].split("}", 1)[0]
            return pkg in comp
        return False

    def start_app(self, package: str, activity: Optional[str] = None) -> bool:
        if activity:
            code, _, _ = self.adb("shell", "am", "start", "-n", activity, "-a", "android.intent.action.MAIN", "-c",
                                  "android.intent.category.LAUNCHER", timeout=10)
            if code == 0: return True
        code, _, _ = self.adb("shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1",
                              timeout=10)
        return code == 0

    def wait_app_ready(self, pkg: str, timeout_sec: int = 35) -> bool:
        end = time.time() + timeout_sec
        while time.time() < end:
            if self.app_in_foreground(pkg): return True
            time.sleep(1.0)
        return False


# ====== Runner theo port (Cập nhật logic vòng lặp) ======
class AccountRunner(QObject, threading.Thread):
    finished_run = Signal()

    def __init__(self, ctrl, device_id: str, adb_path: str, cloud: CloudClient, accounts_selected: List[Dict],
                 user_login_email: str):
        QObject.__init__(self)
        threading.Thread.__init__(self, name=f"AccountRunner-{device_id}", daemon=True)
        self.ctrl = ctrl
        self.device_id = device_id
        self.adb_path = adb_path
        self.cloud = cloud
        self.user_login_email = user_login_email
        self.master_account_list = list(accounts_selected)
        self._stop = threading.Event()
        self._last_log = None

        self.wk = SimpleNoxWorker(adb_path, device_id,
                                  log_cb=lambda s: _ui_log(ctrl, device_id, s))
        self.stop_evt = threading.Event()
        setattr(self.wk, "_abort", False)

        # --- MinicapWorker: tạo hòm thư ảnh cho flows ---
        try:
            import os
            use_minicap = os.environ.get("BB_MINICAP", "1") not in ("0", "false", "False")
            if use_minicap:
                mailbox = Path("frame_mailbox") / self.device_id.replace(":", "_")
                jpeg_q = int(os.environ.get("BB_MINICAP_Q", "100"))
                self.minicap = MinicapWorker(self.adb_path, self.device_id, mailbox,
                                             virt_size=(SCREEN_W, SCREEN_H), jpeg_quality=jpeg_q)
                self.minicap.start()

                def _fetcher():
                    return self.minicap.read_latest_frame()

                setattr(self.wk, "frame_fetcher", _fetcher)
                self.log("MinicapWorker đã khởi động, dùng mailbox ảnh thay cho screencap.")
            else:
                self.minicap = None
                self.log("BB_MINICAP=0 => dùng screencap ADB như logic gốc.")
        except Exception as _e:
            self.log(f"MinicapWorker khởi động thất bại: {_e}. Sẽ fallback screencap như cũ.")
            self.minicap = None

    def request_stop(self):
        self.stop_evt.set()
        self._stop.set()
        setattr(self.wk, "_abort", True)
        try:
            if getattr(self, "minicap", None):
                self.minicap.request_stop()
        except Exception:
            pass
        try:
            mc = getattr(self, "_stats_minicap", 0)
            sc = getattr(self, "_stats_screencap", 0)
            last_src = getattr(self, "_frame_source", "unknown")
            self.log(f"[FRAME] stats: minicap={mc}, screencap={sc}, last={last_src}")
        except Exception:
            pass

    def _sleep_coop(self, secs: float):
        end_time = time.time() + secs
        while time.time() < end_time:
            if self.stop_evt.is_set() or self._stop.is_set():
                return False
            time.sleep(min(1.0, end_time - time.time()))
        return True

    def log(self, s: str):
        if s != self._last_log:
            self._last_log = s
            _ui_log(self.ctrl, self.device_id, s)

    def _get_features(self) -> Dict[str, bool]:
        return dict(
            build=self.ctrl.w.chk_build.isChecked(),
            expedition=self.ctrl.w.chk_expedition.isChecked(),
            bless=self.ctrl.w.chk_bless.isChecked(),
            autoleave=self.ctrl.w.chk_auto_leave.isChecked(),
        )

    def run(self):
        self.log("Bắt đầu vòng lặp auto liên tục.")

        while not self._stop.is_set():
            try:
                # Bước 1: Cập nhật lại danh sách tài khoản từ server (LOGIC CŨ)
                try:
                    self.log("Đang làm mới danh sách tài khoản từ server...")
                    selected_ids = {acc.get('id') for acc in self.master_account_list}
                    all_accounts_fresh = self.cloud.get_game_accounts(status="ok")
                    # Server đã lọc status='ok'; client CHỈ lọc theo danh sách đã chọn
                    self.master_account_list = [
                        acc for acc in all_accounts_fresh if acc.get('id') in selected_ids
                    ]
                except Exception as e:
                    self.log(f"Lỗi làm mới danh sách tài khoản: {e}. Tạm nghỉ 1 phút.")
                    if not self._sleep_coop(60):
                        break
                    continue

                # Bước 2: Lập kế hoạch độc lập (giữ nguyên)
                features = self._get_features()
                eligible_for_build_expe = _scan_eligible_accounts(self.master_account_list, features)
                emails_for_build_expe = {acc.get('game_email') for acc in eligible_for_build_expe}

                bless_plan = {}
                if features.get("bless"):
                    self.log("Đang lập kế hoạch Chúc phúc từ dữ liệu server...")
                    try:
                        bless_config = self.cloud.get_blessing_config()
                        bless_targets = self.cloud.get_blessing_targets()

                        # Lọc danh sách target theo tick trong UI "DS Chúc phúc"
                        tvb = self.ctrl.w.tbl_bless
                        selected_target_names = set()
                        for r in range(tvb.rowCount()):
                            w = tvb.cellWidget(r, BLESS_COL_CHECK)
                            cb = w.findChild(QCheckBox) if w else None
                            if cb and cb.isChecked():
                                it = tvb.item(r, BLESS_COL_NAME)
                                if it:
                                    selected_target_names.add(it.text().strip())

                        if selected_target_names:
                            bless_targets = [
                                t for t in bless_targets
                                if (t.get("name") or t.get("target_name") or "").strip() in selected_target_names
                            ]

                        priority_emails = list(emails_for_build_expe)
                        bless_plan = _plan_online_blessings(
                            self.master_account_list, bless_config, bless_targets, priority_emails
                        )

                        if bless_plan:
                            self.log(f"Đã lập kế hoạch Chúc phúc cho {len(bless_plan)} tài khoản.")
                    except Exception as e:
                        self.log(f"Lỗi lập kế hoạch Chúc phúc: {type(e).__name__}: {e!r}")

                # Bước 3: Tổng hợp danh sách và kiểm tra (giữ nguyên)
                emails_for_bless = set(bless_plan.keys())
                all_emails_to_run = emails_for_build_expe.union(emails_for_bless)

                if not all_emails_to_run:
                    self.log("Không có tài khoản nào đủ điều kiện chạy. Tạm nghỉ 1 giờ...")
                    if not self._sleep_coop(3600):
                        break
                    continue

                accounts_to_run_this_loop = [
                    acc for acc in self.master_account_list
                    if acc.get('game_email') in all_emails_to_run
                ]

                # Ưu tiên account có cả build/expe & bless
                rec = None
                for acc in accounts_to_run_this_loop:
                    if acc.get('game_email') in emails_for_build_expe and acc.get('game_email') in emails_for_bless:
                        rec = acc
                        break
                if not rec:
                    rec = accounts_to_run_this_loop[0]

                self.log(
                    f"Tổng hợp: {len(accounts_to_run_this_loop)} tài khoản có nhiệm vụ. "
                    f"Bắt đầu xử lý: {rec.get('game_email')}"
                )

                # --- Thực thi tác vụ cho 1 tài khoản (giữ nguyên) ---
                account_id = rec.get('id')
                email = rec.get('game_email', '')
                encrypted_password = rec.get('game_password', '')
                server_id = int(rec.get('server_id', '0') or 0)

                # Lấy img_url server theo server_id → truyền thẳng cho flow
                resp = self.cloud.get(f"/api/servers?id={server_id}")
                img_url = (resp.get("data") or {}).get("img_url", "")
                server = img_url

                try:
                    password = decrypt(encrypted_password, self.user_login_email)
                except Exception as e:
                    self.log(f"⚠️ Lỗi giải mã mật khẩu cho {email}. Bỏ qua. Lỗi: {e}")
                    if not self._sleep_coop(10):
                        break
                    continue

                # Đưa game về trạng thái logout trước khi login
                if not logout_once(self.wk, max_rounds=7):
                    self.log("Logout thất bại, sẽ thử lại ở vòng lặp sau.")
                    continue

                # Gắn thông tin cho flows_login: cần cloud + uga_id
                uga_id = (rec.get('uga_id') or rec.get('user_game_account_id') or rec.get('id'))

                self.wk.uga_id = int(uga_id) if uga_id is not None else None
                self.wk.cloud = self.cloud

                # LOGIN (flows_login sẽ tự check 'sai mật khẩu' 2s và cập nhật bad_password nếu có)
                ok_login = login_once(self.wk, email, password, server, "")
                if not ok_login:
                    self.log(f"Login thất bại cho {email} → quay lại đầu vòng lặp để nạp DS mới.")
                    # QUAY ĐẦU VÒNG LẶP: lần kế tiếp sẽ get_game_accounts() nên acc vừa bad_password sẽ biến mất
                    if not self._sleep_coop(2.0):
                        break
                    continue

                did_build = False
                did_expe = False

                # Chúc phúc (giữ nguyên)
                if email in bless_plan:
                    targets_to_bless_info = bless_plan[email]
                    target_names = [t['name'] for t in targets_to_bless_info]
                    self.log(f"Tài khoản {email} có nhiệm vụ Chúc phúc cho: {', '.join(target_names)}")

                    blessed_ok_names = run_bless_flow(self.wk, target_names, log=self.log)
                    if blessed_ok_names:
                        for name in blessed_ok_names:
                            for target_info in targets_to_bless_info:
                                if target_info['name'] == name:
                                    try:
                                        self.cloud.record_blessing(target_info['id'], account_id)
                                        self.log("📝 [API] Đã ghi lại lịch sử Chúc phúc.")
                                    except Exception as e:
                                        err = None
                                        try:
                                            r = getattr(e, "response", None)
                                            if r is not None:
                                                j = r.json()
                                                err = j.get("error")
                                        except Exception:
                                            pass
                                        if err in ("cycle_quota_reached", "already_blessed_today",
                                                   "daily_quota_reached"):
                                            self.log(f"[API] Bỏ qua ghi lịch sử: {err}")
                                        else:
                                            self.log(f"[API] Lỗi ghi lịch sử: {e}")
                                    break

                # Build / Expedition (giữ nguyên)
                if email in emails_for_build_expe:
                    if (features.get("build") or features.get("expedition")) and _leave_cooldown_passed(
                            rec.get('last_leave_time')
                    ):
                        self.wk.ga_id = int(account_id)
                        join_guild_once(self.wk, log=self.log)

                    if features.get("build") and rec.get('last_build_date') != _today_str_for_build():
                        if ensure_guild_inside(self.wk, log=self.log) and run_guild_build_flow(self.wk, log=self.log):
                            did_build = True
                            self.cloud.update_game_account(account_id, {'last_build_date': _today_str_for_build()})
                            self.log("📝 [API] Cập nhật ngày xây dựng.")

                    if features.get("expedition") and _expe_cooldown_passed(rec.get('last_expedition_time')):
                        if ensure_guild_inside(self.wk, log=self.log) and run_guild_expedition_flow(self.wk,
                                                                                                    log=self.log):
                            did_expe = True
                            self.cloud.update_game_account(account_id, {'last_expedition_time': _now_dt_str_for_api()})
                            self.log("📝 [API] Cập nhật mốc viễn chinh.")

                # Auto leave (giữ nguyên)
                if features.get("autoleave") and (did_build or did_expe):
                    if run_guild_leave_flow(self.wk, log=self.log):
                        self.cloud.update_game_account(account_id, {'last_leave_time': _now_dt_str_for_api()})
                        self.log("📝 [API] Cập nhật mốc rời liên minh.")

                # Kết thúc lượt: thoát game như cũ
                logout_once(self.wk, max_rounds=7)

            except Exception as e:
                self.log(f"Lỗi nghiêm trọng trong vòng lặp: {e}. Tạm nghỉ 5 phút.")
                if not self._sleep_coop(300):
                    break

        self.log("Vòng lặp auto đã dừng theo yêu cầu.")
        self.finished_run.emit()

    def _auto_stop_and_uncheck(self):
        row = _table_row_for_device_id(self.ctrl, self.device_id)
        if row >= 0:
            _set_checkbox_state_silent(self.ctrl, row, False)
        self.request_stop()


# ====== API cho UI: gọi khi tick/untick ======
def on_checkbox_toggled(ctrl, port: int, checked: bool):  # Sửa: port không còn dùng, nhưng giữ signature
    row = ctrl.w.tbl_nox.currentRow()  # Lấy hàng đang được chọn
    if row < 0: return

    device_id_item = ctrl.w.tbl_nox.item(row, 2)
    if not device_id_item: return
    device_id = device_id_item.text()

    if checked:
        try:
            lic_status = ctrl.w.cloud.license_status()
            if not lic_status.get("valid"):
                msg = "License chưa kích hoạt hoặc đã hết hạn."
                QMessageBox.warning(ctrl.w, "Lỗi License", msg)
                _ui_log(ctrl, device_id, f"Không thể bắt đầu auto: {msg}")
                _set_checkbox_state_silent(ctrl, row, False);
                return
        except Exception as e:
            QMessageBox.critical(ctrl.w, "Lỗi kiểm tra License", f"Không thể xác thực license:\n{e}")
            _ui_log(ctrl, device_id, f"Không thể bắt đầu auto: Lỗi kiểm tra license.")
            _set_checkbox_state_silent(ctrl, row, False);
            return

        accounts_selected = []
        all_online_accounts = ctrl.w.online_accounts
        for r in range(ctrl.w.tbl_acc.rowCount()):
            chk_widget = ctrl.w.tbl_acc.cellWidget(r, 0)
            checkbox = chk_widget.findChild(QCheckBox) if chk_widget else None
            if checkbox and checkbox.isChecked():
                if r < len(all_online_accounts): accounts_selected.append(all_online_accounts[r])

        if not accounts_selected:
            _ui_log(ctrl, device_id, "Chưa có tài khoản nào được chọn để chạy.")
            _set_checkbox_state_silent(ctrl, row, False);
            return

        user_login_email = ctrl.w.cloud.load_token().email
        if not user_login_email:
            _ui_log(ctrl, device_id, "Lỗi: Không tìm thấy email người dùng.");
            return

        _ui_log(ctrl, device_id, f"Chuẩn bị chạy auto cho {len(accounts_selected)} tài khoản đã chọn.")

        # --- Logic mới để chọn ADB path (đã được đơn giản hóa) ---
        # Luôn sử dụng ADB của LDPlayer đã được định nghĩa trong config
        adb_path = str(LDPLAYER_ADB_PATH)
        _ui_log(ctrl, device_id, f"Sử dụng ADB của LDPlayer: {adb_path}")

        if not Path(adb_path).exists():
            msg = f"Lỗi: Không tìm thấy file ADB tại: {adb_path}"
            _ui_log(ctrl, device_id, msg)
            QMessageBox.critical(ctrl.w, "Lỗi Cấu hình", msg)
            _set_checkbox_state_silent(ctrl, row, False);
            return
        # --- Hết logic mới ---

        if (r := _RUNNERS.get(device_id)) and r.is_alive():
            _ui_log(ctrl, device_id, "Auto đang chạy.");
            return

        runner = AccountRunner(ctrl, device_id, adb_path, ctrl.w.cloud, accounts_selected, user_login_email)
        runner.finished_run.connect(lambda: _set_checkbox_state_silent(ctrl, row, False))

        _RUNNERS[device_id] = runner;
        runner.start();
        _ui_log(ctrl, device_id, "Bắt đầu auto.")

    else:
        if r := _RUNNERS.get(device_id): r.request_stop()
        _RUNNERS.pop(device_id, None)
        _ui_log(ctrl, device_id, "Đã gửi yêu cầu dừng auto.")
