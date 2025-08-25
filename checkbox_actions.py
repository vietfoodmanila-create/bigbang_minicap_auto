# checkbox_actions.py
# Phiên bản TÁI CẤU TRÚC, chỉ làm nhiệm vụ khởi động và dừng Worker.

from __future__ import annotations
from typing import Dict
from PySide6.QtWidgets import QCheckBox

from worker import Worker
import config


# Biến toàn cục để lưu trữ các worker đang chạy, key là device_id
_WORKERS: Dict[str, "Worker"] = {}


def _ui_log(ctrl, device_id: str, msg: str):
    """Gửi log ra giao diện chính một cách an toàn."""
    try:
        ctrl.w.log_msg(f"[{device_id}] {msg}")
    except Exception:
        print(f"[{device_id}] {msg}")

def _set_checkbox_state_silent(ctrl, row: int, checked: bool):
    """Cập nhật trạng thái checkbox mà không kích hoạt lại sự kiện toggled."""
    chk_container = ctrl.w.tbl_nox.cellWidget(row, 0)
    if chk_container and (chk := chk_container.findChild(QCheckBox)):
        try:
            chk.blockSignals(True)
            chk.setChecked(checked)
        finally:
            chk.blockSignals(False)


def on_checkbox_toggled(ctrl, device_id: str, checked: bool):
    """
    Được gọi khi người dùng tick/untick checkbox 'Start' trên giao diện.
    Đây là điểm khởi đầu của mọi hành động.
    """
    current_row = -1
    for r in range(ctrl.w.tbl_nox.rowCount()):
        item = ctrl.w.tbl_nox.item(r, 2)
        if item and item.text() == device_id:
            current_row = r
            break

    if checked:
        _ui_log(ctrl, device_id, "Nhận được yêu cầu bắt đầu auto...")

        accounts_selected = []
        for r in range(ctrl.w.tbl_acc.rowCount()):
            chk_widget = ctrl.w.tbl_acc.cellWidget(r, 0)
            checkbox = chk_widget.findChild(QCheckBox) if chk_widget else None
            if checkbox and checkbox.isChecked():
                accounts_selected.append(ctrl.w.online_accounts[r])

        if not accounts_selected:
            _ui_log(ctrl, device_id, "Lỗi: Vui lòng chọn ít nhất một tài khoản để chạy.")
            if current_row != -1:
                _set_checkbox_state_silent(ctrl, current_row, False)
            return

        if device_id in _WORKERS:
            _ui_log(ctrl, device_id, "Worker đã tồn tại, đang dừng worker cũ trước khi khởi động lại...")
            _WORKERS[device_id].stop()
            _WORKERS.pop(device_id, None)

        user_login_email = ctrl.w.cloud.load_token().email
        worker = Worker(ctrl, device_id, config.PLATFORM_TOOLS_ADB_PATH, ctrl.w.cloud, accounts_selected, user_login_email)

        if worker.start():
            _WORKERS[device_id] = worker
            _ui_log(ctrl, device_id, "Đã khởi động Worker thành công.")
        else:
            _ui_log(ctrl, device_id, "Lỗi: Không thể khởi động Worker. Vui lòng kiểm tra log chi tiết.")
            if current_row != -1:
                _set_checkbox_state_silent(ctrl, current_row, False)
    else:
        _ui_log(ctrl, device_id, "Nhận được yêu cầu dừng auto...")
        if device_id in _WORKERS:
            worker = _WORKERS.pop(device_id)
            worker.stop()
            _ui_log(ctrl, device_id, "Đã gửi yêu cầu dừng đến Worker.")
        else:
            _ui_log(ctrl, device_id, "Không tìm thấy Worker đang chạy để dừng.")