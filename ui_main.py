# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import subprocess
import shutil
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict
import os
from datetime import datetime
import time
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import importlib

# Import các thư viện cần thiết cho Selenium
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
import requests
from module import resource_path
from PySide6.QtCore import Qt, QPoint, QSize,QRegularExpression
from PySide6.QtGui import QCloseEvent, QTextCursor, QIcon, QPixmap,QRegularExpressionValidator
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QTabWidget, QGroupBox, QFormLayout, QTextEdit, QLabel, QMessageBox, QPushButton,
    QAbstractItemView, QMenu, QLineEdit, QDialog, QDialogButtonBox, QInputDialog
)
from ui_auth import CloudClient
from ui_license import AccountBanner
from utils_crypto import encrypt
from ui_verify_game_login import VerifyGameLoginDialog
from ui_verify_game_login_webonly import VerifyGameLoginWebOnlyDialog


# ====== Cấu hình (SỬA ĐỔI) ======
# Import thêm các biến mới từ config.py
try:
    from config import NOX_ADB_PATH, LDPLAYER_ADB_PATH, EMULATOR_TYPE

    # Giữ lại ADB_PATH để tương thích
    ADB_PATH = Path(NOX_ADB_PATH)
except ImportError:
    # Fallback nếu config.py chưa được cập nhật
    NOX_ADB_PATH = r"D:\Program Files\Nox\bin\nox_adb.exe"
    LDPLAYER_ADB_PATH = r"D:\LDPlayer\LDPlayer9\dnadb.exe"
    EMULATOR_TYPE = "BOTH"
    ADB_PATH = Path(NOX_ADB_PATH)

DATA_ROOT = Path("data")
DATA_ROOT.mkdir(exist_ok=True)
DEFAULT_WIDTH = 450
DEFAULT_HEIGHT = 900

GAME_LOGIN_URL = "https://pay.bigbangthoikhong.vn/login?game_id=105"

ACC_HEADERS_VISIBLE = ["", "Email", "Xem", "Sửa", "Xóa"]
ACC_COL_CHECK, ACC_COL_EMAIL, ACC_COL_STATUS, ACC_COL_EDIT, ACC_COL_DELETE = range(5)

# Thêm cột checkbox cho DS Chúc phúc
BLESS_HEADERS_VISIBLE = ["", "Tên nhân vật", "Lần cuối chạy"]
BLESS_COL_CHECK, BLESS_COL_NAME, BLESS_COL_LAST = range(3)



# ---------------- Helpers & Dialogs (SỬA ĐỔI LOGIC NHẬN DIỆN) ----------------
def _run_quiet(cmd: list[str], timeout: int = 8) -> str:
    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, startupinfo=startupinfo,
                             encoding='utf-8', errors='ignore')
        return out.stdout
    except Exception:
        return ""


# Dán để thay thế hàm cũ trong ui_main.py

def list_adb_ports_with_status() -> dict[str, str]:
    """
    Quét và hợp nhất kết quả từ cả hai ADB của Nox và LDPlayer.
    Ưu tiên kết quả từ LDPlayer ADB nếu có sự trùng lặp để tránh nhận diện sai.
    """
    result: dict[str, str] = {}

    # 1. Quét bằng LDPlayer ADB trước
    try:
        if Path(LDPLAYER_ADB_PATH).exists():
            ld_text = _run_quiet([str(LDPLAYER_ADB_PATH), "devices"], timeout=6)
            for line in ld_text.splitlines():
                s = line.strip()
                if not s or s.startswith("List of devices"): continue
                if "emulator-" in s or "127.0.0.1:" in s:
                    parts = s.split()
                    device_id = parts[0]
                    status = parts[1] if len(parts) > 1 else "unknown"
                    result[device_id] = f"LDPlayer - {status}"
    except Exception as e:
        print(f"Lỗi khi quét LDPlayer ADB: {e}")

    # 2. Quét bằng Nox ADB
    try:
        if Path(NOX_ADB_PATH).exists():
            nox_text = _run_quiet([str(NOX_ADB_PATH), "devices"], timeout=6)
            for line in nox_text.splitlines():
                s = line.strip()
                if not s or s.startswith("List of devices"): continue
                if "emulator-" in s or "127.0.0.1:" in s:
                    parts = s.split()
                    device_id = parts[0]
                    # CHỈ THÊM NẾU MÁY ẢO NÀY CHƯA ĐƯỢC LDPLAYER NHẬN DIỆN
                    if device_id not in result:
                        status = parts[1] if len(parts) > 1 else "unknown"
                        result[device_id] = f"Nox - {status}"
    except Exception as e:
        print(f"Lỗi khi quét Nox ADB: {e}")

    return result


def list_known_ports_from_data() -> List[int]:
    ports: List[int] = []
    if not DATA_ROOT.exists(): return ports
    for p in DATA_ROOT.iterdir():
        if p.is_dir():
            try:
                ports.append(int(p.name))
            except Exception:
                pass
    return ports


def check_game_login_client_side(email: str, password: str) -> tuple[bool, str]:
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
    driver = None
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.get(GAME_LOGIN_URL)
        wait = WebDriverWait(driver, 20)
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.TAG_NAME, "iframe")))
        email_field = wait.until(EC.visibility_of_element_located((By.NAME, "username")))
        password_field = driver.find_element(By.NAME, "password")
        email_field.send_keys(email)
        password_field.send_keys(password)
        time.sleep(0.5)
        login_button = driver.find_element(By.XPATH, "//span[contains(text(), 'Đăng Nhập')]")
        login_button.click()
        driver.switch_to.default_content()
        WebDriverWait(driver, 15).until(lambda d: "login" not in d.current_url.lower())
        final_url = driver.current_url
        if "rechargepackage" in final_url.lower():
            return True, "Xác thực thành công!"
        else:
            return False, f"Chuyển hướng đến trang không mong đợi: {final_url}"
    except TimeoutException:
        try:
            if driver and (
                    "sai mật khẩu" in driver.page_source.lower() or "incorrect password" in driver.page_source.lower()):
                return False, "Thông tin đăng nhập không chính xác."
        except:
            pass
        return False, "Hết thời gian chờ, trang web không phản hồi như mong đợi."
    except Exception as e:
        return False, f"Lỗi Selenium: {e}"
    finally:
        if driver:
            driver.quit()


class AccountDialog(QDialog):
    def __init__(self, account_data: dict = None, parent=None):
        super().__init__(parent)
        self.account_data = account_data
        self.is_edit_mode = account_data is not None
        self.setWindowTitle("Sửa tài khoản" if self.is_edit_mode else "Thêm tài khoản mới")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        self.email_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.server_edit = QLineEdit()
        if self.is_edit_mode:
            self.email_edit.setText(self.account_data.get("game_email", ""))
            self.email_edit.setReadOnly(True)
            self.server_edit.setText(str(self.account_data.get("server", "")))
            self.password_edit.setPlaceholderText("Nhập mật khẩu mới nếu muốn thay đổi")
        else:
            self.email_edit.setPlaceholderText("Nhập email game")
            self.password_edit.setPlaceholderText("Nhập mật khẩu game")
            self.server_edit.setPlaceholderText("Nhập server (mặc định: 8)")
        form_layout.addRow("Email:", self.email_edit)
        form_layout.addRow("Mật khẩu:", self.password_edit)
        form_layout.addRow("Server:", self.server_edit)
        layout.addLayout(form_layout)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def get_data(self) -> dict:
        data = {"game_email": self.email_edit.text().strip().lower(),
                "game_password": self.password_edit.text().strip(), "server": self.server_edit.text().strip() or "8"}
        if self.is_edit_mode and not data["game_password"]: del data["game_password"]
        return data


class MainWindow(QMainWindow):
    def __init__(self, cloud: CloudClient):
        super().__init__()
        self.cloud = cloud
        self.setWindowTitle("BigBang Auto")
        app_icon = QIcon(resource_path("images/logo.ico"))
        self.setWindowIcon(app_icon)

        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self.setMinimumSize(420, 760)
        self.active_port: Optional[int] = None
        self.active_device_id: Optional[str] = None
        self.online_accounts: List[Dict] = []
        self.blessing_targets: List[Dict] = []
        self._is_closing = False

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0);
        main_layout.setSpacing(0)

        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(5, 5, 5, 5)

        logo_label = QLabel()
        pixmap = QPixmap(resource_path("images/logo.png"))
        logo_label.setPixmap(pixmap.scaled(QSize(32, 32), Qt.KeepAspectRatio, Qt.SmoothTransformation))

        self.banner = AccountBanner(self.cloud, controller=self, parent=self)
        header_layout.addWidget(self.banner, 1)

        main_layout.addWidget(header_widget)

        splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(splitter)

        top = QWidget();
        top_layout = QVBoxLayout(top)
        self.tbl_nox = QTableWidget(0, 5)
        self.tbl_nox.setHorizontalHeaderLabels(["Start", "Tên máy ảo", "Device ID", "Trạng thái", "Status"])
        self.tbl_nox.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents);
        self.tbl_nox.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_nox.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents);
        self.tbl_nox.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tbl_nox.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.tbl_nox.setSelectionMode(QAbstractItemView.SingleSelection);
        self.tbl_nox.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_nox.setEditTriggers(QAbstractItemView.NoEditTriggers);
        self.tbl_nox.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tbl_nox.customContextMenuRequested.connect(self._show_nox_context_menu)
        top_layout.addWidget(self.tbl_nox);
        splitter.addWidget(top)

        bottom = QWidget();
        bottom_layout = QVBoxLayout(bottom)
        self.tabs = QTabWidget()

        w_acc = QWidget();
        acc_layout = QVBoxLayout(w_acc);
        acc_toolbar = QHBoxLayout()
        self.chk_select_all_accs = QCheckBox("Chọn tất cả");
        self.btn_acc_add = QPushButton("Thêm tài khoản");
        self.btn_acc_refresh = QPushButton("Làm mới DS")
        acc_toolbar.addWidget(self.chk_select_all_accs);
        acc_toolbar.addStretch();
        acc_toolbar.addWidget(self.btn_acc_add);
        acc_toolbar.addWidget(self.btn_acc_refresh)
        acc_layout.addLayout(acc_toolbar)
        self.tbl_acc = QTableWidget(0, len(ACC_HEADERS_VISIBLE));
        self.tbl_acc.setHorizontalHeaderLabels(ACC_HEADERS_VISIBLE)
        self.tbl_acc.horizontalHeader().setSectionResizeMode(ACC_COL_CHECK, QHeaderView.ResizeToContents)
        self.tbl_acc.horizontalHeader().setSectionResizeMode(ACC_COL_STATUS, QHeaderView.ResizeToContents)
        self.tbl_acc.horizontalHeader().setSectionResizeMode(ACC_COL_EDIT, QHeaderView.ResizeToContents)
        self.tbl_acc.horizontalHeader().setSectionResizeMode(ACC_COL_DELETE, QHeaderView.ResizeToContents)
        self.tbl_acc.horizontalHeader().setSectionResizeMode(ACC_COL_EMAIL, QHeaderView.Stretch)

        self.tbl_acc.setEditTriggers(QAbstractItemView.NoEditTriggers);
        acc_layout.addWidget(self.tbl_acc);
        self.tabs.addTab(w_acc, "Accounts")

        w_feat = QWidget();
        feat_layout = QVBoxLayout(w_feat);
        grp = QGroupBox("Tính năng liên minh");
        form = QFormLayout(grp)
        # --- Gia nhập liên minh: TextBox + nút Sửa/Lưu ---
        row_gt = QWidget()
        row_gt_lay = QHBoxLayout(row_gt)
        row_gt_lay.setContentsMargins(0, 0, 0, 0)

        self.ed_guild_target = QLineEdit()
        self.ed_guild_target.setEnabled(False)  # mặc định khóa
        self.ed_guild_target.setMaxLength(12)  # tối đa 12 ký tự
        # Validator: không cho khoảng trắng
        self.ed_guild_target.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"\S{0,12}"), self.ed_guild_target)
        )
        # Tự làm sạch nếu người dùng paste có khoảng trắng / dài quá 12
        self.ed_guild_target.textChanged.connect(self._on_guild_text_changed)

        self.btn_guild_edit_save = QPushButton("Sửa")
        self.btn_guild_edit_save.setFixedWidth(56)
        self.btn_guild_edit_save.clicked.connect(self.on_guild_edit_save_clicked)

        row_gt_lay.addWidget(self.ed_guild_target, 1)
        row_gt_lay.addWidget(self.btn_guild_edit_save)

        form.addRow(QLabel("Gia nhập liên minh:"), row_gt)
        self.load_user_guild_target()
        self.chk_build = QCheckBox("Xây dựng liên minh / xem quảng cáo");
        self.chk_expedition = QCheckBox("Viễn chinh")
        self.chk_auto_leave = QCheckBox("Tự thoát liên minh sau khi thao tác xong");
        self.chk_bless = QCheckBox("Chúc phúc")
        form.addRow(self.chk_build);
        form.addRow(self.chk_expedition);
        form.addRow(self.chk_auto_leave);
        form.addRow(self.chk_bless)
        feat_layout.addWidget(grp);
        feat_layout.addStretch(1);
        self.tabs.addTab(w_feat, "Tính năng")

        w_bless = QWidget();
        bless_layout = QVBoxLayout(w_bless);
        grp_bconf = QGroupBox("Cấu hình chúc phúc");
        form_bconf = QFormLayout(grp_bconf)
        self.ed_bless_cooldown = QLineEdit();
        self.ed_bless_cooldown.setPlaceholderText("Giờ (ví dụ 8)")
        self.ed_bless_perrun = QLineEdit();
        self.ed_bless_perrun.setPlaceholderText("Số lượt mỗi lần (ví dụ 3)")
        form_bconf.addRow(QLabel("Giãn cách (giờ):"), self.ed_bless_cooldown);
        form_bconf.addRow(QLabel("Số lượt chúc mỗi lần:"), self.ed_bless_perrun)
        bless_layout.addWidget(grp_bconf)
        # Thanh công cụ DS Chúc phúc: checkbox "Chọn tất cả"
        bless_toolbar = QHBoxLayout()
        self.chk_select_all_bless = QCheckBox("Chọn tất cả")
        bless_toolbar.addWidget(self.chk_select_all_bless)
        bless_toolbar.addStretch()
        bless_layout.addLayout(bless_toolbar)

        self.tbl_bless = QTableWidget(0, len(BLESS_HEADERS_VISIBLE))
        self.tbl_bless.setHorizontalHeaderLabels(BLESS_HEADERS_VISIBLE)
        self.tbl_bless.horizontalHeader().setSectionResizeMode(BLESS_COL_CHECK, QHeaderView.ResizeToContents)
        self.tbl_bless.horizontalHeader().setSectionResizeMode(BLESS_COL_NAME, QHeaderView.Stretch)
        self.tbl_bless.horizontalHeader().setSectionResizeMode(BLESS_COL_LAST, QHeaderView.ResizeToContents)
        self.tbl_bless.setEditTriggers(QAbstractItemView.NoEditTriggers)
        bless_layout.addWidget(self.tbl_bless)
        bless_btns = QHBoxLayout();
        self.btn_bless_add = QPushButton("Thêm hàng");
        self.btn_bless_del = QPushButton("Xoá hàng")
        self.btn_bless_load = QPushButton("Load");
        self.btn_bless_save = QPushButton("Save")
        bless_btns.addWidget(self.btn_bless_add);
        bless_btns.addWidget(self.btn_bless_del);
        bless_btns.addStretch(1);
        bless_btns.addWidget(self.btn_bless_load);
        bless_btns.addWidget(self.btn_bless_save)
        bless_layout.addLayout(bless_btns);
        self.tabs.addTab(w_bless, "DS Chúc phúc")

        bottom_layout.addWidget(self.tabs);
        bottom_layout.addWidget(QLabel("Log:"))
        self.log = QTextEdit();
        self.log.setReadOnly(True);
        bottom_layout.addWidget(self.log, 1)
        splitter.addWidget(bottom);
        splitter.setSizes([250, 670])

        self.tbl_nox.itemSelectionChanged.connect(self.on_nox_selection_changed)
        self.btn_acc_add.clicked.connect(self.on_add_account_clicked);
        self.btn_acc_refresh.clicked.connect(self.load_and_sync_accounts);
        self.chk_select_all_accs.toggled.connect(self.on_select_all_accounts)

        self.btn_bless_add.clicked.connect(self.bless_add_online);
        self.btn_bless_del.clicked.connect(self.bless_del_online);
        self.btn_bless_load.clicked.connect(self.load_bless_online);
        self.btn_bless_save.clicked.connect(self.save_bless_config_online)
        self.chk_select_all_bless.toggled.connect(self.on_select_all_bless)

        self.refresh_nox()
        if self.tbl_nox.rowCount() > 0: self.tbl_nox.selectRow(0)

    def closeEvent(self, event: QCloseEvent):
        self._is_closing = True;
        super().closeEvent(event)

    # ── tô màu nền cột Email theo status trong self.tbl_acc ──
    def apply_status_color_to_account_table(self):
        from PySide6.QtGui import QColor, QBrush
        tv = self.tbl_acc  # bảng tài khoản
        email_col = 1  # cột Email
        status_col = None  # không có cột status hiển thị -> đọc từ self.online_accounts

        rows = tv.rowCount()
        accs = getattr(self, "online_accounts", [])  # danh sách tài khoản đã load từ API
        for r in range(rows):
            st = "ok"
            if r < len(accs):
                st = str(accs[r].get("status") or "ok").lower()

            it = tv.item(r, email_col)
            if not it:
                continue

            if st == "ok":
                it.setBackground(QBrush(QColor(220, 245, 230)))  # xanh nhạt
            else:
                it.setBackground(QBrush(QColor(255, 225, 225)))  # đỏ nhạt

    def refresh_nox(self):
        adb_map = list_adb_ports_with_status()
        self.tbl_nox.setRowCount(0)
        for device_id, status_str in sorted(adb_map.items()):
            r = self.tbl_nox.rowCount()
            self.tbl_nox.insertRow(r)
            chk = QCheckBox()
            self.tbl_nox.setCellWidget(r, 0, chk)

            parts = status_str.split(' - ')
            emulator_name = parts[0]
            status = parts[1] if len(parts) > 1 else "unknown"

            items = [QTableWidgetItem(f"{emulator_name}"), QTableWidgetItem(device_id),
                     QTableWidgetItem(status),
                     QTableWidgetItem("IDLE")]

            for i, it in enumerate(items, start=1):
                it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                if i in (2, 3): it.setTextAlignment(Qt.AlignCenter)
                self.tbl_nox.setItem(r, i, it)

    def get_current_device_id(self) -> Optional[str]:
        row = self.tbl_nox.currentRow()
        if row < 0: return None
        it = self.tbl_nox.item(row, 2)
        return it.text() if it else None

    def _show_nox_context_menu(self, pos: QPoint):
        pass

    def _delete_offline_instance(self, row: int, port: int):
        pass

    def on_nox_selection_changed(self):
        device_id = self.get_current_device_id()
        if device_id is None:
            self.tbl_acc.setRowCount(0);
            self.tbl_bless.setRowCount(0);
            return
        if device_id != self.active_device_id:
            self.active_device_id = device_id
            self.log_msg(f"Đã chọn máy ảo: {device_id}.")
            self.load_and_sync_accounts()
            self.load_bless_online()

    def load_and_sync_accounts(self):
        if self.active_device_id is None:
            self.online_accounts = []
            self.populate_accounts_table()
            return
        try:
            # BƯỚC 1: Lưu trạng thái các checkbox hiện tại
            checked_emails = set()
            for row in range(self.tbl_acc.rowCount()):
                widget = self.tbl_acc.cellWidget(row, ACC_COL_CHECK)
                checkbox = widget.findChild(QCheckBox) if widget else None
                if checkbox and checkbox.isChecked():
                    email_item = self.tbl_acc.item(row, ACC_COL_EMAIL)
                    if email_item:
                        checked_emails.add(email_item.text())

            self.log_msg("Đang tải và làm mới danh sách tài khoản từ server...")
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.online_accounts = self.cloud.get_game_accounts()

            # BƯỚC 2: Truyền danh sách đã lưu vào hàm populate
            self.populate_accounts_table(checked_emails)
            self.apply_status_color_to_account_table()
            self.log_msg(f"Đã làm mới {len(self.online_accounts)} tài khoản.")
        except Exception as e:
            self.online_accounts = []
            self.populate_accounts_table()
            self.log_msg(f"Lỗi tải và làm mới DS tài khoản: {e}")
            QMessageBox.critical(self, "Lỗi API", f"Không thể tải danh sách tài khoản:\n{e}")
        finally:
            QApplication.restoreOverrideCursor()

    def load_accounts_current_port(self):
        self.load_and_sync_accounts()
    def _on_guild_text_changed(self, s: str):
        """
        Làm sạch khi người dùng paste: loại bỏ mọi khoảng trắng và cắt 12 ký tự.
        (Validator đã chặn nhập mới, nhưng vẫn xử lý trường hợp paste.)
        """
        s2 = "".join(ch for ch in (s or "") if not ch.isspace())
        if s2 != s or len(s2) > 12:
            self.ed_guild_target.blockSignals(True)
            self.ed_guild_target.setText(s2[:12])
            self.ed_guild_target.blockSignals(False)

    def load_user_guild_target(self):
        try:
            val = self.cloud.get_user_config("guild_target")  # <- giờ là string
            self.ed_guild_target.blockSignals(True)
            self.ed_guild_target.setText(val)
            self.ed_guild_target.blockSignals(False)
            self.log_msg(f"[DBG] guild_target loaded = {repr(val)}")
        except Exception as e:
            self.ed_guild_target.blockSignals(True)
            self.ed_guild_target.setText("")
            self.ed_guild_target.blockSignals(False)
            self.log_msg(f"Lỗi tải guild_target: {e}")

        self.ed_guild_target.setEnabled(False)
        self.btn_guild_edit_save.setText("Sửa")

    def on_guild_edit_save_clicked(self):
        """
        Nhấn 'Sửa' -> bật nhập, đổi nút thành 'Lưu'.
        Nhấn 'Lưu' -> gọi API set_user_config, khóa nhập, đổi nút về 'Sửa'.
        """
        if self.btn_guild_edit_save.text() == "Sửa":
            self.ed_guild_target.setEnabled(True)
            self.ed_guild_target.setFocus()
            self.btn_guild_edit_save.setText("Lưu")
            return

        # Trường hợp đang ở 'Lưu'
        val = (self.ed_guild_target.text() or "").strip()
        if " " in val:
            QMessageBox.warning(self, "Cảnh báo",
                                "Tên liên minh không được chứa khoảng trắng.")
            return
        if len(val) > 12:
            val = val[:12]
            self.ed_guild_target.setText(val)

        try:
            resp = self.cloud.set_user_config("guild_target", val)
            self.log_msg(f"Đã lưu guild_target='{val}'. RESP={resp}")
            self.ed_guild_target.setEnabled(False)
            self.btn_guild_edit_save.setText("Sửa")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi API",
                                 f"Không thể lưu guild_target:\n{e}")

    def populate_accounts_table(self, checked_emails: set = None):
        # Sử dụng một set rỗng làm giá trị mặc định an toàn
        if checked_emails is None:
            checked_emails = set()

        self.tbl_acc.setRowCount(0)
        for row_data in self.online_accounts:
            row = self.tbl_acc.rowCount()
            self.tbl_acc.insertRow(row)
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_box = QCheckBox()

            # BƯỚC 3: Khôi phục trạng thái checkbox
            email = row_data.get('game_email', '')
            if email in checked_emails:
                chk_box.setChecked(True)

            chk_layout.addWidget(chk_box)
            chk_layout.setAlignment(Qt.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self.tbl_acc.setCellWidget(row, ACC_COL_CHECK, chk_widget)
            self.tbl_acc.setItem(row, ACC_COL_EMAIL, QTableWidgetItem(email))

            btn_info = QPushButton("🔍")
            btn_info.setFixedSize(32, 32)
            btn_info.setToolTip("Xem chi tiết thông tin")
            status = row_data.get('status', 'ok')
            if status == 'ok':
                btn_info.setStyleSheet("background-color: #e8f5e9; color: #388e3c;")
            else:
                btn_info.setStyleSheet("background-color: #f5f5f5; color: #616161;")
            btn_info.clicked.connect(lambda c, r=row: self.on_info_account(r))
            self.tbl_acc.setCellWidget(row, ACC_COL_STATUS, btn_info)

            btn_edit = QPushButton("✏️")
            btn_edit.setFixedSize(32, 32)
            btn_edit.setToolTip("Sửa thông tin tài khoản")
            btn_edit.setStyleSheet("background-color: #e3f2fd; color: #1976d2;")
            btn_edit.clicked.connect(lambda c, r=row: self.on_edit_account(r))
            self.tbl_acc.setCellWidget(row, ACC_COL_EDIT, btn_edit)

            btn_delete = QPushButton("🗑️")
            btn_delete.setFixedSize(32, 32)
            btn_delete.setToolTip("Xóa tài khoản khỏi danh sách")
            btn_delete.setStyleSheet("background-color: #ffebee; color: #c62828;")
            btn_delete.clicked.connect(lambda c, r=row: self.on_delete_account(r))
            self.tbl_acc.setCellWidget(row, ACC_COL_DELETE, btn_delete)

        self.log_msg(f"Đã hiển thị {len(self.online_accounts)} tài khoản.")

    def on_add_account_clicked(self):
        dlg = VerifyGameLoginDialog(parent=self, default_mode="FORM")  # hoặc "WEB" nếu bạn muốn mặc định
        if dlg.exec() != QDialog.Accepted:
            return
        verified = dlg.get_verified_data()
        if not verified:
            QMessageBox.warning(self, "Chưa xác minh", "Bạn chưa hoàn tất đăng nhập thành công.")
            return

        email = verified.get("game_email", "")
        password = verified.get("game_password", "")
        server = verified.get("server", "")

        if not email or not password:
            QMessageBox.warning(self, "Thiếu thông tin", "Thiếu email hoặc mật khẩu sau xác minh.")
            return

        existing_emails = [acc.get('game_email', '').lower() for acc in getattr(self, "online_accounts", [])]
        if email.lower() in existing_emails:
            QMessageBox.warning(self, "Tài khoản đã tồn tại", f"Tài khoản '{email}' đã có trong danh sách.")
            self.log_msg(f"Thêm bị hủy: {email} đã tồn tại.")
            return

        try:
            token_data = self.cloud.load_token()
            user_login_email = getattr(token_data, "email", None) if token_data else None
            if not user_login_email:
                QMessageBox.critical(self, "Lỗi", "Không tìm thấy email người dùng để tạo khóa mã hóa.")
                return

            encrypted_password = encrypt(password, user_login_email)
            data_to_send = {"game_email": email, "game_password": encrypted_password, "server": server or None}

            self.log_msg("Xác minh OK. Mã hoá & gửi dữ liệu lên server…")
            self.cloud.add_game_account(data_to_send)

            self.log_msg("Thêm tài khoản thành công. Đang đồng bộ…")
            self.load_and_sync_accounts()

        except Exception as e:
            self.log_msg(f"Lỗi khi thêm tài khoản: {e}")
            QMessageBox.critical(self, "Lỗi API", f"Không thể thêm tài khoản:\n{e}")

    def open_game_web_login(self, parent):
        """
        Mở lại dialog đăng nhập game (giống khi Thêm tài khoản) và trả về:
          { "ok": bool, "email": str|None, "password": str|None, "message": str }
        Chỉ phục vụ việc xác thực lại mật khẩu mới (client-side).
        """
        from PySide6 import QtWidgets

        # Tìm dialog thêm tài khoản mà bạn đang dùng (giữ nguyên logic gốc)
        try:
            # Nếu AccountDialog ở module khác, đảm bảo đã import ở đầu file ui_main.py
            dlg = AccountDialog(parent=parent)
        except NameError:
            QtWidgets.QMessageBox.critical(parent if isinstance(parent, QtWidgets.QWidget) else None,
                                           "Thiếu AccountDialog",
                                           "Không tìm thấy AccountDialog. Vui lòng import hoặc điều chỉnh tên lớp.")
            return {"ok": False, "email": None, "password": None, "message": "AccountDialog không khả dụng"}

        # Nếu dialog của bạn có API đặt chế độ "login-only" thì tận dụng (không bắt buộc)
        if hasattr(dlg, "set_mode"):
            try:
                dlg.set_mode("login_only")
            except Exception:
                pass

        # Gợi ý: nếu biết email đang sửa, có thể prefill (tuỳ AccountDialog có hỗ trợ hay không)
        expected_email = None
        try:
            expected_email = getattr(parent, "account", {}).get("game_email")
        except Exception:
            expected_email = None
        if expected_email and hasattr(dlg, "prefill_email"):
            try:
                dlg.prefill_email(expected_email)
            except Exception:
                pass

        rc = dlg.exec()
        if rc == QtWidgets.QDialog.Accepted:
            # Dùng đúng API cũ của bạn để lấy dữ liệu
            try:
                data = dlg.get_data()
            except Exception:
                data = {}
            email = (data.get("game_email") or "").strip()
            password = data.get("game_password")
            if email and password:
                return {"ok": True, "email": email, "password": password, "message": ""}
            return {"ok": False, "email": email or None, "password": None, "message": "Thiếu email hoặc mật khẩu."}

        return {"ok": False, "email": None, "password": None, "message": "Hủy bởi người dùng."}

    def on_add_account_clicked(self):
        # Yêu cầu đã đăng nhập Cloud trước (self.cloud)
        dlg = VerifyGameLoginWebOnlyDialog(self.cloud, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        data = dlg.get_verified_payload()
        if not data:
            QMessageBox.warning(self, "Chưa xác minh", "Bạn chưa hoàn tất đăng nhập.")
            return

        email = data.get("game_email") or ""  # có thể rỗng nếu trang không in email
        password = data.get("game_password") or ""
        server_id = data.get("server_id")

        if not password or not server_id:
            QMessageBox.warning(self, "Thiếu dữ liệu", "Thiếu mật khẩu hoặc server.")
            return

        # Nếu không bắt được email từ web, hỏi người dùng xác nhận email sẽ lưu
        if not email:
            email, ok = QInputDialog.getText(self, "Nhập email game", "Email dùng để đăng nhập:")
            if not ok or not email.strip():
                return
            email = email.strip()

        existing_emails = [acc.get('game_email', '').lower() for acc in getattr(self, "online_accounts", [])]
        if email.lower() in existing_emails:
            QMessageBox.warning(self, "Tài khoản đã tồn tại", f"Tài khoản '{email}' đã có trong danh sách.")
            self.log_msg(f"Huỷ thêm: {email} đã tồn tại.")
            return

        try:
            token_data = self.cloud.load_token()
            owner_email = getattr(token_data, "email", None) if token_data else None
            if not owner_email:
                QMessageBox.critical(self, "Lỗi", "Không tìm thấy email người dùng để tạo khoá mã hoá.")
                return

            encrypted = encrypt(password, owner_email)
            payload = {"game_email": email, "game_password": encrypted, "server_id": server_id}

            self.log_msg("Đăng nhập web OK. Đang mã hoá và gửi lên server…")
            self.cloud.add_game_account(payload)  # giữ nguyên method cũ, chỉ khác payload có server_id

            self.log_msg("Thêm tài khoản thành công. Làm mới danh sách…")
            self.load_and_sync_accounts()
        except Exception as e:
            self.log_msg(f"Lỗi thêm tài khoản: {e}")
            QMessageBox.critical(self, "Lỗi API", f"Không thể thêm tài khoản:\n{e}")

    def on_info_account(self, row):
        from datetime import datetime
        account = self.online_accounts[row]

        def fmt_dt(s):
            try:
                return datetime.fromisoformat(s).strftime('%d/%m/%Y %H:%M:%S') if s else "N/A"
            except Exception:
                return s or "N/A"

        def fmt_d(s):
            try:
                return datetime.fromisoformat(s).strftime('%d/%m/%Y') if s else "N/A"
            except Exception:
                return s or "N/A"

        server_name = account.get('server_name') or account.get('server') or "N/A"
        server_id = account.get('server_id')
        server_line = f"{server_name}" if server_id else server_name

        status = str(account.get('status', 'N/A'))
        color = 'green' if status.lower() == 'ok' else 'red'

        info = (
            f"<b>Email:</b> {account.get('game_email', 'N/A')}<br>"
            f"<b>Server:</b> {server_line}<br>"
            f"<b>Trạng thái:</b> <span style='color:{color};'>{status}</span><br><br>"
            f"<b>Xây dựng cuối:</b> {fmt_d(account.get('last_build_date'))}<br>"
            f"<b>Viễn chinh cuối:</b> {fmt_dt(account.get('last_expedition_time'))}<br>"
            f"<b>Rời LM cuối:</b> {fmt_dt(account.get('last_leave_time'))}<br>"
            f"<b>Chúc phúc:</b> {account.get('last_bless_info', 'N/A')}"
        )
        QMessageBox.information(self, "Thông tin tài khoản", info)

    def on_edit_account(self, row: int):
        acc = self.online_accounts[row]
        current_email = (acc.get('game_email') or '').strip()
        initial_sid = acc.get('server_id')
        initial_sname = (acc.get('server_name') or acc.get('server') or '').strip()

        dlg = VerifyGameLoginWebOnlyDialog(
            self.cloud,
            parent=self,
            edit_mode=True,  # bật chế độ sửa
            preset_email=current_email,  # email phải khớp khi đăng nhập
            initial_server_id=initial_sid,  # chọn sẵn server hiện tại
            initial_server_name=initial_sname,
            lock_email=True  # (tùy) chặn sửa email trên trang login
        )
        if dlg.exec() != QDialog.Accepted:
            return

        data = dlg.get_verified_payload() or {}

        payload = {}

        # Server (ưu tiên id, fallback theo tên để tương thích DB cũ varchar(50))
        sid = data.get('server_id')
        sname = (data.get('server_name') or '').strip()

        if sid is not None:
            if initial_sid is None or int(sid) != int(initial_sid):
                payload['server_id'] = int(sid)
        else:
            if sname and sname != initial_sname:
                payload['server'] = sname

        # Mật khẩu (chỉ khi người dùng đã đăng nhập web thành công)
        new_plain = data.get('game_password') or ''
        if new_plain:
            try:
                token_data = self.cloud.load_token()
                owner_email = getattr(token_data, "email", None) if token_data else None
                if not owner_email:
                    QMessageBox.critical(self, "Lỗi", "Không tìm thấy email người dùng để tạo khoá mã hoá.")
                    return
                payload['game_password'] = encrypt(new_plain, owner_email)
                payload['game_email'] = current_email
            except Exception as e:
                QMessageBox.critical(self, "Lỗi mã hoá", f"Không thể mã hoá mật khẩu mới:\n{e}")
                return

        if not payload:
            QMessageBox.information(self, "Thông báo", "Bạn chưa thay đổi gì.")
            return

        try:
            self.cloud.update_game_account(int(acc.get('id')), payload)
            self.log_msg("Cập nhật tài khoản thành công. Đang làm mới danh sách…")
            self.load_and_sync_accounts()
        except Exception as e:
            QMessageBox.critical(self, "Lỗi API", f"Không thể cập nhật tài khoản:\n{e}")
    def on_delete_account(self, row):
        account = self.online_accounts[row]
        reply = QMessageBox.question(self, 'Xác nhận xóa',
                                     f"Bạn có chắc muốn xóa tài khoản '{account['game_email']}' khỏi danh sách?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.log_msg(f"Đang xóa tài khoản {account['game_email']}...")
            try:
                self.cloud.delete_game_account(account['id'])
                self.log_msg("Xóa thành công! Đang làm mới danh sách...");
                self.load_accounts_current_port()
            except Exception as e:
                self.log_msg(f"Lỗi khi xóa: {e}");
                QMessageBox.critical(self, "Lỗi", f"Không thể xóa tài khoản:\n{e}")

    def on_select_all_accounts(self, checked):
        for row in range(self.tbl_acc.rowCount()):
            widget = self.tbl_acc.cellWidget(row, ACC_COL_CHECK)
            if widget and (chk_box := widget.findChild(QCheckBox)): chk_box.setChecked(checked)

    def on_select_all_bless(self, checked: bool):
        for row in range(self.tbl_bless.rowCount()):
            w = self.tbl_bless.cellWidget(row, BLESS_COL_CHECK)
            if not w:
                continue
            cb = w.findChild(QCheckBox)
            if cb:
                cb.setChecked(checked)

    def load_bless_online(self):
        if self.active_device_id is None:
            return
        try:
            self.log_msg("Đang tải cấu hình và DS Chúc phúc từ server.")
            QApplication.setOverrideCursor(Qt.WaitCursor)

            # Nhớ những mục đang check để khôi phục sau khi reload
            selected_names = set()
            for r in range(self.tbl_bless.rowCount()):
                w = self.tbl_bless.cellWidget(r, BLESS_COL_CHECK)
                cb = w.findChild(QCheckBox) if w else None
                if cb and cb.isChecked():
                    it_name = self.tbl_bless.item(r, BLESS_COL_NAME)
                    if it_name:
                        selected_names.add(it_name.text().strip())

            # Load config
            config = self.cloud.get_blessing_config()
            self.ed_bless_cooldown.setText(str(config.get("cooldown_hours", 8)))
            self.ed_bless_perrun.setText(str(config.get("per_run", 3)))

            # Load targets (toàn bộ cho UI)
            self.blessing_targets = self.cloud.get_blessing_targets(fetch_all=True)

            # Đổ bảng
            self.tbl_bless.setRowCount(0)
            for item in self.blessing_targets:
                r = self.tbl_bless.rowCount()
                self.tbl_bless.insertRow(r)

                # Cột checkbox
                chk_widget = QWidget()
                lay = QHBoxLayout(chk_widget)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setAlignment(Qt.AlignCenter)
                cb = QCheckBox()
                # Khôi phục tick nếu trước đó đã chọn
                if (item.get("target_name") or "").strip() in selected_names:
                    cb.setChecked(True)
                lay.addWidget(cb)
                self.tbl_bless.setCellWidget(r, BLESS_COL_CHECK, chk_widget)

                # Cột tên (gắn id vào UserRole)
                name = item.get("target_name", "")
                it_name = QTableWidgetItem(name)
                try:
                    it_name.setData(Qt.UserRole, int(item.get("id") or 0))
                except Exception:
                    it_name.setData(Qt.UserRole, 0)
                self.tbl_bless.setItem(r, BLESS_COL_NAME, it_name)

                # Cột lần cuối
                last_run_str = item.get("last_blessed_run_at", "")
                if last_run_str:
                    try:
                        dt = datetime.fromisoformat(last_run_str)
                        last_run_str = dt.strftime("%d/%m/%Y %H:%M")
                    except Exception:
                        pass
                self.tbl_bless.setItem(r, BLESS_COL_LAST, QTableWidgetItem(last_run_str))

            self.log_msg(f"Đã tải {len(self.blessing_targets)} mục tiêu Chúc phúc.")
        except Exception as e:
            detail = ""
            try:
                resp = getattr(e, "response", None)
                if resp is not None:
                    try:
                        detail = f" [HTTP {resp.status_code}] {resp.json()}"
                    except Exception:
                        detail = f" [HTTP {resp.status_code}] {resp.text[:200]}"
            except Exception:
                pass
            self.log_msg(f"Lỗi tải DS Chúc phúc: {e}{detail}")
            QMessageBox.critical(self, "Lỗi API", f"Không thể tải dữ liệu Chúc phúc:\n{e}{detail}")
        finally:
            QApplication.restoreOverrideCursor()

    def save_bless_config_online(self):
        if self.active_device_id is None: return
        try:
            cooldown = int(self.ed_bless_cooldown.text().strip() or 0)
            per_run = int(self.ed_bless_perrun.text().strip() or 0)
            data = {"cooldown_hours": cooldown, "per_run": per_run}
            self.log_msg("Đang lưu cấu hình Chúc phúc lên server...")
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.cloud.update_blessing_config(data)
            self.log_msg("Lưu cấu hình thành công!")
            QMessageBox.information(self, "Thành công", "Đã lưu cấu hình Chúc phúc.")
        except ValueError:
            QMessageBox.warning(self, "Lỗi", "Giãn cách và Số lượt phải là số.")
        except Exception as e:
            self.log_msg(f"Lỗi lưu cấu hình Chúc phúc: {e}");
            QMessageBox.critical(self, "Lỗi API", f"Không thể lưu cấu hình:\n{e}")
        finally:
            QApplication.restoreOverrideCursor()

    def bless_add_online(self):
        if self.active_device_id is None: return
        text, ok = QInputDialog.getText(self, 'Thêm mục tiêu', 'Nhập tên nhân vật cần chúc phúc:')
        if ok and (target_name := text.strip()):
            self.log_msg(f"Đang thêm mục tiêu '{target_name}'...")
            try:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                self.cloud.add_blessing_target(target_name)
                self.log_msg("Thêm thành công! Đang làm mới danh sách...");
                self.load_bless_online()
            except Exception as e:
                self.log_msg(f"Lỗi thêm mục tiêu: {e}");
                QMessageBox.critical(self, "Lỗi API", f"Không thể thêm mục tiêu:\n{e}")
            finally:
                QApplication.restoreOverrideCursor()

    def bless_del_online(self):
        if self.active_device_id is None: return
        selected_rows = sorted({i.row() for i in self.tbl_bless.selectedIndexes()})
        if not selected_rows: QMessageBox.information(self, "Thông báo",
                                                      "Vui lòng chọn một hoặc nhiều mục tiêu để xóa."); return
        targets_to_delete = [self.blessing_targets[r] for r in selected_rows]
        names_to_delete = ", ".join([t.get('target_name', '') for t in targets_to_delete])
        reply = QMessageBox.question(self, 'Xác nhận xóa', f"Bạn có chắc muốn xóa các mục tiêu:\n{names_to_delete}?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.log_msg(f"Đang xóa {len(targets_to_delete)} mục tiêu...")
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                for target in targets_to_delete:
                    if target_id := target.get('id'): self.cloud.delete_blessing_target(target_id)
                self.log_msg("Xóa thành công! Đang làm mới danh sách...");
                self.load_bless_online()
            except Exception as e:
                self.log_msg(f"Lỗi xóa mục tiêu: {e}");
                QMessageBox.critical(self, "Lỗi API", f"Không thể xóa mục tiêu:\n{e}")
            finally:
                QApplication.restoreOverrideCursor()

    def load_bless_current_port(self):
        self.load_bless_online()

    def save_bless_current_port(self):
        self.save_bless_config_online()

    def bless_add(self):
        self.bless_add_online()

    def bless_del(self):
        self.bless_del_online()

    def log_msg(self, msg: str):
        if self._is_closing or not hasattr(self, 'log') or self.log is None:
            print(f"(LOG-STDOUT) {msg}")
            return
        try:
            self.log.moveCursor(QTextCursor.MoveOperation.Start)
            self.log.insertPlainText(msg + "\n")
        except RuntimeError:
            print(f"(LOG-STDOUT-ERR) {msg}")

    def accounts_path_for_port(self, port: int) -> Path:
        d = DATA_ROOT / str(port);
        d.mkdir(parents=True, exist_ok=True);
        return d / "accounts.txt"


def main():
    app = QApplication(sys.argv)
    from ui_auth import CloudClient
    w = MainWindow(cloud=CloudClient())
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()