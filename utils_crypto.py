# utils_crypto.py
# Chứa các hàm mã hóa và giải mã mật khẩu

import base64

# Đây là một "secret key" đơn giản, bạn nên thay đổi thành một chuỗi phức tạp và giữ bí mật
SECRET_KEY = b'bbtk-auto-secret-key-!@#$%'

def _derive_key(user_email: str) -> bytes:
    """Tạo key mã hóa từ email người dùng và secret key."""
    # Đơn giản là kết hợp và lấy một phần, có thể dùng các thuật toán phức tạp hơn
    combined = SECRET_KEY + user_email.encode('utf-8')
    return base64.urlsafe_b64encode(combined[:32])

def encrypt(plaintext: str, user_email: str) -> str:
    """Mã hóa mật khẩu bằng phương pháp XOR đơn giản."""
    key = _derive_key(user_email)
    encrypted_bytes = bytearray()
    for i, char_byte in enumerate(plaintext.encode('utf-8')):
        encrypted_bytes.append(char_byte ^ key[i % len(key)])
    return base64.urlsafe_b64encode(encrypted_bytes).decode('utf-8')

def decrypt(ciphertext: str, user_email: str) -> str:
    """Giải mã mật khẩu."""
    key = _derive_key(user_email)
    encrypted_bytes = base64.urlsafe_b64decode(ciphertext.encode('utf-8'))
    decrypted_bytes = bytearray()
    for i, char_byte in enumerate(encrypted_bytes):
        decrypted_bytes.append(char_byte ^ key[i % len(key)])
    return decrypted_bytes.decode('utf-8')