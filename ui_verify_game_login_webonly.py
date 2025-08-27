# ui_verify_game_login_webonly.py
from __future__ import annotations
from typing import Optional, Dict, List
from urllib.parse import urlparse, parse_qs

from PySide6 import QtCore, QtWidgets
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript, QWebEngineProfile

PAY_HOST = "pay.bigbangthoikhong.vn"
LOGIN_URL = "https://pay.bigbangthoikhong.vn/login?game_id=105"
SUCCESS_PATH = "/rechargePackage"
SUCCESS_QS_KEY = "game_id"
SUCCESS_QS_VAL = "105"


class InterceptingPage(QWebEnginePage):
    credsCaptured = QtCore.Signal(str, str)  # email, password

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        try:
            if isinstance(message, str) and message.startswith("BBAPP_CREDS::"):
                parts = message.split("::", 2)
                if len(parts) == 3:
                    self.credsCaptured.emit(parts[1].strip(), parts[2])
        except Exception:
            pass
        super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)


class VerifyGameLoginWebOnlyDialog(QtWidgets.QDialog):
    """
    - add_mode (mặc định): yêu cầu đăng nhập web thành công (redirect) rồi mới cho OK.
    - edit_mode=True: cho phép OK nếu đã đăng nhập web thành công HOẶC chỉ đổi server.
      Nếu đổi mật khẩu, email đăng nhập phải khớp preset_email.
    """
    def __init__(self,
                 cloud,
                 parent: Optional[QtWidgets.QWidget] = None,
                 edit_mode: bool = False,
                 preset_email: Optional[str] = None,
                 initial_server_id: Optional[int] = None,
                 initial_server_name: Optional[str] = None,
                 lock_email: bool = False):
        super().__init__(parent)
        self.cloud = cloud
        self.setWindowTitle("Xác minh đăng nhập (Web) & chọn Server" if not edit_mode else "Sửa tài khoản (Web) & chọn Server")
        self.setMinimumSize(960, 580)

        # context
        self._edit_mode = bool(edit_mode)
        self._preset_email = (preset_email or "").strip()
        self._initial_server_id = initial_server_id
        self._initial_server_name = (initial_server_name or "").strip()
        self._lock_email = bool(lock_email)

        # state
        self._verified = False
        self._email = ""
        self._password = ""
        self._servers: List[Dict] = []

        self._build_ui()
        self._init_web()
        self._load_servers()
        self._open_login()

    # ---------- UI ----------
    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        # Hướng dẫn trên cùng
        self.lblGuide = QtWidgets.QLabel()
        self.lblGuide.setWordWrap(True)
        if self._edit_mode:
            self.lblGuide.setText(
                "<b>Hướng dẫn:</b> Nếu chỉ muốn đổi <b>Server</b>, hãy chọn server mới rồi bấm <i>Xác nhận & Lưu</i>.<br>"
                "Nếu muốn đổi <b>mật khẩu</b>, hãy đăng nhập thành công trong khung WebView. "
                "Email đăng nhập phải đúng: <b>{}</b>.".format(self._preset_email or "email tài khoản cần sửa")
            )
        else:
            self.lblGuide.setText("Vui lòng đăng nhập tài khoản game trong WebView và chọn Server để thêm tài khoản.")
        root.addWidget(self.lblGuide)

        # Chọn server
        top = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel("Chọn server:")
        self.cbServer = QtWidgets.QComboBox()
        self.cbServer.setMinimumWidth(200)
        self.cbServer.currentIndexChanged.connect(self._reeval_ok)
        top.addWidget(lbl)
        top.addWidget(self.cbServer)
        top.addStretch(1)
        root.addLayout(top)

        # WebView
        self.web_profile = QWebEngineProfile(self)
        self.web_profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
        self.web_profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
        self.web_profile.setHttpUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        self.web = QWebEngineView(self)
        root.addWidget(self.web, 1)

        # Thông báo dưới
        self.lbl = QtWidgets.QLabel()
        self.lbl.setWordWrap(True)
        root.addWidget(self.lbl)

        # Buttons
        bottom = QtWidgets.QHBoxLayout()
        self.btnCancel = QtWidgets.QPushButton("Huỷ")
        self.btnOk = QtWidgets.QPushButton("Xác nhận & Lưu")
        self.btnOk.setEnabled(False)
        bottom.addStretch(1)
        bottom.addWidget(self.btnCancel)
        bottom.addWidget(self.btnOk)
        root.addLayout(bottom)

        self.btnCancel.clicked.connect(self.reject)
        self.btnOk.clicked.connect(self._confirm)

    # ---------- Web ----------
    def _init_web(self):
        self.page = InterceptingPage(self.web_profile, self.web)
        self.page.credsCaptured.connect(self._on_creds_captured)
        self.web.setPage(self.page)

        # Script 1: hook bắt email/password
        js_capture = r"""
        (function(){
          if (window.__bbapp_hooked__) return; window.__bbapp_hooked__ = true;
          function pickEmail(){
            return document.querySelector('input[type="email"]')
                || document.querySelector('input[name*="email" i]')
                || document.querySelector('input[name*="user" i]');
          }
          function pickPass(){
            return document.querySelector('input[type="password"]')
                || document.querySelector('input[name*="pass" i]');
          }
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
        sc1 = QWebEngineScript()
        sc1.setName("bbapp-capture")
        sc1.setInjectionPoint(QWebEngineScript.DocumentReady)
        sc1.setWorldId(QWebEngineScript.MainWorld)
        sc1.setRunsOnSubFrames(True)
        sc1.setSourceCode(js_capture)
        self.web_profile.scripts().insert(sc1)

        # Script 2: (tùy) prefill & lock email khi edit_mode/preset_email
        if self._edit_mode and self._preset_email and self._lock_email:
            esc = self._preset_email.replace("\\", "\\\\").replace("'", "\\'")
            js_fill = f"""
            (function(){{
              function pickEmail(){{
                return document.querySelector('input[type="email"]')
                    || document.querySelector('input[name*="email" i]')
                    || document.querySelector('input[name*="user" i]');
              }}
              var e = pickEmail();
              if (e) {{
                 e.value = '{esc}';
                 e.dispatchEvent(new Event('input', {{bubbles:true}}));
                 e.readOnly = true;
                 e.style.backgroundColor = '#f7f7f7';
                 e.style.cursor = 'not-allowed';
               }}
            }})();
            """
            sc2 = QWebEngineScript()
            sc2.setName("bbapp-fill-email")
            sc2.setInjectionPoint(QWebEngineScript.DocumentReady)
            sc2.setWorldId(QWebEngineScript.MainWorld)
            sc2.setRunsOnSubFrames(True)
            sc2.setSourceCode(js_fill)
            self.web_profile.scripts().insert(sc2)

        self.web.urlChanged.connect(self._on_url_changed)
        self.web.loadFinished.connect(self._on_load_finished)

    # ---------- Data loading ----------
    def _load_servers(self):
        try:
            self._servers = self.cloud.get_servers()
            self.cbServer.clear()
            for s in self._servers:
                self.cbServer.addItem(str(s.get("name", f"#{s.get('id','')}")), s.get("id"))
            self._select_initial_server()
        except Exception as e:
            # Fallback: chỉ hiển thị server hiện tại nếu có
            self.cbServer.clear()
            if self._initial_server_name:
                self.cbServer.addItem(self._initial_server_name, None)
            self._set_error(f"Không tải được danh sách server: {e}")

        self._reeval_ok()

    def _select_initial_server(self):
        if self._initial_server_id is not None:
            idx = self.cbServer.findData(self._initial_server_id)
            if idx >= 0:
                self.cbServer.setCurrentIndex(idx)
                return
        if self._initial_server_name:
            idx2 = self.cbServer.findText(self._initial_server_name)
            if idx2 >= 0:
                self.cbServer.setCurrentIndex(idx2)

    # ---------- Nav ----------
    def _open_login(self):
        self._verified = False
        self.btnOk.setEnabled(False)
        self._set_info("Mở trang đăng nhập…")
        self.web.setUrl(QtCore.QUrl(LOGIN_URL))

    def _on_load_finished(self, ok: bool):
        if not ok:
            self._set_error("Không tải được trang. Kiểm tra mạng.")
            return
        self._set_info("Trang đã sẵn sàng. Vui lòng đăng nhập trực tiếp trong WebView.")

    def _on_url_changed(self, url: QtCore.QUrl):
        s = url.toString()
        parsed = urlparse(s)
        if parsed.netloc == PAY_HOST and parsed.path.startswith(SUCCESS_PATH):
            qs = parse_qs(parsed.query)
            if qs.get(SUCCESS_QS_KEY, [""])[0] == SUCCESS_QS_VAL:
                # Redirect thành công → chỉ chấp nhận đổi mật khẩu nếu hợp lệ
                if not self._password:
                    self._set_error("Chưa bắt được mật khẩu từ WebView. Hãy thử đăng nhập lại.")
                    self._verified = False
                    self._reeval_ok()
                    return

                # Ở chế độ sửa: email bắt buộc khớp
                if self._edit_mode:
                    if not self._email:
                        self._set_error("Không bắt được email; không thể xác nhận đổi mật khẩu. Bạn vẫn có thể đổi server.")
                        self._verified = False
                        self._reeval_ok()
                        return
                    if self._preset_email and self._email.strip().lower() != self._preset_email.lower():
                        self._set_error("Bạn đang đăng nhập email khác. Hãy đăng nhập đúng tài khoản cần sửa.")
                        self._verified = False
                        self._reeval_ok()
                        return

                # Hợp lệ
                self._verified = True
                self._set_ok("Đăng nhập thành công. Bạn có thể bấm 'Xác nhận & Lưu'.")
                self._reeval_ok()

    def _on_creds_captured(self, email: str, password: str):
        self._email = (email or "").strip()
        self._password = password
        # Không bật verified ở đây; verified chỉ bật khi redirect OK trong _on_url_changed

    # ---------- Helpers ----------
    def _current_sid(self) -> Optional[int]:
        try:
            val = self.cbServer.currentData()
            return int(val) if val is not None else None
        except Exception:
            return None

    def _server_changed(self) -> bool:
        cur_sid = self._current_sid()
        if self._initial_server_id is not None and cur_sid is not None:
            return int(cur_sid) != int(self._initial_server_id)
        # fallback theo tên nếu không có id
        cur_name = (self.cbServer.currentText() or "").strip()
        if self._initial_server_name:
            return cur_name != self._initial_server_name
        return False

    def _reeval_ok(self):
        if self._edit_mode:
            self.btnOk.setEnabled(bool(self._verified or self._server_changed()))
        else:
            self.btnOk.setEnabled(bool(self._verified))

    # ---------- Confirm ----------
    def _confirm(self):
        if self._edit_mode:
            # cho phép lưu nếu đã verified hoặc chỉ đổi server
            if not (self._verified or self._server_changed()):
                self._set_error("Bạn chưa đăng nhập lại và cũng chưa đổi server.")
                return
            self.accept()
            return

        # add_mode: phải verified
        if not self._verified:
            self._set_error("Chưa xác minh đăng nhập.")
            return
        if not self._password:
            self._set_error("Thiếu mật khẩu đã bắt được từ WebView.")
            return
        self.accept()

    # ---------- Result ----------
    def get_verified_payload(self) -> Optional[Dict]:
        """
        Trả về:
          - server_id: id server được chọn (có thể None nếu fallback)
          - server_name: tên server đang chọn (để client fallback khi chưa có server_id)
          - game_email: email bắt được (có thể rỗng nếu trang không in)
          - game_password: mật khẩu (chỉ có khi _verified=True)
        """
        sid = self._current_sid()
        sname = self.cbServer.currentText()
        return {
            "server_id": sid,
            "server_name": sname,
            "game_email": (self._email or ""),
            "game_password": (self._password if self._verified else "")
        }

    # ---------- Status texts ----------
    def _set_error(self, m: str):
        self.lbl.setStyleSheet("color:#c62828;")
        self.lbl.setText(m)

    def _set_ok(self, m: str):
        self.lbl.setStyleSheet("color:#2e7d32;")
        self.lbl.setText(m)

    def _set_info(self, m: str):
        self.lbl.setStyleSheet("color:#333;")
        self.lbl.setText(m)
