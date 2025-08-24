# checkbox_actions.py
# Phiên bản mới, đơn giản hóa để chỉ khởi động và dừng Worker.

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from PySide6.QtWidgets import QCheckBox, QMessageBox
from config import PLATFORM_TOOLS_ADB_PATH
from worker import Worker

# Biến toàn cục để lưu trữ các worker đang chạy
_WORKERS: Dict[str, "Worker"] = {}


# --- CÁC HÀM TIỆN ÍCH (SAO CHÉP TỪ PHIÊN BẢN CŨ) ---
def _ui_log(ctrl, device_id: str, msg: str):
    try:
        ctrl.w.log_msg(f"[{device_id}] {msg}")
    except Exception:
        print(f"[{device_id}] {msg}")


def _set_checkbox_state_silent(ctrl, row: int, checked: bool):
    chk_container = ctrl.w.tbl_nox.cellWidget(row, 0)
    if chk_container and (chk := chk_container.findChild(QCheckBox)):
        try:
            chk.blockSignals(True)
            chk.setChecked(checked)
        finally:
            chk.blockSignals(False)


# (Sao chép các hàm helper khác như _scan_eligible_accounts, _plan_online_blessings, v.v. vào đây nếu cần)

# --- HÀM CHÍNH ---
def on_checkbox_toggled(ctrl, device_id: str, checked: bool):
    """Được gọi khi người dùng tick/untick checkbox 'Start'."""

    if checked:
        # 1. Thu thập thông tin từ giao diện
        accounts_selected = []
        for r in range(ctrl.w.tbl_acc.rowCount()):
            chk_widget = ctrl.w.tbl_acc.cellWidget(r, 0)
            checkbox = chk_widget.findChild(QCheckBox) if chk_widget else None
            if checkbox and checkbox.isChecked():
                accounts_selected.append(ctrl.w.online_accounts[r])

        user_login_email = ctrl.w.cloud.load_token().email

        if not accounts_selected:
            _ui_log(ctrl, device_id, "Lỗi: Chưa chọn tài khoản nào để chạy.")
            _set_checkbox_state_silent(ctrl, ctrl.w.tbl_nox.currentRow(), False)
            return

        # 2. Dừng worker cũ nếu có (để khởi động lại với cấu hình mới)
        if device_id in _WORKERS:
            _WORKERS[device_id].stop()

        # 3. Tạo và khởi động worker mới
        worker = Worker(ctrl, device_id, PLATFORM_TOOLS_ADB_PATH, ctrl.w.cloud, accounts_selected, user_login_email)

        if worker.start():
            _WORKERS[device_id] = worker
            _ui_log(ctrl, device_id, "Bắt đầu auto với kiến trúc mới.")
        else:
            _ui_log(ctrl, device_id, "Lỗi: Không thể khởi động worker. Vui lòng kiểm tra log.")
            _set_checkbox_state_silent(ctrl, ctrl.w.tbl_nox.currentRow(), False)
    else:
        # 4. Dừng worker
        if device_id in _WORKERS:
            worker = _WORKERS.pop(device_id)
            worker.stop()
            _ui_log(ctrl, device_id, "Đã gửi yêu cầu dừng auto.")