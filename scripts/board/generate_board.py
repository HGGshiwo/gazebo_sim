from pathlib import Path
import sys
import hashlib
import math

# 针对 Python 3.8 及以下版本的 reportlab 兼容补丁
if sys.version_info < (3, 9):
    _original_md5 = hashlib.md5

    def _patched_md5(*args, **kwargs):
        kwargs.pop("usedforsecurity", None)  # 强行移除不支持的参数
        return _original_md5(*args, **kwargs)

    hashlib.md5 = _patched_md5

import argparse
import json
from PIL import Image

# 引入 reportlab 核心库处理排版和裁切线
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4, A3
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader

from common import AprilTagDownloader, Exporter
from layouts import *


class BoardGenerator:
    def __init__(self, layout_strategy, dpi=300):
        self.layout_strategy = layout_strategy
        self.dpi = dpi
        self.pixel_to_meter = 0.0254 / dpi

    def build(self, board_size_mm, start_id, family, out_prefix, split=False, paper_size="A4"):
        # 1. 计算总像素尺寸 (以毫米推算)
        board_size_px = int((board_size_mm / 25.4) * self.dpi)
        canvas_img = Image.new("RGB", (board_size_px, board_size_px), (255, 255, 255))
        center_x, center_y = board_size_px / 2.0, board_size_px / 2.0

        # 以画板 90% 区域作为有效排布区 (留白边)
        X_size = board_size_px * 0.90
        print(f"X_size: {X_size}")
        layout_data = self.layout_strategy.generate_layout(X_size, start_id)

        points_3d_dict = {}
        downloader_cache = {}  # 缓存给 SVG 导出用
        save_dir = Path(__file__).parent.joinpath("output")
        save_dir.mkdir(exist_ok=True)

        print(f"\n[1/3] 开始生成排版图 (物理尺寸: {board_size_mm}mm x {board_size_mm}mm)")
        for item in layout_data:
            tag_id, cx_px, cy_px, size_px = (
                item["id"],
                item["cx"],
                item["cy"],
                int(item["size"]),
            )

            # 获取图片
            img = AprilTagDownloader.fetch_tag(tag_id, family)
            downloader_cache[tag_id] = img
            img_resized = img.resize((size_px, size_px), Image.NEAREST)

            # 粘贴到大画板
            paste_x = int(center_x + cx_px - size_px / 2)
            paste_y = int(center_y + cy_px - size_px / 2)
            canvas_img.paste(img_resized, (paste_x, paste_y))

            # 计算供 C++ 用的 3D 物理坐标
            cx_m, cy_m = cx_px * self.pixel_to_meter, cy_px * self.pixel_to_meter

            # 根据族类(family)计算网格比例
            if "tag16h5" in family:
                effective_ratio = 6.0 / 8.0
            elif "tag36h11" in family:
                effective_ratio = 8.0 / 10.0
            elif "tag25h9" in family:
                effective_ratio = 7.0 / 9.0
            else:
                effective_ratio = 0.75

            # 角点之间的真实物理距离
            effective_size_px = size_px * effective_ratio
            half_s_m = (effective_size_px / 2.0) * self.pixel_to_meter

            points_3d_dict[tag_id] = [
                [-half_s_m + cx_m, half_s_m + cy_m, 0.0],
                [half_s_m + cx_m, half_s_m + cy_m, 0.0],
                [half_s_m + cx_m, -half_s_m + cy_m, 0.0],
                [-half_s_m + cx_m, -half_s_m + cy_m, 0.0],
            ]

        # 2. 导出 3D 配置文件
        json_path = save_dir.joinpath(f"{out_prefix}_3d_config.json")
        with open(json_path, "w") as f:
            json.dump(points_3d_dict, f, indent=4)
        print(f"[2/3] 3D坐标系已导出至: {json_path}")

        # 3. 执行格式导出
        print("[3/3] 正在生成图像文件...")
        exporter = Exporter(canvas_img, layout_data, board_size_px, self.dpi)

        # 3.1 生成轻量级预览 PNG
        exporter.export_preview_png(save_dir.joinpath(f"{out_prefix}_preview.png"))

        # 3.2 始终生成实际物理大小的 SVG 矢量图
        exporter.export_svg(
            save_dir.joinpath(f"{out_prefix}_full.svg"), downloader_cache
        )

        # 3.3 生成真实尺寸的分割 PDF，并加入完整虚线裁切线
        if split:
            pdf_name = f"{out_prefix}_split_{paper_size}.pdf"
            pdf_path = str(save_dir.joinpath(pdf_name))
            print(f"正在生成 {paper_size} 分割打印 PDF 并添加辅助裁切虚线...")
            self._export_pdf_split_with_cropmarks(canvas_img, board_size_mm, pdf_path, paper_size)

        print("\n✅ 所有任务完成！")

    def _export_pdf_split_with_cropmarks(self, img, board_size_mm, pdf_path, paper_size):
        """将完整阵列图切分至多页 PDF，标记贯穿整页的虚线裁切线，并添加页码防呆提示"""
        # 设置页面尺寸
        if paper_size.upper() == "A3":
            page_w, page_h = A3
        else:
            page_w, page_h = A4

        c = rl_canvas.Canvas(pdf_path, pagesize=(page_w, page_h))

        # 留出 15mm 边距，确保普通打印机的物理边距打得出来
        margin = 15 * mm
        print_w = page_w - 2 * margin
        print_h = page_h - 2 * margin

        # 画板的总物理尺寸
        board_w_pt = board_size_mm * mm
        board_h_pt = board_size_mm * mm

        cols = math.ceil(board_w_pt / print_w)
        rows = math.ceil(board_h_pt / print_h)

        img_w_px, img_h_px = img.size

        for row in range(rows):
            for col in range(cols):
                # 计算在画布上的起点位置 (物理 pt)
                x_start_pt = col * print_w
                y_start_pt = row * print_h

                tile_w_pt = min(print_w, board_w_pt - x_start_pt)
                tile_h_pt = min(print_h, board_h_pt - y_start_pt)

                # 将物理排版区域映射到 PIL 的像素值
                x_start_px = int((x_start_pt / board_w_pt) * img_w_px)
                y_start_px = int((y_start_pt / board_h_pt) * img_h_px)
                x_end_px = int(((x_start_pt + tile_w_pt) / board_w_pt) * img_w_px)
                y_end_px = int(((y_start_pt + tile_h_pt) / board_h_pt) * img_h_px)

                # 裁剪图像区块
                tile_img = img.crop((x_start_px, y_start_px, x_end_px, y_end_px))
                tile_reader = ImageReader(tile_img)

                # 居中绘制位置
                draw_x = (page_w - tile_w_pt) / 2.0
                draw_y = (page_h - tile_h_pt) / 2.0

                # 1. 绘制图像
                c.drawImage(tile_reader, draw_x, draw_y, width=tile_w_pt, height=tile_h_pt)

                # 2. ===== 绘制贯穿整页的虚线裁切线 =====
                # 使用灰色避免喧宾夺主，线宽0.5
                c.setStrokeColorRGB(0.5, 0.5, 0.5)
                c.setLineWidth(0.5)
                # 设置虚线样式: 8pt 实线, 4pt 空白
                c.setDash(8, 4)

                # 画四条贯穿全页的直线，形成一个完美的“井”字包裹着图像区域
                c.line(draw_x, 0, draw_x, page_h)                                 # 左边界竖线
                c.line(draw_x + tile_w_pt, 0, draw_x + tile_w_pt, page_h)         # 右边界竖线
                c.line(0, draw_y, page_w, draw_y)                                 # 下边界横线
                c.line(0, draw_y + tile_h_pt, page_w, draw_y + tile_h_pt)         # 上边界横线

                # 3. ===== 绘制防呆页码水印 (即使是白纸也能知道位置) =====
                c.setDash()  # 恢复实线模式
                c.setFillColorRGB(0.6, 0.6, 0.6)  # 浅灰色文字
                c.setFont("Helvetica", 9)
                # 在页面底部边缘留下拼接线索
                info_text = f"Part: Col {col+1} of {cols} | Row {row+1} of {rows}  (Cut along dashed lines)"
                c.drawString(margin, margin / 2, info_text)

                # 结束当前页
                c.showPage()
                
        c.save()


LAYOUT_MAP = {
    "asymmetric": AsymmetricLayout,
    "grid": UniformGridLayout,
    "max": ProgressiveLayout,
    "super": SupernovaLayout,
    "opt": OptimizedLayout,
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="模块化的高精度 AprilTag 阵列生成工具")
    layout_keys = list(LAYOUT_MAP.keys())
    parser.add_argument(
        "--layout", choices=layout_keys, default=layout_keys[-1], help="布局"
    )
    parser.add_argument(
        "--family", default="tag16h5", help="AprilTag族 (默认: tag16h5, 即 tag5)"
    )
    parser.add_argument(
        "--size-mm", type=float, default=600.0, help="画板的实际物理边长(毫米)，默认 600mm"
    )
    parser.add_argument("--start-id", type=int, default=0, help="起始ID (默认: 0)")
    parser.add_argument("--out", default="landing_board", help="输出文件名的统一前缀")
    
    parser.add_argument("--split", action="store_true", help="传入此参数，则额外将PDF进行分页切割")
    parser.add_argument("--paper", choices=["A4", "A3", "a4", "a3"], default="A4", help="切割用的纸张大小 (默认: A4)")

    args = parser.parse_args()
    print(f"Use layout: {args.layout}")
    strategy = LAYOUT_MAP[args.layout]()
    generator = BoardGenerator(layout_strategy=strategy, dpi=300)

    generator.build(
        board_size_mm=args.size_mm,
        start_id=args.start_id,
        family=args.family,
        out_prefix=args.out,
        split=args.split,
        paper_size=args.paper.upper(),
    )