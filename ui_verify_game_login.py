# ui_verify_game_login_v2.py
from __future__ import annotations
from typing import Optional, Dict
from urllib.parse import urlparse, parse_qs
import re

from PySide6 import QtCore, QtWidgets
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript,QWebEngineProfile

PAY_HOST = "pay.bigbangthoikhong.vn"
LOGIN_URL = "https://pay.bigbangthoikhong.vn/login?game_id=105"
SUCCESS_PATH = "/rechargePackage"
SUCCESS_QS_KEY = "game_id"
SUCCESS_QS_VAL = "105"

# --- Trang thay thế QWebEnginePage để BẮT credentials qua console.log ---
class InterceptingPage(QWebEnginePage):
    credsCaptured = QtCore.Signal(str, str)  # email, password

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        # Nghe console log dạng:  BBAPP_CREDS::<email>::<password>
        try:
            if isinstance(message, str) and message.startswith("BBAPP_CREDS::"):
                # không log ra ngoài; chỉ emit signal nội bộ
                raw = message.split("::", 2)  # ["BBAPP_CREDS", email, password]
                if len(raw) == 3:
                    email = raw[1].strip()
                    password = raw[2]
                    self.credsCaptured.emit(email, password)
        except Exception:
            pass
        super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)

class VerifyGameLoginDialog(QtWidgets.QDialog):
    """
    Xác minh đăng nhập (client) theo 2 chế độ đối xứng:
      - Chế độ A (TỪ FORM): lấy email/mật khẩu ở form trái, AUTO-FILL vào web và submit.
      - Chế độ B (TỪ WEB): user nhập trên web; script bắt email+password khi submit (không yêu cầu gõ lại).
    Chỉ khi redirect hợp lệ (/rechargePackage?game_id=105) mới cho phép Xác nhận & đóng.
    """
    def __init__(self, parent=None, prefill_email: str = "", prefill_server: str = "", default_mode: str = "FORM"):
        super().__init__(parent)
        self.setWindowTitle("Xác minh đăng nhập tài khoản game (client-side)")
        self.setMinimumSize(980, 580)
        self._verified = False
        self._mode = default_mode  # "FORM" | "WEB"
        self._captured_from_web: Dict[str, str] = {}  # {"email":..., "password":...}
        self._used_form_values: Dict[str, str] = {}   # {"email":..., "password":...}

        self._build_ui(prefill_email, prefill_server)
        self._init_web()
        self._connect()
        self._apply_mode_ui()
        self._open_login()

    # ---------------- UI ----------------
    def _build_ui(self, prefill_email: str, prefill_server: str):
        root = QtWidgets.QVBoxLayout(self)

        # Chọn chế độ
        modeRow = QtWidgets.QHBoxLayout()
        self.rbForm = QtWidgets.QRadioButton("TỪ FORM (auto điền & kiểm tra)")
        self.rbWeb  = QtWidgets.QRadioButton("TỪ WEB (user nhập, app tự bắt)")
        self.rbForm.setChecked(self._mode != "WEB")
        self.rbWeb.setChecked(self._mode == "WEB")
        modeRow.addWidget(self.rbForm); modeRow.addWidget(self.rbWeb); modeRow.addStretch(1)
        root.addLayout(modeRow)

        splitter = QtWidgets.QSplitter()
        splitter.setOrientation(QtCore.Qt.Horizontal)
        root.addWidget(splitter)

        # Panel trái (FORM)
        left = QtWidgets.QWidget()
        l = QtWidgets.QVBoxLayout(left)
        form = QtWidgets.QFormLayout()
        self.leEmail = QtWidgets.QLineEdit(); self.leEmail.setPlaceholderText("Email đăng nhập trong game")
        if prefill_email: self.leEmail.setText(prefill_email)
        self.lePass  = QtWidgets.QLineEdit(); self.lePass.setPlaceholderText("Mật khẩu game"); self.lePass.setEchoMode(QtWidgets.QLineEdit.Password)
        self.cbShow  = QtWidgets.QCheckBox("Hiện mật khẩu")
        self.cbShow.toggled.connect(lambda on: self.lePass.setEchoMode(QtWidgets.QLineEdit.Normal if on else QtWidgets.QLineEdit.Password))
        self.leServer= QtWidgets.QLineEdit(); self.leServer.setPlaceholderText("Server (ví dụ: 1, 2, 3…) — có thể để trống")
        if prefill_server: self.leServer.setText(prefill_server)
        form.addRow("Email game", self.leEmail)
        form.addRow("Mật khẩu", self.lePass)
        form.addRow("", self.cbShow)
        form.addRow("Server", self.leServer)
        l.addLayout(form)

        self.btnVerify = QtWidgets.QPushButton("BẮT ĐẦU KIỂM TRA")
        l.addWidget(self.btnVerify)

        self.lbl = QtWidgets.QLabel(); self.lbl.setWordWrap(True)
        l.addWidget(self.lbl)
        l.addStretch(1)

        splitter.addWidget(left)

        # Panel phải (WEB)
        right = QtWidgets.QWidget()
        r = QtWidgets.QVBoxLayout(right)

        self.web_profile = QWebEngineProfile(self)
        self.web_profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
        self.web_profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
        self.web_profile.setHttpUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )

        self.web = QWebEngineView(self)
        r.addWidget(self.web, 1)

        tools = QtWidgets.QHBoxLayout()
        self.btnOpen = QtWidgets.QPushButton("Mở lại trang đăng nhập")
        tools.addWidget(self.btnOpen)
        tools.addStretch(1)
        r.addLayout(tools)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        # Hàng nút cuối
        bottom = QtWidgets.QHBoxLayout()
        self.btnCancel  = QtWidgets.QPushButton("Huỷ")
        self.btnConfirm = QtWidgets.QPushButton("Xác nhận & đóng")
        self.btnConfirm.setEnabled(False)
        bottom.addStretch(1); bottom.addWidget(self.btnCancel); bottom.addWidget(self.btnConfirm)
        root.addLayout(bottom)

    def _apply_mode_ui(self):
        # FORM mode: cho nhập form, WebView có thể ẩn (im lặng) hoặc để xem
        # WEB  mode: khoá form để tránh lệch dữ liệu, user nhập trên WebView
        is_form = self.rbForm.isChecked()
        for w in (self.leEmail, self.lePass, self.cbShow, self.leServer, self.btnVerify):
            w.setEnabled(is_form)
        # Nếu muốn hoàn toàn ẩn web ở FORM mode: self.web.setVisible(not is_form)
        # Ở đây để hiển thị nhằm debug; có thể đổi theo nhu cầu
        self._set_info("Chế độ TỪ FORM: nhập email/mật khẩu bên trái rồi bấm 'BẮT ĐẦU KIỂM TRA'." if is_form
                       else "Chế độ TỪ WEB: đăng nhập trong WebView; app sẽ tự bắt email/mật khẩu khi bấm Đăng nhập.")

    # ---------------- Web init & hooks ----------------
    def _init_web(self):
        # Dùng InterceptingPage để nghe console.log
        self.page = InterceptingPage(self.web_profile, self.web)
        self.page.credsCaptured.connect(self._on_creds_captured_from_web)
        self.web.setPage(self.page)

        # Inject script: bắt sự kiện submit để console.log("BBAPP_CREDS::<email>::<password>")
        js_capture = r"""
        (function(){
          if (window.__bbapp_hooked__) return; window.__bbapp_hooked__ = true;
          function pickEmail(){ return document.querySelector('input[type="email"]')
                 || document.querySelector('input[name*="email" i]') || document.querySelector('input[name*="user" i]'); }
          function pickPass(){ return document.querySelector('input[type="password"]')
                 || document.querySelector('input[name*="pass" i]'); }
          function captureNow(){
             try{
               var e = pickEmail(); var p = pickPass();
               var ev = (e && e.value) ? e.value.trim() : "";
               var pv = (p && p.value) ? p.value : "";
               if (pv && typeof console !== 'undefined' && console.log) {
                  console.log("BBAPP_CREDS::" + ev + "::" + pv);
               }
             }catch(_){}
          }
          document.addEventListener('submit', function(ev){ captureNow(); }, true);
          document.addEventListener('click', function(ev){
            var t = ev.target;
            if (!t) return;
            var typ = (t.getAttribute && (t.getAttribute('type')||"")).toLowerCase();
            if (typ === 'submit' || /login|đăng\s*nhập|dang\s*nhap/i.test(t.textContent||"")) {
               captureNow();
            }
          }, true);
        })();
        """
        sc = QWebEngineScript()
        sc.setName("bbapp-capture")
        sc.setInjectionPoint(QWebEngineScript.DocumentReady)
        sc.setWorldId(QWebEngineScript.MainWorld)
        sc.setRunsOnSubFrames(True)
        sc.setSourceCode(js_capture)
        self.web_profile.scripts().insert(sc)

    # ---------------- Signals/Slots ----------------
    def _connect(self):
        self.web.urlChanged.connect(self._on_url_changed)
        self.web.loadFinished.connect(self._on_load_finished)
        self.btnOpen.clicked.connect(self._open_login)
        self.btnVerify.clicked.connect(self._verify_form_mode)
        self.btnCancel.clicked.connect(self.reject)
        self.btnConfirm.clicked.connect(self._confirm_and_close)
        self.rbForm.toggled.connect(self._on_mode_change)
        self.rbWeb.toggled.connect(self._on_mode_change)

    def _on_mode_change(self):
        self._mode = "FORM" if self.rbForm.isChecked() else "WEB"
        self._apply_mode_ui()
        self._open_login()

    # ---------------- Logic ----------------
    def _open_login(self):
        self._verified = False
        self.btnConfirm.setEnabled(False)
        self._set_info("Đang mở trang đăng nhập…")
        self.web.setUrl(QtCore.QUrl(LOGIN_URL))

    def _on_load_finished(self, ok: bool):
        if not ok:
            self._set_error("Không tải được trang. Kiểm tra mạng.")
            return
        if self._mode == "FORM":
            self._set_info("Trang đã sẵn sàng. Bấm 'BẮT ĐẦU KIỂM TRA' để auto điền & submit.")
        else:
            self._set_info("Trang đã sẵn sàng. Vui lòng đăng nhập trực tiếp trong WebView.")

    def _on_url_changed(self, url: QtCore.QUrl):
        s = url.toString()
        parsed = urlparse(s)
        if parsed.netloc == PAY_HOST and parsed.path.startswith(SUCCESS_PATH):
            qs = parse_qs(parsed.query)
            if qs.get(SUCCESS_QS_KEY, [""])[0] == SUCCESS_QS_VAL:
                # Thành công: kiểm tra chế độ để chốt credentials
                if self._mode == "FORM":
                    if not self._used_form_values.get("email") or not self._used_form_values.get("password"):
                        self._set_error("Thiếu giá trị form đã dùng. Vui lòng thử lại.")
                        return
                    self._verified = True
                    self._set_ok("Đăng nhập thành công (TỪ FORM).")
                    self.btnConfirm.setEnabled(True)
                else:
                    if not self._captured_from_web.get("password"):
                        self._set_error("Chưa bắt được mật khẩu từ WebView. Vui lòng thử lại thao tác đăng nhập.")
                        return
                    self._verified = True
                    self._set_ok("Đăng nhập thành công (TỪ WEB).")
                    self.btnConfirm.setEnabled(True)

    def _verify_form_mode(self):
        # Chỉ chạy ở chế độ FORM: auto fill + submit với giá trị ở panel trái
        if self._mode != "FORM":
            return
        email = (self.leEmail.text() or "").strip()
        password = self.lePass.text()
        if not email or not password:
            self._set_error("Vui lòng nhập email và mật khẩu ở panel trái.")
            return
        self._used_form_values = {"email": email, "password": password, "server": (self.leServer.text() or "").strip()}
        js = """
        (function(){
          function pick(sel){return document.querySelector(sel);}
          var e = pick('input[type=email]') || pick('input[name*=email i]') || pick('input[name*=user i]');
          var p = pick('input[type=password]') || pick('input[name*=pass i]');
          if (e){ e.focus(); e.value = %EMAIL%; e.dispatchEvent(new Event('input', {bubbles:true})); }
          if (p){ p.focus(); p.value = %PASS%; p.dispatchEvent(new Event('input', {bubbles:true})); }
          var btn = pick('button[type=submit]') || pick('button[name*=login i]') || pick('button[class*=login i]') || pick('input[type=submit]');
          if (btn){ btn.click(); return "submitted"; }
          if (p && e && p.form && p.form.submit){ p.form.submit(); return "form.submit"; }
          return "not_found";
        })();
        """.replace("%EMAIL%", repr(email)).replace("%PASS%", repr(password))
        self.web.page().runJavaScript(js, self._after_form_submit)

    def _after_form_submit(self, res):
        if res in ("submitted", "form.submit"):
            self._set_info("Đã tự động điền & submit. Nếu có CAPTCHA/OTP, vui lòng hoàn tất trong WebView.")
        else:
            self._set_error("Không tìm được nút/biểu mẫu để submit. Hãy thử chế độ 'TỪ WEB'.")

    def _on_creds_captured_from_web(self, email: str, password: str):
        # Chỉ chấp nhận khi đang ở chế độ WEB
        if self._mode != "WEB":
            return
        email = (email or "").strip()
        self._captured_from_web = {"email": email, "password": password}
        # Cập nhật panel trái để hiển thị (readOnly)
        self.leEmail.setText(email)
        self.lePass.setText(password)
        self.leEmail.setEnabled(False)
        self.lePass.setEnabled(False)
        self.cbShow.setEnabled(True)  # vẫn cho phép xem/ẩn
        self._set_info("Đã bắt được email/mật khẩu từ WebView. Tiếp tục đăng nhập để hoàn tất.")

    def _confirm_and_close(self):
        if not self._verified:
            self._set_error("Chưa xác minh đăng nhập thành công.")
            return
        # Trả về đúng bộ credentials đã dùng trong chế độ tương ứng
        if self._mode == "FORM":
            self._data = dict(self._used_form_values)
        else:
            server = self.leServer.text().strip()
            self._data = {"email": self._captured_from_web.get("email", ""),
                          "password": self._captured_from_web.get("password", ""),
                          "server": server}
        self.accept()

    def get_verified_data(self) -> Optional[Dict]:
        if not self._verified:
            return None
        # Chuẩn hoá key names cho caller
        if self._mode == "FORM":
            return {"game_email": self._used_form_values.get("email", ""),
                    "game_password": self._used_form_values.get("password", ""),
                    "server": self._used_form_values.get("server", "")}
        return {"game_email": self._data.get("email", ""),
                "game_password": self._data.get("password", ""),
                "server": self._data.get("server", "")}

    # ---------------- helpers ----------------
    def _set_error(self, m: str):
        self.lbl.setStyleSheet("color:#c62828;"); self.lbl.setText(m)

    def _set_ok(self, m: str):
        self.lbl.setStyleSheet("color:#2e7d32;"); self.lbl.setText(m)

    def _set_info(self, m: str):
        self.lbl.setStyleSheet("color:#333;"); self.lbl.setText(m)
