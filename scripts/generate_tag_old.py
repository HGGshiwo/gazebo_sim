import math
import numpy as np
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from pathlib import Path
import argparse

# https://github.com/AprilRobotics/apriltag-imgs/blob/master/tagCustom48h12/tag48_12_00000.png
def get_path(path):
    if not Path(path).is_absolute():
        path = str(Path(__file__).parent.joinpath(path))
    return path

def read_image(path):
    # 读取为黑白图像（1位像素，0/1）
    img = Image.open(path)
    return img

def get_a4_size(dpi=300):
    width_inch, height_inch = A4[0] / 72, A4[1] / 72
    width_px = int(width_inch * dpi)
    height_px = int(height_inch * dpi)
    return width_px, height_px

def expand_image(img, num_a4, dpi=300):
    a4_w, a4_h = get_a4_size(dpi)
    # 选择最接近正方形的行列数
    best_diff = None
    best_cols, best_rows = None, None
    for cols in range(1, num_a4 + 1):
        if num_a4 % cols == 0:
            rows = num_a4 // cols
            diff = abs(cols * a4_w - rows * a4_h)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_cols, best_rows = cols, rows
    cols, rows = best_cols, best_rows
    target_w = cols * a4_w
    target_h = rows * a4_h

    # 保持正方形，缩放原图到适合的尺寸（短边对齐，长边居中）
    orig_w, orig_h = img.size
    scale = min(target_w, target_h) / max(orig_w, orig_h)
    new_size = (int(orig_w * scale), int(orig_h * scale))
    img_resized = img.resize(new_size, Image.NEAREST)

    # 创建目标画布，白底
    canvas_img = Image.new(img.mode, (target_w, target_h), (255, 255, 255, 255))
    # 居中粘贴
    left = (target_w - new_size[0]) // 2
    top = (target_h - new_size[1]) // 2
    canvas_img.paste(img_resized, (left, top))
    return canvas_img, cols, rows, a4_w, a4_h

def find_center_square_transparent(img):
    # img: PIL Image, mode '1'
    arr = np.array(img)
    # 透明区为白色（255），黑色为0
    transparent = np.where(arr[:,:,-1] != 255)
    if len(transparent[0]) == 0:
        raise ValueError("No transparent area found!")
    min_y, max_y = np.min(transparent[0]), np.max(transparent[0])
    min_x, max_x = np.min(transparent[1]), np.max(transparent[1])
    side = min(max_x - min_x, max_y - min_y)
    center_x = (min_x + max_x) // 2
    center_y = (min_y + max_y) // 2
    half = side // 2
    return (center_x - half, center_y - half, center_x + half, center_y + half)

def recursive_draw(img, base, min_size=4):
    box = find_center_square_transparent(base)
    side = box[2] - box[0]
    if side <= min_size:
        return base
    # 缩小原图到透明区大小，最近邻插值
    small = img.resize((side, side), Image.NEAREST)
    # 递归
    try:
        small_trans_box = find_center_square_transparent(small)
        small = recursive_draw(img, small, min_size)
    except Exception:
        pass
    # 粘贴到透明区
    base.paste(small, (box[0], box[1]))
    return base

def crop_white_border(img):
    """去掉图像周围的白边"""
    arr = np.array(img)
    # 找到非白色像素的边界
    if len(arr.shape) == 3:
        # RGBA或RGB模式
        non_white = np.where((arr[:,:,0] != 255) | (arr[:,:,1] != 255) | (arr[:,:,2] != 255))
    else:
        # 灰度或1位模式
        non_white = np.where(arr != 255)
    
    if len(non_white[0]) == 0:
        # 全是白色，返回原图
        return img
    
    min_y, max_y = np.min(non_white[0]), np.max(non_white[0])
    min_x, max_x = np.min(non_white[1]), np.max(non_white[1])
    
    # 裁剪图像
    return img.crop((min_x, min_y, max_x + 1, max_y + 1))

def export_to_pdf(img, cols, rows, a4_w, a4_h, output_path, dpi=300):
    c = canvas.Canvas(output_path, pagesize=A4)
    for r in range(rows):
        for col in range(cols):
            left = col * a4_w
            upper = r * a4_h
            box = (left, upper, left + a4_w, upper + a4_h)
            part = img.crop(box)
            part_path = f"temp_part_{r}_{col}.png"
            part_path = get_path(part_path)
            part.save(part_path, dpi=(dpi, dpi))
            c.drawImage(part_path, 0, 0, width=A4[0], height=A4[1])
            c.showPage()
    c.save()

def export_to_png(img, output_path, dpi=300):
    img.save(output_path, dpi=(dpi, dpi))

def main(
    input_png,
    output_path,
    output_format="pdf",
    num_a4=4,
    min_size=32,
    dpi=300
):
    input_png = get_path(input_png)
    output_path = get_path(output_path)
    img = read_image(input_png)
    img_expanded, cols, rows, a4_w, a4_h = expand_image(img, num_a4, dpi)
    img_final = recursive_draw(img, img_expanded, min_size)
    
    if output_format.lower() == "pdf":
        export_to_pdf(img_final, cols, rows, a4_w, a4_h, output_path, dpi)
    elif output_format.lower() == "png":
        # PNG输出：去掉白边后导出
        img_cropped = crop_white_border(img_final)
        export_to_png(img_cropped, output_path, dpi)
    else:
        raise ValueError(f"Unsupported format: {output_format}")
    
    print(f"Exported to {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert image to PDF or PNG")
    parser.add_argument("input", help="Input PNG file path")
    parser.add_argument("output", help="Output file path")
    parser.add_argument("--pdf", action="store_true", help="Export as PDF (default)")
    parser.add_argument("--png", action="store_true", help="Export as PNG")
    parser.add_argument("--num-a4", type=int, default=4, help="Number of A4 pages (default: 4)")
    parser.add_argument("--min-size", type=int, default=32, help="Minimum size for recursion (default: 32)")
    parser.add_argument("--dpi", type=int, default=300, help="DPI for output (default: 300)")
    
    args = parser.parse_args()
    
    # 确定输出格式
    if args.png:
        output_format = "png"
    elif args.pdf:
        output_format = "pdf"
    else:
        # 默认根据输出文件扩展名判断
        output_format = "pdf" if args.output.lower().endswith(".pdf") else "png"
    
    main(
        input_png=args.input,
        output_path=args.output,
        output_format=output_format,
        num_a4=args.num_a4,
        min_size=args.min_size,
        dpi=args.dpi
    )
""" 
图片来源: https://github.com/AprilRobotics/apriltag-imgs

# 导出为PDF（默认）
python generate_tag.py input.png output.pdf --pdf

# 导出为PNG
python generate_tag.py input.png output.png --png

# 自动根据扩展名判断（不指定--pdf或--png时）
python generate_tag.py input.png output.pdf
python generate_tag.py input.png output.png

# 带其他参数
python generate_tag.py input.png output.png --png --num-a4 4 --min-size 32 --dpi 300
"""
