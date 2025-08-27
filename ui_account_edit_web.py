from __future__ import annotations
from typing import Dict, Any, Optional, List

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from utils_crypto import encrypt


class EditGameAccountWebDialog(QtWidgets.QDialog):
    """
    Sửa tài khoản game bằng WebView + chọn server.
    Nút 'Xác nhận' chỉ sáng khi:
      - Đổi server, hoặc
      - Đăng nhập web thành công (để đổi mật khẩu), hoặc
      - Cả hai.
    """

    LOGIN_URL = "https://pay.bigbangthoikhong.vn/login?game_id=105"
    SUCCESS_PATH = "/rechargePackage"

    def __init__(self, cloud, account: dict, parent: Optional[QtWidgets.QWidget] = None):
        real_parent = parent if isinstance(parent, QtWidgets.QWidget) else None
        super().__init__(real_parent, QtCore.Qt.WindowType.Dialog)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        self.setWindowTitle("Xác minh đăng nhập (Web) & chọn Server")

        self.cloud = cloud
        self.account = account

        self._servers: List[dict] = []
        self._server_id_by_index: Dict[int, Optional[int]] = {}
        self._login_ok = False
        self._captured_email: Optional[str] = None
        self._captured_password: Optional[str] = None

        self._build_ui()
        QtCore.QTimer.singleShot(0, self._after_show)

    # ---------- UI ----------
    def _build_ui(self) -> None:
        main = QtWidgets.QVBoxLayout(self)

        # Hướng dẫn
        self.lblGuide = QtWidgets.QLabel(
            "Hướng dẫn:\n"
            "• Nếu cần sửa server: hãy chọn server mới rồi bấm Xác nhận.\n"
            "• Nếu mật khẩu thay đổi: hãy đăng nhập lại tài khoản trong khung bên dưới.\n"
            "• Chỉ khi trang chuyển đến mục nạp, hệ thống mới coi là đăng nhập thành công."
        )
        self.lblGuide.setWordWrap(True)
        main.addWidget(self.lblGuide)

        # Chọn server
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Chọn server:"))
        self.cboServer = QtWidgets.QComboBox()
        self.cboServer.currentIndexChanged.connect(self._recompute_save_enabled)
        top.addWidget(self.cboServer, 1)
        main.addLayout(top)

        # WebView
        self.web = QWebEngineView(self)
        self.web.urlChanged.connect(self._on_url_changed)
        self.web.loadFinished.connect(self._on_load_finished)
        main.addWidget(self.web, 1)

        # Status
        self.lblStatus = QtWidgets.QLabel("Đang khởi tạo…")
        self.lblStatus.setStyleSheet("color:#666;")
        main.addWidget(self.lblStatus)

        # Buttons
        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        self.btnCancel = QtWidgets.QPushButton("Hủy")
        self.btnSave = QtWidgets.QPushButton("Xác nhận")
        self.btnSave.setEnabled(False)
        self.btnCancel.clicked.connect(self.reject)
        self.btnSave.clicked.connect(self._on_save)
        btns.addWidget(self.btnCancel)
        btns.addWidget(self.btnSave)
        main.addLayout(btns)

        self.resize(980, 620)

    # ---------- After show ----------
    def _after_show(self) -> None:
        # Luôn mở trang login; không kiểm tra token/license ở client
        self.web.setUrl(QUrl(self.LOGIN_URL))
        self.lblStatus.setText("Đang mở trang đăng nhập…")

        # Thử nạp danh sách server từ API; nếu lỗi thì fallback server hiện tại
        self._load_servers_into_combo()

    def _load_servers_into_combo(self) -> None:
        current_name = str(self.account.get("server_name") or self.account.get("server") or "")
        self.cboServer.clear()
        self._server_id_by_index.clear()

        try:
            servers = self.cloud.get_servers()
        except Exception as e:
            # Fallback: chỉ hiển thị server hiện tại để người dùng vẫn có thể đổi mật khẩu
            if current_name:
                self.cboServer.addItem(current_name)
            self.lblStatus.setText(f"Không thể tải danh sách server (API sẽ kiểm tra quyền): {e}")
            self._recompute_save_enabled()
            return

        self._servers = servers or []
        for idx, s in enumerate(self._servers):
            name = str(s.get("name", ""))
            sid = s.get("id")  # có thể None nếu backend chưa có bảng servers
            self.cboServer.addItem(name)
            self._server_id_by_index[idx] = sid

        # Chọn sẵn server hiện tại
        if current_name:
            for i in range(self.cboServer.count()):
                if self.cboServer.itemText(i) == current_name:
                    self.cboServer.setCurrentIndex(i)
                    break

        self._recompute_save_enabled()

    # ---------- Helpers ----------
    def _server_changed(self) -> bool:
        old_name = str(self.account.get("server_name") or self.account.get("server") or "")
        new_name = str(self.cboServer.currentText() or "")
        return (new_name != "") and (new_name != old_name)

    def _recompute_save_enabled(self) -> None:
        enable = self._server_changed() or self._login_ok
        self.btnSave.setEnabled(bool(enable))

    # ---------- Web events ----------
    def _on_load_finished(self, ok: bool) -> None:
        url = self.web.url().toString()
        if not ok:
            self.lblStatus.setText(f"Tải trang thất bại: {url}")
            return

        if "/login" in url:
            self._inject_email_and_capture_hooks()
            self.lblStatus.setText("Trang đã sẵn sàng. Vui lòng đăng nhập trực tiếp trong WebView.")
        else:
            self.lblStatus.setText(f"Đã tải: {url}")

    def _on_url_changed(self, qurl: QtCore.QUrl) -> None:
        if self.SUCCESS_PATH in qurl.path():
            self._on_login_success_page()

    def _inject_email_and_capture_hooks(self) -> None:
        expected_email = (self.account.get("game_email") or "").replace("\\", "\\\\").replace("'", "\\'")
        js = f"""
        (function(){{
          try {{
            var email = '{expected_email}';
            var emailInput = document.querySelector('input[type=email],input[name=email],input[placeholder*="Email"],input[placeholder*="email"]');
            if (emailInput) {{
              emailInput.value = email;
              emailInput.dispatchEvent(new Event('input', {{bubbles:true}}));
              emailInput.readOnly = true;
              emailInput.style.backgroundColor = '#f7f7f7';
            }}
            var passInput = document.querySelector('input[type=password],input[name=password]');
            var form = document.querySelector('form') || document.body;
            function capture(){{
              try {{
                var e = emailInput ? emailInput.value : '';
                var p = passInput ? passInput.value : '';
                if (e || p){{
                  localStorage.setItem('bbtk_email', e||'');
                  localStorage.setItem('bbtk_password', p||'');
                }}
              }} catch(ex) {{}}
            }}
            if (form && form.addEventListener) {{
              form.addEventListener('submit', capture, true);
            }}
            var btn = document.querySelector('button[type=submit],input[type=submit]');
            if (btn && btn.addEventListener) {{
              btn.addEventListener('click', capture, true);
            }}
            window.addEventListener('beforeunload', capture, true);
            return true;
          }} catch(ex) {{
            return false;
          }}
        }})();
        """
        self.web.page().runJavaScript(js, lambda _: None)

    def _on_login_success_page(self) -> None:
        js = """
        (function(){
          try {
            var e = localStorage.getItem('bbtk_email') || '';
            var p = localStorage.getItem('bbtk_password') || '';
            localStorage.removeItem('bbtk_email');
            localStorage.removeItem('bbtk_password');
            return {email: e, password: p};
          } catch(ex) {
            return {email:'', password:''};
          }
        })();
        """
        def _after(res: Dict[str, Any]):
            email = (res or {}).get("email") or ""
            password = (res or {}).get("password") or ""
            expected = (self.account.get("game_email") or "").strip().lower()

            if not password:
                self._login_ok = False
                self._captured_email = None
                self._captured_password = None
                self.lblStatus.setText("Không lấy được mật khẩu từ trang đăng nhập. Vui lòng thử lại.")
                self._recompute_save_enabled()
                return

            if email.strip().lower() != expected:
                self._login_ok = False
                self._captured_email = None
                self._captured_password = None
                QtWidgets.QMessageBox.critical(self, "Sai tài khoản",
                    "Bạn vừa đăng nhập một email khác. Vui lòng đăng nhập đúng tài khoản đang sửa.")
                self.lblStatus.setText("Sai email đăng nhập.")
                self._recompute_save_enabled()
                return

            self._login_ok = True
            self._captured_email = email
            self._captured_password = password
            self.lblStatus.setText(f"Đăng nhập thành công: {email}")
            self._recompute_save_enabled()

        self.web.page().runJavaScript(js, _after)

    # ---------- Save ----------
    def _on_save(self) -> None:
        payload: Dict[str, Any] = {}

        # Đổi server?
        if self._server_changed():
            idx = self.cboServer.currentIndex()
            new_name = self.cboServer.currentText()
            new_sid = self._server_id_by_index.get(idx)
            if new_sid is not None:
                payload["server_id"] = int(new_sid)
            else:
                payload["server"] = new_name  # fallback với schema hiện tại (varchar(50))

        # Đổi mật khẩu?
        if self._login_ok and self._captured_email and self._captured_password:
            try:
                user_login_email = self.cloud.load_token().email
                enc = encrypt(self._captured_password, user_login_email)
                payload["game_password"] = enc
                payload["game_email"] = self._captured_email
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Lỗi mã hoá", f"Không thể mã hoá mật khẩu mới:\n{e}")
                return

        if not payload:
            self.reject()
            return

        # Gửi PUT lên API (API sẽ tự kiểm tra auth/license theo index.php)
        try:
            acc_id = int(self.account.get("id"))
            self.cloud.update_game_account(acc_id, payload)
            self.accept()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Lỗi cập nhật", f"Không thể cập nhật tài khoản:\n{e}")
