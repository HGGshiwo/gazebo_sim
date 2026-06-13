import math
import base64
import urllib.request
import re
import json
from io import BytesIO
from pathlib import Path
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import sys
import hashlib

# 兼容 Python 3.8 的 reportlab md5 补丁
if sys.version_info < (3, 9):
    _original_md5 = hashlib.md5
    def _patched_md5(*args, **kwargs):
        kwargs.pop('usedforsecurity', None)
        return _original_md5(*args, **kwargs)
    hashlib.md5 = _patched_md5

class AprilTagDownloader:
    """负责从官方库下载 Tag"""
    @staticmethod
    def fetch_tag(tag_id, family="tag16h5"):
        # 自动推导 URL 前缀, 例如 tag16h5 -> tag16_05_
        match = re.match(r"tag(\d+)h(\d+)", family)
        if match:
            family_prefix = f"tag{match.group(1)}_{int(match.group(2)):02d}_"
        else:
            family_prefix = family.replace("h", "_") + "_"
            
        url = f"https://raw.githubusercontent.com/AprilRobotics/apriltag-imgs/master/{family}/{family_prefix}{tag_id:05d}.png"
        
        print(f"  -> 正在获取 [{family}] ID: {tag_id}...")
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req) as response:
                return Image.open(BytesIO(response.read())).convert("RGB")
        except Exception as e:
            raise RuntimeError(f"下载失败: {url}\n{e}")

class Exporter:
    """通用导出接口：负责生成预览 PNG, 完整 SVG, 以及分割 PDF"""
    def __init__(self, canvas_img, layout_data, board_size_px, dpi=300):
        self.canvas_img = canvas_img
        self.layout_data = layout_data
        self.board_size_px = board_size_px
        self.dpi = dpi

    def export_preview_png(self, output_path, max_dim=1024):
        """导出缩放后的预览 PNG（限制最大边长），不占用过多磁盘和内存"""
        img_copy = self.canvas_img.copy()
        # thumbnail 会原地等比例缩小图像
        img_copy.thumbnail((max_dim, max_dim))
        img_copy.save(output_path)
        print(f"  [+] 预览 PNG 已保存: {output_path} (最大边长 {max_dim}px)")

    def export_svg(self, output_path, downloader_cache):
        """导出完整 SVG (矢量格式，内嵌 base64 图片保证独立性，真实尺寸)"""
        w, h = self.board_size_px, self.board_size_px
        center_x, center_y = w / 2.0, h / 2.0
        
        svg = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">']
        svg.append('<rect width="100%" height="100%" fill="white"/>')
        
        for item in self.layout_data:
            img = downloader_cache[item['id']]
            buffered = BytesIO()
            img.resize((int(item['size']), int(item['size'])), Image.NEAREST).save(buffered, format="PNG")
            b64_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
            
            px = center_x + item['cx'] - item['size'] / 2.0
            py = center_y + item['cy'] - item['size'] / 2.0
            
            svg.append(f'<image x="{px}" y="{py}" width="{item["size"]}" height="{item["size"]}" href="data:image/png;base64,{b64_str}" />')
            
        svg.append('</svg>')
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(svg))
        print(f"  [+] 实际大小 SVG 已保存: {output_path}")

    def export_pdf_split(self, output_path):
        """导出分割的 PDF (切分为多张 A4 纸以便普通打印机打印，真实尺寸)"""
        a4_w_px = int((A4[0] / 72) * self.dpi)
        a4_h_px = int((A4[1] / 72) * self.dpi)
        
        cols = math.ceil(self.canvas_img.width / a4_w_px)
        rows = math.ceil(self.canvas_img.height / a4_h_px)
        
        c = canvas.Canvas(output_path, pagesize=A4)
        for r in range(rows):
            for col in range(cols):
                left, upper = col * a4_w_px, r * a4_h_px
                part = self.canvas_img.crop((left, upper, left + a4_w_px, upper + a4_h_px))
                part_path = f"temp_split_{r}_{col}.png"
                part.save(part_path, dpi=(self.dpi, self.dpi))
                
                c.drawImage(part_path, 0, 0, width=A4[0], height=A4[1])
                c.showPage()
                Path(part_path).unlink(missing_ok=True)
        c.save()
        print(f"  [+] 分割 PDF 已保存: {output_path} (共 {cols * rows} 页 A4)")