from pathlib import Path
import sys
import hashlib

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
from common import AprilTagDownloader, Exporter
from layouts import *


class BoardGenerator:
    def __init__(self, layout_strategy, dpi=300):
        self.layout_strategy = layout_strategy
        self.dpi = dpi
        self.pixel_to_meter = 0.0254 / dpi

    def build(self, board_size_mm, start_id, family, out_prefix, split=False):
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

            # --- 核心修正：换算 AprilTag 的有效角点物理尺寸 ---
            # 根据族类(family)计算网格比例
            if "tag16h5" in family:
                # 8x8 总网格，6x6 黑框网格
                effective_ratio = 6.0 / 8.0
            elif "tag36h11" in family:
                # 10x10 总网格，8x8 黑框网格
                effective_ratio = 8.0 / 10.0
            elif "tag25h9" in family:
                # 9x9 总网格，7x7 黑框网格
                effective_ratio = 7.0 / 9.0
            else:
                # 默认降级比例 (如果使用了其他罕见字典)
                effective_ratio = 0.75

            # 角点之间的真实物理距离
            effective_size_px = size_px * effective_ratio
            half_s_m = (effective_size_px / 2.0) * self.pixel_to_meter

            # 这里的四个点，严格对应 AprilTag C++ 库中 det->p[0], p[1], p[2], p[3] 的顺序
            # 顺序为：左下，右下，右上，左上 (基于相机投影坐标系的不同，可能需根据你的飞控调整)
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

        # 1. 生成轻量级预览 PNG
        exporter.export_preview_png(save_dir.joinpath(f"{out_prefix}_preview.png"))

        # 2. 始终生成实际物理大小的 SVG 矢量图
        exporter.export_svg(
            save_dir.joinpath(f"{out_prefix}_full.svg"), downloader_cache
        )

        # 3. 仅在明确指定 split 时，才生成真实尺寸的 A4 分割 PDF
        if split:
            exporter.export_pdf_split(save_dir.joinpath(f"{out_prefix}_split_A4.pdf"))

        print("\n✅ 所有任务完成！")


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
    parser.add_argument("--split", action="store_true", help="传入此参数，则额外将PDF分割为多张A4纸")

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
    )
