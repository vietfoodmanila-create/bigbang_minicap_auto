#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sys
import hashlib
import uuid
import platform
from dataclasses import dataclass

import requests
from PySide6 import QtCore, QtGui, QtWidgets

# ==================== CONFIG ====================
API_BASE_URL = os.getenv("BBTK_API_BASE", "https://api.bbtkauto.io.vn")

# Endpoint paths (giữ đúng logic, nếu API nào chưa có server sẽ trả 404 -> UI báo nhẹ nhàng)
REGISTER_START_PATH = "/api/register/start"
REGISTER_RESEND_PATH = "/api/register/resend"
REGISTER_VERIFY_PATH = "/api/register/verify"
LOGIN_PATH          = "/api/login"
LOGOUT_PATH         = "/api/logout"
LICENSE_STATUS_PATH = "/api/license/status"
LICENSE_ACTIVATE    = "/api/license/activate"
PAYMENT_INFO_PATH   = "/api/payment/info"   # lấy thông tin Zalo/Bank + URL ảnh QR từ server

# (có thể chưa có bên server, UI vẫn chạy bình thường)
FORGOT_START_PATH   = "/api/forgot/start"
FORGOT_VERIFY_PATH  = "/api/forgot/verify"
CHANGE_PASS_PATH    = "/api/password/change"

PING_PATH           = "/api/ping"

APP_NAME = "BBTKAuto"
TOKEN_FILE = os.path.join(
    os.getenv("APPDATA") or os.path.expanduser("~/.config"),
    APP_NAME, "token.json",
)
REQUEST_TIMEOUT = 15

# ==================== HELPERS ====================

def ensure_app_dir():
    d = os.path.dirname(TOKEN_FILE); os.makedirs(d, exist_ok=True); return d

def stable_device_uid() -> str:
    """Sinh UID thiết bị ổn định (ẩn trên UI nhưng vẫn gửi ngầm khi login)."""
    try: mac = uuid.getnode()
    except Exception: mac = 0
    sig = f"{platform.node()}|{platform.machine()}|{platform.processor()}|{mac}"
    return f"PC-{hashlib.sha1(sig.encode()).hexdigest()[:12].upper()}"

@dataclass
class TokenData:
    token: str
    email: str | None = None
    exp: str | None = None

class CloudClient:
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self._token: str | None = None
        self.device_uid = stable_device_uid()
        self.device_name = platform.node()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": f"{APP_NAME}/1.0"})
        self.load_token()
    # === token store ===
    def save_token(self, td: TokenData):
        ensure_app_dir()
        self._token = td.token
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump({"token": td.token, "email": td.email, "exp": td.exp}, f, ensure_ascii=False, indent=2)

    def load_token(self) -> TokenData | None:
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                obj = json.load(f)
            self._token = obj.get("token")
            return TokenData(token=obj.get("token"), email=obj.get("email"), exp=obj.get("exp"))
        except Exception:
            return None

    def clear_token(self):
        # Xóa token trong bộ nhớ
        self._token = None
        # Gỡ header Authorization khỏi session
        try:
            self.session.headers.pop("Authorization", None)
        except Exception:
            pass
        # Xóa file token.json
        try:
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
        except Exception:
            pass

    def is_logged_in(self) -> bool:
        return bool(self._token)

    # === low-level ===
    def _url(self, path: str) -> str: return self.base_url + path

    def _auth_headers(self) -> dict:
        hdrs = {"Content-Type": "application/json"}
        if self._token:
            hdrs["Authorization"] = f"Bearer {self._token}"
        # NEW: ràng buộc thiết bị
        try:
            from ui_auth import stable_device_uid  # nếu cùng file thì bỏ import này
        except Exception:
            pass
        hdrs["X-Device-UID"] = stable_device_uid()
        return hdrs

    # === API ===
    def ping(self) -> dict:
        r = self.session.get(self._url(PING_PATH), timeout=REQUEST_TIMEOUT); r.raise_for_status(); return r.json()

    # ----- Register + OTP -----
    def register_start(self, email: str, password: str) -> dict:
        r = self.session.post(self._url(REGISTER_START_PATH), json={"email": email, "password": password}, timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r); return r.json()

    def register_resend(self, email: str) -> dict:
        r = self.session.post(self._url(REGISTER_RESEND_PATH), json={"email": email}, timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r); return r.json()

    def register_verify(self, email: str, code: str) -> dict:
        r = self.session.post(self._url(REGISTER_VERIFY_PATH), json={"email": email, "code": code}, timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r); return r.json()

    # ----- Login/Logout -----
    def login(self, email: str, password: str, device_uid: str | None = None,
              device_name: str | None = None) -> TokenData:
        # Đảm bảo luôn gửi device_uid và device_name hợp lệ
        duid = device_uid or stable_device_uid()
        dname = device_name or platform.node() or "Unknown PC"
        payload = {"email": email, "password": password, "device_uid": duid, "device_name": dname}

        r = self.session.post(self._url(LOGIN_PATH), json=payload, timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r)
        data = r.json()
        token = data.get("token") or data.get("access_token")
        if not token:
            raise requests.HTTPError("Phản hồi không có token")

        self._token = token
        # NEW: gắn luôn vào session để các request sau tự mang theo
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.session.headers["X-Device-UID"] = duid

        td = TokenData(token=token, email=email, exp=data.get("exp"))
        self.save_token(td)
        return td

    # File: ui_auth.py, class CloudClient
    def logout(self) -> bool:
        # 1. Cố gắng gửi yêu cầu logout lên server (best-effort)
        if self._token:
            try:
                # Gửi yêu cầu nhưng không quan tâm kết quả trả về
                self.session.post(self._url(LOGOUT_PATH), headers=self._auth_headers(), timeout=REQUEST_TIMEOUT)
            except Exception:
                # Bỏ qua mọi lỗi (mất mạng, server lỗi, etc.)
                pass

        # 2. Luôn luôn xóa token cục bộ, đây là bước quan trọng nhất
        self.clear_token()
        return True

    def license_status(self) -> dict:
        params = {'device_uid': stable_device_uid()}
        r = self.session.get(self._url(LICENSE_STATUS_PATH), headers=self._auth_headers(), params=params,timeout=REQUEST_TIMEOUT)
        if r.status_code == 401: return {"logged_in": False}
        self._raise_for_json_error(r)
        data = r.json(); data["logged_in"] = True; return data

    def license_activate(self, license_key: str, device_uid: str, device_name: str | None = None) -> dict:
        pl = {"license_key": license_key, "device_uid": device_uid, "device_name": device_name or platform.node()}
        r = self.session.post(self._url(LICENSE_ACTIVATE), headers=self._auth_headers(), json=pl, timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r); return r.json()

    def list_licenses(self) -> list:
        """Lấy danh sách các license mà người dùng sở hữu."""
        r = self.session.get(self._url("/api/license/list"), headers=self._auth_headers(), timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r)
        return r.json().get("licenses", [])
    # ----- New: lấy thông tin thanh toán + ảnh QR từ server -----
    def payment_info(self) -> dict:
        r = self.session.get(self._url(PAYMENT_INFO_PATH), headers=self._auth_headers(), timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r); return r.json()

    # ----- Optional -----
    def forgot_start(self, email: str) -> dict:
        r = self.session.post(self._url(FORGOT_START_PATH), json={"email": email}, timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r); return r.json()

    def forgot_verify(self, email: str, code: str, new_password: str) -> dict:
        r = self.session.post(self._url(FORGOT_VERIFY_PATH), json={"email": email, "code": code, "new_password": new_password}, timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r); return r.json()

    def change_password(self, old_password: str, new_password: str) -> dict:
        r = self.session.post(self._url(CHANGE_PASS_PATH), headers=self._auth_headers(), json={"old_password": old_password, "new_password": new_password}, timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r); return r.json()
    def get_game_accounts(self) -> list:
        """Lấy danh sách tài khoản game của người dùng."""
        r = self.session.get(self._url("/api/game_accounts"), headers=self._auth_headers(), timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r)
        return r.json().get("accounts", [])

    def add_game_account(self, data: dict) -> dict:
        """Thêm một tài khoản game mới."""
        # Payload giờ được lấy trực tiếp từ dictionary data
        payload = {
            "game_email": data.get("game_email"),
            "game_password": data.get("game_password"),
            "server": data.get("server")
        }
        r = self.session.post(self._url("/api/game_accounts"), json=payload, headers=self._auth_headers(), timeout=30)
        self._raise_for_json_error(r)
        return r.json()

    def update_game_account(self, account_id: int, data: dict) -> dict:
        """Cập nhật thông tin một tài khoản game."""
        url = self._url(f"/api/game_accounts/{account_id}")
        # Tăng timeout vì có thể có cURL check
        r = self.session.put(url, json=data, headers=self._auth_headers(), timeout=30)
        self._raise_for_json_error(r)
        return r.json()

    def delete_game_account(self, account_id: int) -> dict:
        """Xóa quyền sở hữu một tài khoản game."""
        url = self._url(f"/api/game_accounts/{account_id}")
        r = self.session.delete(url, headers=self._auth_headers(), timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r)
        return r.json()
#hàm lấy api chúc phúc
    def get_blessing_config(self) -> dict:
        """Lấy cấu hình Chúc phúc của người dùng."""
        r = self.session.get(self._url("/api/blessing/config"), headers=self._auth_headers(), timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r)
        return r.json().get("config", {})

    def update_blessing_config(self, data: dict) -> dict:
        """Cập nhật cấu hình Chúc phúc."""
        r = self.session.put(self._url("/api/blessing/config"), json=data, headers=self._auth_headers(),
                             timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r)
        return r.json()

    # Đoạn code mới để thay thế
    def get_blessing_targets(self, fetch_all: bool = False) -> list:
        """
        Lấy danh sách các mục tiêu Chúc phúc.
        :param fetch_all: Nếu True, lấy tất cả mục tiêu để quản lý.
                          Nếu False, chỉ lấy những mục tiêu đủ điều kiện để chạy auto.
        """
        path = "/api/blessing/targets"
        params = {'all': 'true'} if fetch_all else {}

        r = self.session.get(self._url(path), headers=self._auth_headers(), params=params, timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r)
        return r.json().get("targets", [])

    def add_blessing_target(self, target_name: str) -> dict:
        """Thêm một mục tiêu Chúc phúc mới."""
        payload = {"target_name": target_name}
        r = self.session.post(self._url("/api/blessing/targets"), json=payload, headers=self._auth_headers(),
                              timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r)
        return r.json()

    def delete_blessing_target(self, target_id: int) -> dict:
        """Xóa một mục tiêu Chúc phúc."""
        url = self._url(f"/api/blessing/targets/{target_id}")
        r = self.session.delete(url, headers=self._auth_headers(), timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r)
        return r.json()

    def record_blessing(self, target_id: int, game_account_id: int) -> dict:
        """Ghi lại một hành động Chúc phúc vào lịch sử."""
        payload = {"target_id": target_id, "game_account_id": game_account_id}
        r = self.session.post(self._url("/api/blessing/history"), json=payload, headers=self._auth_headers(),
                              timeout=REQUEST_TIMEOUT)
        self._raise_for_json_error(r)
        return r.json()
    # --- utils ---
    @staticmethod
    def _raise_for_json_error(r: requests.Response):
        if r.status_code >= 400:
            try: j = r.json(); msg = j.get("error") or j.get("message") or r.text
            except Exception: msg = r.text
            e = requests.HTTPError(msg); e.response = r; raise e

# ==================== UI WIDGETS ====================

class ClickableLabel(QtWidgets.QLabel):
    clicked = QtCore.Signal()
    def mousePressEvent(self, e: QtGui.QMouseEvent) -> None:
        if e.button() == QtCore.Qt.LeftButton: self.clicked.emit()
        super().mousePressEvent(e)

class LoginPage(QtWidgets.QWidget):
    logged_in = QtCore.Signal(TokenData)
    goto_register = QtCore.Signal()
    goto_forgot = QtCore.Signal()
    def __init__(self, cloud: CloudClient, parent=None):
        super().__init__(parent); self.cloud = cloud; self._build_ui()
    def _build_ui(self):
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(16, 16, 16, 8)
        title = QtWidgets.QLabel("Đăng nhập"); title.setStyleSheet("font-weight:600;font-size:18px;"); lay.addWidget(title)
        self.leEmail = QtWidgets.QLineEdit(); self.leEmail.setPlaceholderText("Email")
        self.lePass  = QtWidgets.QLineEdit(); self.lePass.setPlaceholderText("Mật khẩu"); self.lePass.setEchoMode(QtWidgets.QLineEdit.Password)
        self.btnLogin = QtWidgets.QPushButton("Đăng nhập"); self.btnLogin.setFixedHeight(34); self.btnLogin.clicked.connect(self.on_login)
        self.lblInfo = QtWidgets.QLabel(); self.lblInfo.setWordWrap(True)
        form = QtWidgets.QFormLayout(); form.addRow("Email", self.leEmail); form.addRow("Mật khẩu", self.lePass)
        lay.addLayout(form); lay.addWidget(self.btnLogin)
        links = QtWidgets.QHBoxLayout()
        lForgot = QtWidgets.QPushButton("Quên mật khẩu"); lForgot.setFlat(True); lForgot.setCursor(QtCore.Qt.PointingHandCursor)
        lRegister = QtWidgets.QPushButton("Đăng ký"); lRegister.setFlat(True); lRegister.setCursor(QtCore.Qt.PointingHandCursor)
        lForgot.clicked.connect(self.goto_forgot.emit); lRegister.clicked.connect(self.goto_register.emit)
        links.addStretch(); links.addWidget(lForgot); links.addSpacing(6); links.addWidget(lRegister); lay.addLayout(links)
        lay.addWidget(self.lblInfo); lay.addStretch(); self.setMaximumHeight(260)
        td = self.cloud.load_token();
        if td and td.email: self.leEmail.setText(td.email)
    def on_login(self):
        email = self.leEmail.text().strip().lower(); pw = self.lePass.text()
        if not email or not pw: self._err("Nhập email và mật khẩu"); return
        try:
            td = self.cloud.login(email, pw, device_uid=stable_device_uid(), device_name=platform.node())
            self._ok("Đăng nhập thành công"); self.logged_in.emit(td)
        except requests.HTTPError as e:
            msg = str(e)
            if "bad_credentials" in msg or "invalid" in msg: self._err("Sai thông tin hoặc chưa xác minh.")
            elif "max_devices" in msg: self._err("License đã đủ số thiết bị.")
            else: self._err(msg)
        except Exception as e: self._err(f"Lỗi: {e}")
    def _err(self, m): self.lblInfo.setStyleSheet("color:#c62828;"); self.lblInfo.setText(m)
    def _ok (self, m): self.lblInfo.setStyleSheet("color:#2e7d32;"); self.lblInfo.setText(m)

class RegisterPage(QtWidgets.QWidget):
    goto_login = QtCore.Signal()
    def __init__(self, cloud: CloudClient, parent=None):
        super().__init__(parent); self.cloud = cloud; self.cooldown_left=0; self.timer=QtCore.QTimer(self); self.timer.timeout.connect(self._tick); self._build_ui()
    def _build_ui(self):
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(16,16,16,8)
        title = QtWidgets.QLabel("Đăng ký tài khoản"); title.setStyleSheet("font-weight:600;font-size:18px;"); lay.addWidget(title)
        self.leEmail=QtWidgets.QLineEdit(); self.leEmail.setPlaceholderText("Email")
        self.lePass =QtWidgets.QLineEdit(); self.lePass.setPlaceholderText("Mật khẩu (>=8)"); self.lePass.setEchoMode(QtWidgets.QLineEdit.Password)
        self.lePass2=QtWidgets.QLineEdit(); self.lePass2.setPlaceholderText("Nhập lại mật khẩu"); self.lePass2.setEchoMode(QtWidgets.QLineEdit.Password)
        self.btnSend=QtWidgets.QPushButton("Gửi mã OTP"); self.btnSend.clicked.connect(self.on_send)
        self.leOTP =QtWidgets.QLineEdit(); self.leOTP.setPlaceholderText("Mã OTP (4 số)"); self.leOTP.setMaxLength(6)
        self.btnVerify=QtWidgets.QPushButton("Xác minh & Tạo tài khoản"); self.btnVerify.clicked.connect(self.on_verify)
        self.lblInfo=QtWidgets.QLabel(); self.lblInfo.setWordWrap(True)
        form=QtWidgets.QFormLayout(); form.addRow("Email", self.leEmail); form.addRow("Mật khẩu", self.lePass); form.addRow("Nhập lại", self.lePass2); form.addRow(self.btnSend); form.addRow("Mã OTP", self.leOTP); form.addRow(self.btnVerify)
        lay.addLayout(form); back=QtWidgets.QPushButton("← Quay lại đăng nhập"); back.setFlat(True); back.clicked.connect(self.goto_login.emit); lay.addWidget(back); lay.addWidget(self.lblInfo); lay.addStretch(); self.setMaximumHeight(360)
    def _start_cooldown(self, s:int=60): self.cooldown_left=s; self.btnSend.setEnabled(False); self._update_send_text(); self.timer.start(1000)
    def _tick(self):
        self.cooldown_left-=1
        if self.cooldown_left<=0: self.timer.stop(); self.btnSend.setEnabled(True); self.btnSend.setText("Gửi mã OTP")
        else: self._update_send_text()
    def _update_send_text(self): self.btnSend.setText(f"Gửi lại sau {self.cooldown_left}s")
    def on_send(self):
        email=self.leEmail.text().strip().lower(); pw=self.lePass.text(); pw2=self.lePass2.text()
        if not email or "@" not in email: self._err("Email không hợp lệ"); return
        if len(pw)<8 or pw!=pw2: self._err("Mật khẩu phải >=8 và khớp nhau"); return
        try: self.cloud.register_start(email,pw); self._ok("Đã gửi OTP. Kiểm tra email."); self._start_cooldown(60)
        except requests.HTTPError as e:
            msg=str(e)
            if "daily_limit" in msg: self._err("Bạn đã vượt quá 3 lần/ngày.")
            elif "cooldown" in msg: self._err("Gửi quá nhanh. Đợi 60 giây.")
            else: self._err(msg)
        except Exception as e: self._err(f"Lỗi: {e}")
    def on_verify(self):
        email=self.leEmail.text().strip().lower(); code=self.leOTP.text().strip()
        if not (email and code): self._err("Nhập email và mã OTP"); return
        try: self.cloud.register_verify(email, code); self._ok("Xác minh thành công. Quay lại đăng nhập.")
        except requests.HTTPError as e: self._err(str(e))
        except Exception as e: self._err(f"Lỗi: {e}")
    def _err(self, m): self.lblInfo.setStyleSheet("color:#c62828;"); self.lblInfo.setText(m)
    def _ok (self, m): self.lblInfo.setStyleSheet("color:#2e7d32;"); self.lblInfo.setText(m)

class ForgotPage(QtWidgets.QWidget):
    goto_login = QtCore.Signal()
    def __init__(self, cloud: CloudClient, parent=None):
        super().__init__(parent); self.cloud=cloud; self._build_ui()
    def _build_ui(self):
        lay=QtWidgets.QVBoxLayout(self); lay.setContentsMargins(16,16,16,8)
        title=QtWidgets.QLabel("Quên mật khẩu"); title.setStyleSheet("font-weight:600;font-size:18px;"); lay.addWidget(title)
        self.leEmail=QtWidgets.QLineEdit(); self.leEmail.setPlaceholderText("Email")
        self.btnSend=QtWidgets.QPushButton("Gửi mã OTP"); self.btnSend.clicked.connect(self.on_send)
        self.leOTP=QtWidgets.QLineEdit(); self.leOTP.setPlaceholderText("Mã OTP"); self.leOTP.setMaxLength(6)
        self.leNew=QtWidgets.QLineEdit(); self.leNew.setPlaceholderText("Mật khẩu mới"); self.leNew.setEchoMode(QtWidgets.QLineEdit.Password)
        self.btnVerify=QtWidgets.QPushButton("Xác minh & Đặt mật khẩu"); self.btnVerify.clicked.connect(self.on_verify)
        form=QtWidgets.QFormLayout(); form.addRow("Email", self.leEmail); form.addRow(self.btnSend); form.addRow("Mã OTP", self.leOTP); form.addRow("Mật khẩu mới", self.leNew); form.addRow(self.btnVerify)
        lay.addLayout(form); back=QtWidgets.QPushButton("← Quay lại đăng nhập"); back.setFlat(True); back.clicked.connect(self.goto_login.emit)
        self.lblInfo=QtWidgets.QLabel(); self.lblInfo.setWordWrap(True); lay.addWidget(back); lay.addWidget(self.lblInfo); lay.addStretch(); self.setMaximumHeight(320)
    def on_send(self):
        email=self.leEmail.text().strip().lower()
        if not email: self._err("Nhập email"); return
        try: self.cloud.forgot_start(email); self._ok("Đã gửi OTP khôi phục (nếu server hỗ trợ).")
        except requests.HTTPError as e:
            if getattr(e,"response",None) and e.response.status_code==404: self._err("Chức năng chưa hỗ trợ trên máy chủ.")
            else: self._err(str(e))
        except Exception as e: self._err(f"Lỗi: {e}")
    def on_verify(self):
        email=self.leEmail.text().strip().lower(); code=self.leOTP.text().strip(); newp=self.leNew.text()
        if not (email and code and len(newp)>=8): self._err("Điền đầy đủ và mật khẩu ≥ 8 ký tự"); return
        try: self.cloud.forgot_verify(email, code, newp); self._ok("Đổi mật khẩu thành công (nếu server hỗ trợ).")
        except requests.HTTPError as e:
            if getattr(e,"response",None) and e.response.status_code==404: self._err("Chức năng chưa hỗ trợ trên máy chủ.")
            else: self._err(str(e))
        except Exception as e: self._err(f"Lỗi: {e}")
    def _err(self, m): self.lblInfo.setStyleSheet("color:#c62828;"); self.lblInfo.setText(m)
    def _ok (self, m): self.lblInfo.setStyleSheet("color:#2e7d32;"); self.lblInfo.setText(m)

class ChangePasswordDialog(QtWidgets.QDialog):
    def __init__(self, cloud: CloudClient, parent=None):
        super().__init__(parent); self.cloud=cloud; self.setWindowTitle("Đổi mật khẩu"); self.setFixedWidth(420)
        lay=QtWidgets.QVBoxLayout(self)
        self.leOld=QtWidgets.QLineEdit(); self.leOld.setEchoMode(QtWidgets.QLineEdit.Password); self.leOld.setPlaceholderText("Mật khẩu hiện tại")
        self.leNew=QtWidgets.QLineEdit(); self.leNew.setEchoMode(QtWidgets.QLineEdit.Password); self.leNew.setPlaceholderText("Mật khẩu mới (>=8)")
        self.btn=QtWidgets.QPushButton("Đổi mật khẩu"); self.btn.clicked.connect(self.on_change)
        self.lbl=QtWidgets.QLabel(); self.lbl.setWordWrap(True)
        form=QtWidgets.QFormLayout(); form.addRow("Mật khẩu cũ", self.leOld); form.addRow("Mật khẩu mới", self.leNew)
        lay.addLayout(form); lay.addWidget(self.btn); lay.addWidget(self.lbl)
    def on_change(self):
        oldp=self.leOld.text(); newp=self.leNew.text()
        if len(newp)<8: self._err("Mật khẩu mới phải >= 8"); return
        try: self.cloud.change_password(oldp, newp); self._ok("Đổi mật khẩu thành công."); QtCore.QTimer.singleShot(800, self.accept)
        except requests.HTTPError as e:
            if getattr(e,"response",None) and e.response.status_code==404: self._err("Chức năng chưa hỗ trợ trên máy chủ.")
            else: self._err(str(e))
        except Exception as e: self._err(f"Lỗi: {e}")
    def _err(self, m): self.lbl.setStyleSheet("color:#c62828;"); self.lbl.setText(m)
    def _ok (self, m): self.lbl.setStyleSheet("color:#2e7d32;"); self.lbl.setText(m)

def _pixmap_from_url(url: str, size: int | None = None) -> QtGui.QPixmap | None:
    """Tải ảnh QR/Logo từ URL server (không tự sinh QR)."""
    try:
        if not url: return None
        r = requests.get(url, timeout=10); r.raise_for_status()
        img = QtGui.QImage.fromData(r.content)
        if img.isNull(): return None
        pm = QtGui.QPixmap.fromImage(img)
        if size: pm = pm.scaled(size, size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        return pm
    except Exception:
        return None

class ActivateLicenseDialog(QtWidgets.QDialog):
    activated = QtCore.Signal(dict)
    def __init__(self, cloud: CloudClient, parent=None):
        super().__init__(parent); self.cloud=cloud; self.setWindowTitle("Kích hoạt / Gia hạn license"); self.setMinimumWidth(560)
        lay=QtWidgets.QVBoxLayout(self)
        # Nhập mã kích hoạt
        gb1=QtWidgets.QGroupBox("Nhập mã license để kích hoạt / gia hạn")
        f1=QtWidgets.QFormLayout(gb1)
        self.leKey=QtWidgets.QLineEdit(); self.leKey.setPlaceholderText("Nhập mã license…")
        self.btnAct=QtWidgets.QPushButton("Kích hoạt / Gia hạn"); self.btnAct.clicked.connect(self.on_activate)
        f1.addRow("Mã license", self.leKey); f1.addRow(self.btnAct)
        # Thông tin mua (từ API)
        gb2=QtWidgets.QGroupBox("Mua license")
        self.v2=QtWidgets.QVBoxLayout(gb2)
        self.lblZalo=QtWidgets.QLabel("—"); self.lblBank=QtWidgets.QLabel("—")
        self.imgZalo=QtWidgets.QLabel(); self.imgBank=QtWidgets.QLabel()
        self.imgZalo.setFixedSize(150,150); self.imgBank.setFixedSize(150,150)
        self.imgZalo.setScaledContents(True); self.imgBank.setScaledContents(True)
        vZ=QtWidgets.QHBoxLayout(); vZ.addWidget(self.imgZalo); vZ.addWidget(self.lblZalo); vZ.addStretch()
        vB=QtWidgets.QHBoxLayout(); vB.addWidget(self.imgBank); vB.addWidget(self.lblBank); vB.addStretch()
        self.v2.addLayout(vZ); self.v2.addSpacing(8); self.v2.addLayout(vB)
        self.lbl=QtWidgets.QLabel(); self.lbl.setWordWrap(True)
        lay.addWidget(gb1); lay.addWidget(gb2); lay.addWidget(self.lbl)
        self._load_payment_info()
    def _load_payment_info(self):
        try:
            info = self.cloud.payment_info()  # {zalo:{number,link,qr_url}, bank:{...}, note_template, email_hint}
            z = info.get("zalo", {}) or {}; b = info.get("bank", {}) or {}
            note_tpl = (info.get("note_template") or "BBTAUTO {email}"); email_hint = info.get("email_hint") or ""
            zalo_text = []
            if z.get("number"): zalo_text.append(f"Zalo: {z.get('number')}")
            if z.get("link"):   zalo_text.append(f"Link: {z.get('link')}")
            self.lblZalo.setText("\n".join(zalo_text) if zalo_text else "Zalo: —")
            bank_text = []
            line1 = " ".join([x for x in [b.get("name"), b.get("branch")] if x]);
            if line1: bank_text.append(line1)
            acc = " - ".join([x for x in [b.get("account"), b.get("holder")] if x]);
            if acc: bank_text.append(acc)
            bank_text.append(f"Nội dung CK: {note_tpl.replace('{email}', email_hint or '{email}')}")
            self.lblBank.setText("\n".join(bank_text))
            self.imgZalo.setPixmap(_pixmap_from_url(z.get("qr_url"), 150) or QtGui.QPixmap())
            self.imgBank.setPixmap(_pixmap_from_url(b.get("qr_url"), 150) or QtGui.QPixmap())
        except requests.HTTPError as e:
            self.lbl.setStyleSheet("color:#c62828;"); self.lbl.setText(f"Lỗi tải thông tin thanh toán: {e}")
        except Exception as e:
            self.lbl.setStyleSheet("color:#c62828;"); self.lbl.setText(f"Lỗi tải thông tin thanh toán: {e}")
    def on_activate(self):
        key = self.leKey.text().strip().upper()
        if not key: self._err("Nhập mã license"); return
        try:
            data = self.cloud.license_activate(key, stable_device_uid(), platform.node())
            self._ok("Kích hoạt/Gia hạn thành công."); self.activated.emit(data); QtCore.QTimer.singleShot(700, self.accept)
        except requests.HTTPError as e: self._err(str(e))
        except Exception as e: self._err(f"Lỗi: {e}")
    def _err(self, m): self.lbl.setStyleSheet("color:#c62828;"); self.lbl.setText(m)
    def _ok (self, m): self.lbl.setStyleSheet("color:#2e7d32;"); self.lbl.setText(m)

# ==================== AUTH CONTAINER ====================

class AuthWindow(QtWidgets.QDialog):
    """Chỉ hiển thị 1 màn hình tại 1 thời điểm: Login / Đăng ký / Quên MK."""
    logged_in = QtCore.Signal(TokenData)
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("BBTK Auto – Đăng nhập"); self.setMinimumSize(520,320); self.cloud=CloudClient(); self._build_ui()
    def _build_ui(self):
        lay=QtWidgets.QVBoxLayout(self)
        self.stk=QtWidgets.QStackedWidget()
        self.pgLogin=LoginPage(self.cloud); self.pgReg=RegisterPage(self.cloud); self.pgForgot=ForgotPage(self.cloud)
        self.stk.addWidget(self.pgLogin); self.stk.addWidget(self.pgReg); self.stk.addWidget(self.pgForgot); lay.addWidget(self.stk)
        self.pgLogin.goto_register.connect(lambda: self.stk.setCurrentWidget(self.pgReg))
        self.pgLogin.goto_forgot.connect(lambda: self.stk.setCurrentWidget(self.pgForgot))
        self.pgReg.goto_login.connect(lambda: self.stk.setCurrentWidget(self.pgLogin))
        self.pgForgot.goto_login.connect(lambda: self.stk.setCurrentWidget(self.pgLogin))
        self.pgLogin.logged_in.connect(self._on_logged_in)
        row=QtWidgets.QHBoxLayout(); row.addStretch(); btnClose=QtWidgets.QPushButton("Đóng"); btnClose.clicked.connect(self.reject); row.addWidget(btnClose); lay.addLayout(row)

    def _on_logged_in(self, td: TokenData):
        # đăng nhập xong -> đóng dialog để main mở UI chính
        self.accept()


# ===== Back-compat: giữ nguyên tên lớp cũ để main.py hiện tại không phải sửa =====
class AuthDialog(AuthWindow):
    """Giữ tương thích với code cũ: AuthDialog == AuthWindow."""
    pass

# ==================== INFO BAR + LICENSE GATE ====================

class TopInfoBar(QtWidgets.QWidget):
    request_refresh = QtCore.Signal()
    def __init__(self, cloud: CloudClient, parent=None):
        super().__init__(parent); self.cloud=cloud; self._build_ui()
    def _build_ui(self):
        lay=QtWidgets.QHBoxLayout(self); lay.setContentsMargins(8,4,8,4)
        self.lblEmail=ClickableLabel("Chưa đăng nhập"); self.lblEmail.setStyleSheet("font-weight:600; color:#1a237e; text-decoration: underline;"); self.lblEmail.setCursor(QtCore.Qt.PointingHandCursor); self.lblEmail.clicked.connect(self._open_change_pass)
        self.lblLic=ClickableLabel("License: —"); self.lblLic.setCursor(QtCore.Qt.PointingHandCursor); self.lblLic.clicked.connect(self._open_activate)
        lay.addWidget(self.lblEmail); lay.addWidget(QtWidgets.QLabel(" | ")); lay.addWidget(self.lblLic); lay.addStretch()
        btn=QtWidgets.QToolButton(); btn.setText("Làm mới"); btn.clicked.connect(self.request_refresh.emit); lay.addWidget(btn)
    def set_user(self, email: str | None): self.lblEmail.setText(email or "Chưa đăng nhập")
    def set_license_text(self, s: str): self.lblLic.setText(s)
    def _open_change_pass(self): dlg=ChangePasswordDialog(self.cloud, self); dlg.exec()
    def _open_activate(self): dlg=ActivateLicenseDialog(self.cloud, self); dlg.activated.connect(lambda _ : self.request_refresh.emit()); dlg.exec()

def license_is_valid(st: dict) -> bool:
    if not st: return False
    if st.get("valid") is not None: return bool(st.get("valid"))
    status = st.get("status"); exp = st.get("expires_at")
    try:
        if status==1 and exp: return True
    except Exception:
        pass
    return False

def gate_features_by_license(cloud: CloudClient, on_enable: callable, on_disable: callable, on_status_text: callable | None = None):
    try: st = cloud.license_status()
    except Exception: st = {"ok": False}
    if on_status_text:
        if st.get("ok"):
            if license_is_valid(st):
                dl = st.get("days_left"); text = f"Đã kích hoạt, còn {dl} ngày" if dl is not None else "Đã kích hoạt"
            else: text = "Chưa kích hoạt"
        else: text = "Không xác định"
        on_status_text(text)
    if license_is_valid(st): on_enable()
    else: on_disable()

# =============== demo chạy độc lập (tùy chọn) ===============
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    auth = AuthDialog()
    if auth.exec() != QtWidgets.QDialog.Accepted: sys.exit(0)
    cloud = auth.cloud
    win = QtWidgets.QMainWindow(); root = QtWidgets.QWidget(); v = QtWidgets.QVBoxLayout(root)
    info = TopInfoBar(cloud); v.addWidget(info)
    grp = QtWidgets.QGroupBox("Khu vực tính năng Auto"); lay = QtWidgets.QVBoxLayout(grp); lay.addWidget(QtWidgets.QLabel("…nội dung/tính năng chính…")); v.addWidget(grp)
    def _enable(): grp.setEnabled(True)
    def _disable(): grp.setEnabled(False)
    def _text(s): info.set_license_text(f"License: {s}")
    def _refresh():
        td = cloud.load_token()
        info.set_user(td.email if td else None)
        gate_features_by_license(cloud, _enable, _disable, _text)
    info.request_refresh.connect(_refresh); _refresh()
    win.setCentralWidget(root); win.resize(760, 480); win.show()
    sys.exit(app.exec())
