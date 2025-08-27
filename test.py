# test_blessing_api.py
import os, json, platform, uuid, hashlib, requests
from pathlib import Path

API_BASE = os.getenv("BBTK_API_BASE", "https://api.bbtkauto.io.vn").rstrip("/")

# === Copy logic từ client để trùng khớp ===
APP_NAME = "BBTKAuto"
TOKEN_FILE = os.path.join(
    os.getenv("APPDATA") or os.path.expanduser("~/.config"),
    APP_NAME, "token.json",
)

def stable_device_uid() -> str:
    try:
        mac = uuid.getnode()
    except Exception:
        mac = 0
    sig = f"{platform.node()}|{platform.machine()}|{platform.processor()}|{mac}"
    return f"PC-{hashlib.sha1(sig.encode()).hexdigest()[:12].upper()}"

def load_token():
    p = Path(TOKEN_FILE)
    if not p.exists():
        raise SystemExit(f"Không tìm thấy token file: {p}")
    obj = json.loads(p.read_text("utf-8"))
    tok = obj.get("token")
    if not tok:
        raise SystemExit(f"token.json không có field 'token': {obj}")
    return tok, obj.get("email"), obj.get("exp")

def print_resp(r: requests.Response, title: str):
    print("="*80)
    print(title)
    print(f"URL       : {r.request.method} {r.url}")
    print(f"Status    : {r.status_code} {r.reason}")
    # In một phần header cho gọn
    try:
        print("RespHdrs  :", {k: v for k, v in r.headers.items() if k.lower() in ("content-type","date","server")})
    except Exception:
        pass
    print("Raw text  :")
    try:
        print(r.text[:2000])  # tránh tràn console
    except Exception as e:
        print(f"(err read text: {e})")
    print("JSON parse:")
    try:
        print(r.json())
    except Exception as e:
        print(f"(err parse json: {e})")

def main():
    token, email, exp = load_token()
    uid = stable_device_uid()

    sess = requests.Session()
    sess.headers.update({
        "Authorization": f"Bearer {token}",
        "X-Device-UID": uid,
        "User-Agent": "BBTKAuto/1.0",
        "Content-Type": "application/json",
    })

    # 1) GET /api/blessing/config
    url = f"{API_BASE}/api/blessing/config"
    r = sess.get(url, timeout=15)
    print_resp(r, "GET /api/blessing/config")

    # 2) GET /api/blessing/targets?all=true  (UI quản lý)
    url = f"{API_BASE}/api/blessing/targets"
    r = sess.get(url, params={"all": "true"}, timeout=15)
    print_resp(r, "GET /api/blessing/targets?all=true")

    # 3) GET /api/blessing/targets (dành cho chạy auto)
    r = sess.get(f"{API_BASE}/api/blessing/targets", timeout=15)
    print_resp(r, "GET /api/blessing/targets")

    # 4) (Tùy chọn) Test POST /api/blessing/history
    #    Nhớ thay acc_id/target_id thực tế trước khi mở comment.
    # payload = {"game_account_id": 123, "target_id": 456}
    # r = sess.post(f"{API_BASE}/api/blessing/history", json=payload, timeout=15)
    # print_resp(r, "POST /api/blessing/history")

if __name__ == "__main__":
    main()
