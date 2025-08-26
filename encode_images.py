# encode_images.py
import os
import base64
from pathlib import Path

# Thư mục chứa tất cả các ảnh của bạn
IMAGE_SOURCE_DIR = "images"
# File Python đầu ra sẽ chứa dữ liệu ảnh đã mã hóa
OUTPUT_PY_FILE = "image_data.py"


def encode_images_to_py():
    """
    Quét thư mục IMAGE_SOURCE_DIR, mã hóa tất cả các file .png thành Base64
    và lưu chúng vào một file Python dưới dạng một dictionary.
    """
    image_data_dict = {}

    # Sử dụng Path để xử lý đa nền tảng và dùng .rglob để quét đệ quy
    source_path = Path(IMAGE_SOURCE_DIR)
    image_files = sorted(list(source_path.rglob("*.png")))

    if not image_files:
        print(f"Lỗi: Không tìm thấy file .png nào trong thư mục '{IMAGE_SOURCE_DIR}'")
        return

    print(f"Đang tiến hành mã hóa {len(image_files)} file ảnh...")

    for path in image_files:
        # Đọc dữ liệu nhị phân của file ảnh
        with open(path, "rb") as image_file:
            binary_data = image_file.read()

        # Mã hóa sang Base64 và chuyển thành chuỗi utf-8
        base64_encoded_str = base64.b64encode(binary_data).decode('utf-8')

        # Tạo một key chuẩn hóa (luôn dùng dấu /) để dễ dàng tra cứu
        # Ví dụ: "images/login/icon_lien_minh.png"
        key = path.as_posix()
        image_data_dict[key] = base64_encoded_str
        print(f"  + Đã mã hóa: {key}")

    # Ghi dictionary vào file Python
    with open(OUTPUT_PY_FILE, "w", encoding="utf-8") as f:
        f.write("# -*- coding: utf-8 -*-\n")
        f.write("# File này được tạo tự động bởi encode_images.py\n")
        f.write("# Chứa dữ liệu ảnh đã được mã hóa Base64.\n\n")
        f.write("IMAGE_DATA = {\n")
        for key, value in image_data_dict.items():
            f.write(f'    "{key}": "{value}",\n')
        f.write("}\n")

    print(f"\n✅ Hoàn tất! Đã lưu dữ liệu vào file '{OUTPUT_PY_FILE}'")


if __name__ == "__main__":
    encode_images_to_py()