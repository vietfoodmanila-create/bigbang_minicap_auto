import subprocess
import time
import logging
import os

logger = logging.getLogger(__name__)


class ADBClient:
    def __init__(self, device_id, adb_path="adb"):
        self.device_id = device_id
        self.adb_path = adb_path

        if not os.path.exists(self.adb_path):
            logger.error(f"ADB executable not found at the specified path: {self.adb_path}")
            raise FileNotFoundError(f"ADB not found at {self.adb_path}")

        self.screen_size = self._get_screen_size()

    def _execute(self, command, background=False):
        if not self.device_id:
            logger.error("ADB command failed: Device ID is not set.")
            return None

        cmd = [self.adb_path, "-s", self.device_id] + command
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            if background:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)
                return True
            else:
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, startupinfo=startupinfo,
                                        encoding='utf-8', errors='ignore')
                return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"ADB command failed: {' '.join(cmd)}. STDERR: {e.stderr}")
            return None
        except FileNotFoundError:
            logger.error(f"ADB executable could not be run from path: {self.adb_path}.")
            return None

    def shell(self, command):
        return self._execute(["shell", command])

    def _get_screen_size(self):
        output = self.shell("wm size")
        if output and "Physical size:" in output:
            try:
                size_str = output.split(":")[-1].strip()
                width, height = map(int, size_str.split('x'))
                logger.info(f"Detected screen size for {self.device_id}: {width}x{height}")
                return width, height
            except Exception as e:
                logger.error(f"Failed to parse screen size for {self.device_id}: {output}. Error: {e}")
        return None, None

    def tap(self, x, y):
        self.shell(f"input tap {int(x)} {int(y)}")

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {duration_ms}")

    def forward(self, local_port, remote_name="localabstract:minicap"):
        logger.info(f"Forwarding tcp:{local_port} to {remote_name}")
        return self._execute(["forward", f"tcp:{local_port}", remote_name])

    def remove_forward(self, local_port):
        self._execute(["forward", "--remove", f"tcp:{local_port}"])

    def start_minicap_service(self):
        self.stop_minicap_service()
        time.sleep(0.5)
        if not self.screen_size or not self.screen_size[0]:
            logger.error("Cannot start minicap without screen size.")
            return False

        width, height = self.screen_size
        projection = f"{width}x{height}@{width}x{height}/0"
        minicap_path = "/data/local/tmp/minicap"
        command = f"LD_LIBRARY_PATH=/data/local/tmp {minicap_path} -P {projection} -S"
        logger.info(f"Starting minicap service: {command}")

        success = self._execute(["shell", command], background=True)
        time.sleep(1.5)
        return True

    def stop_minicap_service(self):
        pids = self.shell("pgrep minicap")
        if pids:
            for pid in pids.splitlines():
                if pid.strip():
                    logger.info(f"Killing existing minicap process {pid.strip()}")
                    self.shell(f"kill {pid.strip()}")