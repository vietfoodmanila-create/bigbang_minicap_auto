# -*- coding: utf-8 -*-


import argparse
import os
import sys
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Tuple, List, Optional

# ====== MẶC ĐỊNH THEO YÊU CẦU ======
DEFAULT_ADB_PATH = r"D:\Program Files\Nox\bin\nox_adb.exe"
DEFAULT_DEVICE   = "127.0.0.1:62025"

# ====== HEURISTIC NGƯỠNG ======
MIN_TOTAL_NODES_OK = 50            # >= 50 node thì có "độ giàu" nhất định
MIN_ID_OR_DESC_OK  = 10            # >= 10 node có resource-id hoặc content-desc
LOW_TOTAL_NODES    = 20            # < 20 node thường là "mù" (SurfaceView/UnityPlayer)
XML_REMOTE_PATH    = "/sdcard/view.xml"
XML_LOCAL_PATH     = "view.xml"


def run_adb(adb_path: str, device: Optional[str], args: List[str], check=True, capture_output=False, text=False):
    """
    Chạy lệnh ADB với adb_path và -s device (nếu có).
    """
    cmd = [adb_path]
    if device:
        cmd += ["-s", device]
    cmd += args
    try:
        return subprocess.run(
            cmd,
            check=check,
            capture_output=capture_output,
            text=text
        )
    except subprocess.CalledProcessError as e:
        print(f"[ERR] ADB error: {' '.join(cmd)}\nReturnCode={e.returncode}\nOutput={e.output}\nStderr={e.stderr}", file=sys.stderr)
        if check:
            sys.exit(2)
        return e


def ensure_device_connected(adb_path: str, device: Optional[str]) -> None:
    """
    Đảm bảo thiết bị hiển thị trong 'adb devices'. Với Nox, nếu chưa thấy, tự thử 'adb connect'.
    """
    print("[*] Kiểm tra thiết bị ADB ...")
    out = run_adb(adb_path, None, ["devices"], check=False, capture_output=True, text=True)
    if out.returncode != 0:
        print("[WARN] 'adb devices' lỗi, vẫn tiếp tục thử connect (nếu có device dạng host:port)...")

    listing = out.stdout if out and out.stdout else ""
    if device and device in listing and "\tdevice" in listing:
        print(f"[OK] Đã thấy thiết bị: {device}")
        return

    # Nếu device ở dạng host:port (Nox) → thử adb connect
    if device and (":" in device):
        print(f"[*] Thử 'adb connect {device}' ...")
        conn = run_adb(adb_path, None, ["connect", device], check=False, capture_output=True, text=True)
        if conn.returncode == 0:
            # Kiểm lại
            out2 = run_adb(adb_path, None, ["devices"], check=False, capture_output=True, text=True)
            if out2 and device in (out2.stdout or "") and "\tdevice" in (out2.stdout or ""):
                print(f"[OK] Đã connect và thấy thiết bị: {device}")
                return

    print("[WARN] Không xác nhận được thiết bị trong 'adb devices'. Vẫn tiếp tục thử dump.", file=sys.stderr)


def dump_ui_hierarchy(adb_path: str, device: Optional[str], remote_xml: str = XML_REMOTE_PATH, local_xml: str = XML_LOCAL_PATH) -> str:
    """
    Dump UI hierarchy vào /sdcard/view.xml rồi pull về máy.
    Trả về đường dẫn file XML local.
    """
    print("[*] Dump UI hierarchy (uiautomator dump) ...")
    # Tạo folder trên /sdcard nếu cần (thường không cần)
    run_adb(adb_path, device, ["shell", "uiautomator", "dump", remote_xml], check=True)
    # Nhiều ROM sẽ in “UI hierchary dumped to: ...” trên stdout/stderr — bỏ qua.

    # Chờ tí cho chắc (đôi khi file sync chậm)
    time.sleep(0.3)

    # Xoá file cũ local nếu tồn tại để tránh nhầm
    if os.path.exists(local_xml):
        try:
            os.remove(local_xml)
        except Exception:
            pass

    print(f"[*] Pull {remote_xml} -> {local_xml}")
    run_adb(adb_path, device, ["pull", remote_xml, local_xml], check=True)

    if not os.path.exists(local_xml):
        print(f"[ERR] Không tìm thấy file {local_xml} sau khi pull.", file=sys.stderr)
        sys.exit(2)

    print("[OK] Đã có view.xml local.")
    return local_xml


def analyze_viewxml(local_xml: str) -> Tuple[int, int, int, int, bool]:
    """
    Phân tích view.xml:
    - total_nodes
    - nodes_with_id
    - nodes_with_desc
    - surface_like_nodes (SurfaceView/UnityPlayer)
    - has_meaningful_elements (có đủ id/desc,...)
    """
    print("[*] Phân tích view.xml ...")
    try:
        tree = ET.parse(local_xml)
    except ET.ParseError as e:
        print(f"[ERR] Lỗi parse XML: {e}", file=sys.stderr)
        sys.exit(2)

    root = tree.getroot()

    # Uiautomator dump có thể đặt node dưới <hierarchy> hoặc tương tự
    # Mặc định phần tử node tên là "node"
    nodes = list(root.iter("node"))
    total_nodes = len(nodes)

    nodes_with_id = 0
    nodes_with_desc = 0
    surface_like = 0

    for n in nodes:
        clazz = (n.get("class") or "")
        rid   = (n.get("resource-id") or "")
        cdesc = (n.get("content-desc") or "")
        text  = (n.get("text") or "")

        if rid.strip():
            nodes_with_id += 1
        if cdesc.strip():
            nodes_with_desc += 1

        if ("SurfaceView" in clazz) or ("GLSurfaceView" in clazz) or ("UnityPlayer" in clazz) or ("com.unity3d.player.UnityPlayer" in clazz):
            surface_like += 1

    has_meaningful = (total_nodes >= MIN_TOTAL_NODES_OK) and ((nodes_with_id >= MIN_ID_OR_DESC_OK) or (nodes_with_desc >= MIN_ID_OR_DESC_OK))

    print("===== KẾT QUẢ PHÂN TÍCH =====")
    print(f"Tổng số node                 : {total_nodes}")
    print(f"Số node có resource-id       : {nodes_with_id}")
    print(f"Số node có content-desc      : {nodes_with_desc}")
    print(f"Số node Surface/Unity (gợi ý): {surface_like}")
    print("================================")

    return total_nodes, nodes_with_id, nodes_with_desc, surface_like, has_meaningful


def conclude(total_nodes: int, nodes_with_id: int, nodes_with_desc: int, surface_like: int, has_meaningful: bool) -> int:
    """
    In kết luận & trả về exit code:
    - 0: Khả năng CAO dùng Appium được
    - 1: Trung tính / cần kiểm tra thêm
    - 2: Khả năng THẤP dùng Appium (nên dùng CV+ADB)
    """
    # Case xấu rõ rệt: quá ít node hoặc toàn SurfaceView/Unity
    if total_nodes < LOW_TOTAL_NODES or surface_like > 0:
        print("⚠️  KẾT LUẬN: Khả năng **KHÔNG** dùng Appium cho gameplay (SurfaceView/Unity hoặc cây nghèo).")
        print("👉 Gợi ý: dùng Computer Vision + ADB + State Machine cho phần gameplay. Appium có thể chỉ chạy được ở màn permission/login (nếu có).")
        return 2

    # Case tốt rõ rệt: đủ nhiều node & có nhiều id/desc
    if has_meaningful:
        print("✅ KẾT LUẬN: Khả năng **CAO** dùng Appium (nhiều element có id/desc).")
        print("👉 Bạn có thể mở Appium Inspector để chọn locator (id/xpath/accessibility id).")
        return 0

    # Trung tính: không quá nghèo, nhưng chưa thấy đủ id/desc
    print("❓ KẾT LUẬN: **Trung tính** — Cần kiểm thêm bằng Appium Inspector.")
    print("👉 Thử mở Appium Inspector: nếu nhìn thấy/ chọn được element cụ thể thì vẫn dùng Appium được.")
    return 1


def main():
    parser = argparse.ArgumentParser(description="Kiểm tra nhanh khả năng dùng Appium trên màn hình hiện tại của game/app Android (qua uiautomator dump).")
    parser.add_argument("--adb", default=DEFAULT_ADB_PATH, help="Đường dẫn adb.exe (mặc định: Nox adb)")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="Serial/udid thiết bị, ví dụ 127.0.0.1:62025 (Nox)")
    parser.add_argument("--remote-xml", default=XML_REMOTE_PATH, help="Đường dẫn XML trên thiết bị (/sdcard/view.xml)")
    parser.add_argument("--local-xml", default=XML_LOCAL_PATH, help="Tên file XML lưu local (view.xml)")
    args = parser.parse_args()

    adb_path = args.adb
    device   = args.device

    if not os.path.exists(adb_path):
        print(f"[ERR] Không tìm thấy ADB tại: {adb_path}", file=sys.stderr)
        sys.exit(2)

    ensure_device_connected(adb_path, device)
    xml_local = dump_ui_hierarchy(adb_path, device, args.remote_xml, args.local_xml)
    totals = analyze_viewxml(xml_local)
    code = conclude(*totals)
    sys.exit(code)


if __name__ == "__main__":
    main()
