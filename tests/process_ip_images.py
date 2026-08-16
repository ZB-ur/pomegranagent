"""处理柯尔鸭三视图：去水印、裁剪、多尺寸输出到 assets/。"""
import os
from pathlib import Path

from PIL import Image, ImageOps

SRC = Path("/tmp/duck_ip")
OUT = Path(__file__).resolve().parent.parent / "app" / "frontend" / "assets"
OUT.mkdir(parents=True, exist_ok=True)

# 三视图原始文件
files = {
    "front": "jimeng-2026-08-15-2834-生成柯尔鸭卡通IP形象版本_生成该卡通鸭子IP形象的正面视图，保持角色的白色绒毛..._0.png",
    "side":  "jimeng-2026-08-15-3477-生成柯尔鸭卡通IP形象版本_生成该卡通鸭子IP形象的侧面视图，保持角色的白色绒毛..._0.png",
    "back":  "jimeng-2026-08-15-4171-生成柯尔鸭卡通IP形象版本_生成该卡通鸭子IP形象的背面视图，保持角色的白色绒毛..._0.png",
}


def trim_watermark(img: Image.Image) -> Image.Image:
    """裁掉右下角水印区域（"即梦AI" + 五角星 logo）。"""
    w, h = img.size
    # 裁掉右下角约 18% 宽 x 8% 高
    crop_w = int(w * 0.18)
    crop_h = int(h * 0.08)
    return img.crop((0, 0, w - crop_w, h - crop_h))


def trim_top(img: Image.Image) -> Image.Image:
    """裁掉顶部空白（上方白边）。"""
    w, h = img.size
    # 顶部留 5%，底部留 5%（去掉大量白边）
    top = int(h * 0.05)
    bottom = int(h * 0.05)
    return img.crop((0, top, w, h - bottom))


def trim_sides(img: Image.Image) -> Image.Image:
    """左右裁掉空白。"""
    w, h = img.size
    left = int(w * 0.04)
    right = int(w * 0.04)
    return img.crop((left, 0, w - right, h))


def smart_trim(img: Image.Image) -> Image.Image:
    """智能裁剪：去水印 + 上下白边 + 适度左右白边。"""
    img = trim_watermark(img)
    img = trim_top(img)
    img = trim_sides(img)
    return img


def save_variants(src_img: Image.Image, base_name: str, sizes: dict) -> None:
    for suffix, size in sizes.items():
        img = src_img.copy()
        img = ImageOps.contain(img, (size, size))  # 等比缩放
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        # 白色背景转透明
        white_bg = Image.new("RGBA", img.size, (255, 255, 255, 0))
        white_bg.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
        out_path = OUT / f"{base_name}{suffix}.png"
        white_bg.save(out_path, "PNG")
        print(f"  -> {out_path.name}  {white_bg.size}")


# 处理正面图（主素材）
sizes_main = {"-512": 512}
sizes_avatar = {"-128": 128}
sizes_logo = {"-logo": 96}
sizes_favicon = {"-favicon": 64}

for key, fname in files.items():
    src_path = SRC / fname
    img = Image.open(src_path)
    print(f"{key}: 原图 {img.size}")
    img = img.convert("RGBA")
    img = smart_trim(img)
    print(f"  裁剪后 {img.size}")

    if key == "front":
        save_variants(img, "duck-front", {**sizes_main, **sizes_avatar, **sizes_logo, **sizes_favicon})
    elif key == "side":
        save_variants(img, "duck-side", sizes_main)
    elif key == "back":
        save_variants(img, "duck-back", sizes_main)

print(f"\n✅ 已输出到 {OUT}")
for p in sorted(OUT.glob("*.png")):
    print(f"  {p.name}  {p.stat().st_size // 1024} KB")