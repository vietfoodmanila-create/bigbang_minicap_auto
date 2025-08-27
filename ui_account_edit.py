from __future__ import annotations
from typing import Callable, Optional, Dict, Any, List

from PySide6 import QtCore, QtWidgets
from utils_crypto import encrypt

class EditGameAccountDialog(QtWidgets.QDialog):
    """
    Sửa tài khoản game theo 4 trường hợp:
      - Đổi server (không cần đăng nhập lại)
      - Đổi mật khẩu (đăng nhập web, app tự bắt) — phải khớp email tài khoản
      - Cả hai
      - Không thay đổi gì => nút Lưu bị disable

    Tham số:
      - cloud: CloudClient (đang đăng nhập)
      - account: dict { id, game_email, server | server_name | server_id? ... }
      - login_opener: callable(parent) -> dict { ok:bool, email:str|None, password:str|None, message:str }
        Hãy truyền vào hàm login web đang dùng khi “Thêm tài khoản” để tái sử dụng.
    """
    def __init__(self, cloud, account: dict,
                 login_opener: Callable[[QtWidgets.QWidget], Dict[str, Any]],
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        real_parent = parent if isinstance(parent, QtWidgets.QWidget) else None
        super().__init__(real_parent, QtCore.Qt.WindowType.Dialog)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        self.setWindowTitle("Sửa tài khoản game")

        self.cloud = cloud
        self.account = account
        self.login_opener = login_opener

        self._servers: List[dict] = []
        self._server_id_by_index: Dict[int, Optional[int]] = {}

        # State đăng nhập lại (nếu có)
        self._relogin_ok = False
        self._relogin_email: Optional[str] = None
        self._relogin_password: Optional[str] = None

        self._build_ui()
        QtCore.QTimer.singleShot(0, self._init_after_show)

    def _build_ui(self) -> None:
        lay = QtWidgets.QVBoxLayout(self)

        # Hướng dẫn
        hint = QtWidgets.QLabel(
            "Hướng dẫn:\n"
            "• Nếu cần sửa server: hãy chọn server mới rồi bấm Xác nhận.\n"
            "• Nếu mật khẩu thay đổi: hãy Đăng nhập lại tài khoản để xác thực mật khẩu mới."
        )
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # Email (readonly)
        form = QtWidgets.QFormLayout()
        self.leEmail = QtWidgets.QLineEdit(self.account.get("game_email", ""))
        self.leEmail.setReadOnly(True)
        form.addRow("Email:", self.leEmail)

        # Server combobox
        self.cboServer = QtWidgets.QComboBox()
        form.addRow("Server:", self.cboServer)
        lay.addLayout(form)

        # Khu đăng nhập lại (web)
        grp = QtWidgets.QGroupBox("Đăng nhập lại để đổi mật khẩu (tùy chọn)")
        vgrp = QtWidgets.QVBoxLayout(grp)

        self.lblReloginStatus = QtWidgets.QLabel("Chưa đăng nhập lại")
        self.btnRelogin = QtWidgets.QPushButton("Mở trang đăng nhập game…")
        self.btnRelogin.clicked.connect(self._on_relogin)

        vgrp.addWidget(self.lblReloginStatus)
        vgrp.addWidget(self.btnRelogin)
        lay.addWidget(grp)

        # Nút hành động
        h = QtWidgets.QHBoxLayout()
        h.addStretch(1)
        self.btnSave = QtWidgets.QPushButton("Xác nhận")
        self.btnCancel = QtWidgets.QPushButton("Hủy")
        self.btnSave.setEnabled(False)  # mặc định disable
        self.btnCancel.clicked.connect(self.reject)
        self.btnSave.clicked.connect(self._on_save)
        h.addWidget(self.btnSave)
        h.addWidget(self.btnCancel)
        lay.addLayout(h)

        # Theo dõi thay đổi combobox để bật/tắt nút Lưu
        self.cboServer.currentIndexChanged.connect(self._recompute_save_enabled)

        self.resize(480, 260)

    def _init_after_show(self) -> None:
        # Yêu cầu đang đăng nhập Cloud (token & license)
        td = self.cloud.load_token() if hasattr(self.cloud, "load_token") else None
        if not td or not getattr(td, "token", None):
            QtWidgets.QMessageBox.critical(self, "Chưa đăng nhập",
                                           "Vui lòng đăng nhập Cloud/License trước khi sửa tài khoản.")
            self.reject()
            return

        # Tải danh sách server
        try:
            servers = self.cloud.get_servers()  # [{id, name, img_url}, ...] hoặc legacy không có id
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Lỗi tải server", f"Không thể tải danh sách server:\n{e}")
            servers = []

        self._servers = servers or []
        self.cboServer.clear()
        self._server_id_by_index.clear()
        for idx, s in enumerate(self._servers):
            name = str(s.get("name", ""))
            sid = s.get("id")  # có thể None nếu backend chưa có id
            self.cboServer.addItem(name)
            self._server_id_by_index[idx] = sid

        # Chọn server hiện tại
        current_name = self.account.get("server_name") or self.account.get("server")
        if current_name:
            for i in range(self.cboServer.count()):
                if self.cboServer.itemText(i) == str(current_name):
                    self.cboServer.setCurrentIndex(i)
                    break

        self._recompute_save_enabled()

    # ==== Logic enable/disable nút Lưu theo 4 trường hợp ====
    def _server_changed(self) -> bool:
        old_name = str(self.account.get("server_name") or self.account.get("server") or "")
        new_name = str(self.cboServer.currentText() or "")
        return new_name != "" and new_name != old_name

    def _recompute_save_enabled(self) -> None:
        enable = self._server_changed() or self._relogin_ok
        self.btnSave.setEnabled(bool(enable))

    # ==== Đăng nhập lại (mở web, app tự bắt) ====
    def _on_relogin(self) -> None:
        try:
            res = self.login_opener(self)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Lỗi đăng nhập", f"Không mở được trang đăng nhập:\n{e}")
            return

        ok = bool(res.get("ok"))
        email = res.get("email") or ""
        password = res.get("password") or ""
        msg = res.get("message") or ""

        if not ok:
            self._relogin_ok = False
            self._relogin_email = None
            self._relogin_password = None
            self.lblReloginStatus.setText(f"Đăng nhập thất bại: {msg or 'Người dùng hủy hoặc lỗi.'}")
            self._recompute_save_enabled()
            return

        # Kiểm tra đúng email tài khoản đang sửa
        acc_email = (self.account.get("game_email") or "").strip().lower()
        if email.strip().lower() != acc_email:
            self._relogin_ok = False
            self._relogin_email = None
            self._relogin_password = None
            QtWidgets.QMessageBox.critical(
                self, "Sai tài khoản",
                "Bạn vừa đăng nhập một tài khoản khác. Vui lòng đăng nhập đúng tài khoản đang sửa."
            )
            self.lblReloginStatus.setText("Chưa đăng nhập lại")
            self._recompute_save_enabled()
            return

        # OK: đã đăng nhập đúng tài khoản
        self._relogin_ok = True
        self._relogin_email = email
        self._relogin_password = password
        self.lblReloginStatus.setText(f"Đã đăng nhập: {email}")
        self._recompute_save_enabled()

    # ==== Lưu ====
    def _on_save(self) -> None:
        payload: Dict[str, Any] = {}

        # 1) Đổi server?
        if self._server_changed():
            idx = self.cboServer.currentIndex()
            new_name = self.cboServer.currentText()
            new_sid = self._server_id_by_index.get(idx)
            if new_sid is not None:
                payload["server_id"] = int(new_sid)
            else:
                payload["server"] = new_name  # legacy fallback

        # 2) Đổi mật khẩu?
        if self._relogin_ok and self._relogin_email and self._relogin_password:
            try:
                # Mã hóa giống luồng Thêm tài khoản (key theo email đăng nhập Cloud)
                user_login_email = self.cloud.load_token().email
                encrypted = encrypt(self._relogin_password, user_login_email)
                payload["game_password"] = encrypted
                # Gửi luôn game_email để backend dễ verify log (không bắt buộc)
                payload["game_email"] = self._relogin_email
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Lỗi mã hóa", f"Không thể mã hóa mật khẩu:\n{e}")
                return

        if not payload:
            # Không có thay đổi -> không nên tới đây vì nút đã disable
            self.reject()
            return

        # 3) Gọi API cập nhật
        try:
            acc_id = int(self.account.get("id"))
            self.cloud.update_game_account(acc_id, payload)
            self.accept()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Lỗi cập nhật", f"Không thể cập nhật tài khoản:\n{e}")
