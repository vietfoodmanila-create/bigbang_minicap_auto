# minicap_worker.py
from __future__ import annotations
import os
import re
import time
import threading
import subprocess
from pathlib import Path
from typing import Optional, Tuple

def _run(cmd, timeout=8, text=True):
    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, startupinfo=startupinfo)
        out = p.stdout.decode(errors='ignore') if text else p.stdout
        err = p.stderr.decode(errors='ignore') if text else p.stderr
        return p.returncode, out, err
    except subprocess.TimeoutExpired:
        return 124, "" if text else b"", "timeout" if text else b"timeout"
    except Exception as e:
        return 125, "" if text else b"", (f"ERR:{e}" if text else f"ERR:{e}".encode())

def _adb_shell(adb, serial, *args, timeout=8, text=True):
    return _run([adb, "-s", serial, "shell", *args], timeout=timeout, text=text)

def _adb(adb, serial, *args, timeout=8, text=True):
    return _run([adb, "-s", serial, *args], timeout=timeout, text=text)

def _push_if_missing(adb, serial, local: Path, remote: str):
    code, out, _ = _adb_shell(adb, serial, "ls", "-l", remote, timeout=5)
    need = True
    size_local = local.stat().st_size if local.exists() else -1
    if code == 0 and out:
        try:
            last_line = out.strip().splitlines()[-1]
            m = re.search(rf"\s(\d+)\s.*{re.escape(remote)}\s*$", last_line)
            if m and int(m.group(1)) == size_local and size_local > 0:
                need = False
        except Exception:
            pass
    if need and local.exists():
        _adb(adb, serial, "push", str(local), remote, timeout=30, text=True)

def _detect_display_size(adb, serial) -> Tuple[int, int]:
    code, out, _ = _adb_shell(adb, serial, "wm", "size", timeout=5)
    if code == 0 and out and "Physical size" in out:
        m = re.search(r"Physical size:\s*(\d+)\s*x\s*(\d+)", out)
        if m:
            return int(m.group(1)), int(m.group(2))
    code, out, _ = _adb_shell(adb, serial, "dumpsys", "display", timeout=8)
    if code == 0 and out:
        m = re.search(r"deviceWidth=(\d+),\s*deviceHeight=(\d+)", out)
        if m:
            return int(m.group(1)), int(m.group(2))
    return 900, 1600

def _detect_rotation(adb, serial) -> int:
    # 0: portrait, 1: landscape, 2: reverse portrait, 3: reverse landscape
    code, out, _ = _adb_shell(adb, serial, "dumpsys", "input", timeout=5)
    if code == 0 and out:
        m = re.search(r"SurfaceOrientation:\s*(\d+)", out)
        if m:
            val = int(m.group(1))
            return {0: 0, 1: 90, 2: 180, 3: 270}.get(val, 0)
    return 0

def _detect_abi(adb, serial) -> str:
    code, out, _ = _adb_shell(adb, serial, "getprop", "ro.product.cpu.abi", timeout=5)
    return out.strip() if code == 0 else "arm64-v8a"

def _detect_sdk(adb, serial) -> str:
    code, out, _ = _adb_shell(adb, serial, "getprop", "ro.build.version.sdk", timeout=5)
    return out.strip() if code == 0 else "29"

def _find_vendor_minicap(abi: str, sdk: str) -> Tuple[Optional[Path], Optional[Path]]:
    base = Path("vendor") / "minicap"
    cand_bin = base / "bin" / abi / "minicap"
    cand_so = base / "shared" / f"android-{sdk}" / abi / "minicap.so"
    if not cand_so.exists() and (base / "shared").exists():
        sdks = []
        for p in (base / "shared").glob("android-*"):
            try:
                sdks.append(int(p.name.split("-", 1)[1]))
            except Exception:
                pass
        sdks.sort(reverse=True)
        for s in sdks:
            alt = base / "shared" / f"android-{s}" / abi / "minicap.so"
            if alt.exists():
                cand_so = alt
                break
    return (cand_bin if cand_bin.exists() else None,
            cand_so if cand_so.exists() else None)

def _atomic_write(path: Path, payload: bytes):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(payload)
    os.replace(tmp, path)

def _extract_valid_jpeg(payload: bytes) -> Optional[bytes]:
    if not payload:
        return None
    try:
        s = payload.find(b"\xff\xd8")   # SOI
        e = payload.rfind(b"\xff\xd9")  # EOI
        if s != -1 and e != -1 and e > s:
            return payload[s:e+2]
    except Exception:
        pass
    return None

class MinicapWorker(threading.Thread):
    """
    Worker đơn giản: mỗi vòng gọi minicap lấy 1 JPEG, ghi vào mailbox/last.jpg.
    Dùng 'adb exec-out' để tránh PTY làm hỏng dữ liệu nhị phân.
    """
    def __init__(self, adb_path: str, serial: str, mailbox_dir: Path,
                 virt_size=(900, 1600), jpeg_quality: int = 100,
                 force_rotation: Optional[int] = None):
        super().__init__(name=f"MinicapWorker-{serial}", daemon=True)
        self.adb_path = adb_path
        self.serial = serial
        self.mailbox_dir = Path(mailbox_dir)
        self.mailbox_dir.mkdir(parents=True, exist_ok=True)
        self.jpeg_quality = int(os.environ.get("BB_MINICAP_Q", str(jpeg_quality)))
        self.force_rotation = (int(os.environ["BB_MINICAP_FORCE_ROT"])
                               if "BB_MINICAP_FORCE_ROT" in os.environ
                               else force_rotation)
        self.virt_w, self.virt_h = virt_size
        self.stop_evt = threading.Event()
        self._last_frame_path = self.mailbox_dir / "last.jpg"
        try:
            for p in self.mailbox_dir.glob("*"):
                try:
                    p.unlink()
                except Exception:
                    pass
        except Exception:
            pass

    def request_stop(self):
        self.stop_evt.set()

    def frame_path(self) -> Path:
        return self._last_frame_path

    def read_latest_frame(self) -> Optional[bytes]:
        try:
            if self._last_frame_path.exists() and self._last_frame_path.stat().st_size > 0:
                return self._last_frame_path.read_bytes()
        except Exception:
            pass
        return None

    def _build_minicap_cmd(self, remote_bin: str, proj: str, use_exec_out: bool = True):
        # Dùng 'exec-out' để ra nhị phân sạch; kèm 'sh -c' để redirect stderr
        if use_exec_out:
            return [
                self.adb_path, "-s", self.serial, "exec-out",
                "sh", "-c",
                f"LD_LIBRARY_PATH=/data/local/tmp {remote_bin} -P {proj} -s -Q {self.jpeg_quality} 2>/dev/null"
            ]
        # Fallback: shell (ít khi cần)
        return [
            self.adb_path, "-s", self.serial, "shell",
            "LD_LIBRARY_PATH=/data/local/tmp", remote_bin,
            "-P", proj, "-s", "-Q", str(self.jpeg_quality)
        ]

    def run(self):
        abi = _detect_abi(self.adb_path, self.serial)
        sdk = _detect_sdk(self.adb_path, self.serial)
        real_w, real_h = _detect_display_size(self.adb_path, self.serial)
        rot_auto = _detect_rotation(self.adb_path, self.serial)
        rot = rot_auto if self.force_rotation is None else int(self.force_rotation)

        bin_path, so_path = _find_vendor_minicap(abi, sdk)
        remote_bin = "/data/local/tmp/minicap"
        remote_so = "/data/local/tmp/minicap.so"

        if bin_path and so_path:
            _push_if_missing(self.adb_path, self.serial, bin_path, remote_bin)
            _push_if_missing(self.adb_path, self.serial, so_path, remote_so)
            _adb_shell(self.adb_path, self.serial, "chmod", "0755", remote_bin)

        # Nếu muốn ảnh không bị resample, có thể đặt virt=real.
        # Ở đây giữ virt_size theo config (mặc định 900x1600) để khớp template.
        proj = f"{real_w}x{real_h}@{self.virt_w}x{self.virt_h}/{rot}"

        idle = 0.05
        use_exec_out = True
        while not self.stop_evt.is_set():
            try:
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

                cmd = self._build_minicap_cmd(remote_bin, proj, use_exec_out=use_exec_out)
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
                out, err = p.communicate(timeout=8)

                buf = _extract_valid_jpeg(out)
                if not buf:
                    # thử fallback sang 'shell' nếu exec-out gặp vấn đề đặc thù
                    if use_exec_out:
                        use_exec_out = False
                        time.sleep(0.2)
                        continue
                if buf and len(buf) > 512:
                    try:
                        _atomic_write(self._last_frame_path, buf)
                    except Exception:
                        pass
                else:
                    time.sleep(0.2)
                time.sleep(idle)
            except subprocess.TimeoutExpired:
                try:
                    p.kill()
                except Exception:
                    pass
                time.sleep(0.2)
            except Exception:
                time.sleep(0.2)
