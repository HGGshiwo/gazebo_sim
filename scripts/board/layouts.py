class BaseLayoutStrategy:
    """布局策略基类"""
    def generate_layout(self, X_size, start_id=0):
        """
        返回坐标列表，中心点为 (0,0)
        格式: [{'id': int, 'cx': float, 'cy': float, 'size': float}, ...]
        """
        raise NotImplementedError("子类必须实现此方法")

class ProgressiveLayout(BaseLayoutStrategy):
    """精准高阶版：数学极限压榨 + 0.8比例完美阶梯收缩漏斗"""
    def generate_layout(self, X_size, start_id=0):
        # 1. 内侧微型星团
        inner_size = X_size * 0.08
        inner_dist = X_size * 0.09
        
        # 2. 严格按你要求的公式推导外侧阶梯尺寸
        # 最大尺寸 = 画布一半(0.5) - 中心小标签的尺寸(0.08) = 0.42
        s1 = (0.5 - 0.08) * X_size  # 0.420 X_size
        s2 = s1 * 0.8               # 0.336 X_size
        s3 = s2 * 0.8               # 0.268 X_size (约)
        s4 = s3 * 0.8               # 0.215 X_size (约)
        
        # 3. 核心布局技巧：所有外侧标签的"内边缘"统一紧贴安全边界
        # 这样最大的标签会自动占满剩下的所有空间并极其靠近中心，
        # 而较小的标签会因为尺寸小，外侧空出更多距离，形成完美的渐次脱离(FOV漏斗)。
        safe_margin = inner_size # 0.08 X_size，作为外圈不干扰内圈的安全边界
        
        # 中心坐标 = 安全边界 + 自身尺寸的一半
        cx1 = safe_margin + s1 / 2.0  # 约 0.29 X_size
        cx2 = safe_margin + s2 / 2.0  # 约 0.248 X_size
        cx3 = safe_margin + s3 / 2.0  # 约 0.214 X_size
        cx4 = safe_margin + s4 / 2.0  # 约 0.187 X_size

        return [
            # ----- 内侧十字星团 (近地盲区保障) -----
            {'id': start_id + 0, 'cx': 0, 'cy': 0, 'size': inner_size},
            {'id': start_id + 1, 'cx': 0, 'cy': -inner_dist, 'size': inner_size},
            {'id': start_id + 2, 'cx': 0, 'cy': inner_dist, 'size': inner_size},
            {'id': start_id + 3, 'cx': -inner_dist, 'cy': 0, 'size': inner_size},
            {'id': start_id + 4, 'cx': inner_dist, 'cy': 0, 'size': inner_size},
            
            # ----- 外侧 0.8 完美渐进收缩 (顺时针，基于对称轴翻转对应正负) -----
            
            # 1级接力 (左上): 最大的标签，内缘贴近中心，外缘刚好顶到画板 0.5 的极限边缘！最先脱离视野。
            {'id': start_id + 5, 'cx': -cx1, 'cy': -cx1, 'size': s1},
            
            # 2级接力 (右上): 缩减 0.8，向内靠拢
            {'id': start_id + 6, 'cx': cx2, 'cy': -cx2, 'size': s2},
            
            # 3级接力 (左下): 继续缩减 0.8
            {'id': start_id + 7, 'cx': -cx3, 'cy': cx3, 'size': s3},
            
            # 4级接力 (右下): 最小，不仅贴近中心，且外边缘也是离画板边缘最远的。死死连接内侧星团。
            {'id': start_id + 8, 'cx': cx4, 'cy': cx4, 'size': s4}
        ]
    
        
class AsymmetricLayout(BaseLayoutStrategy):
    """精准降落防多解：多尺度非对称阵列（极限压榨空间版）"""
    def generate_layout(self, X_size, start_id=0):
        # 【突破点 1】极限聚拢内侧：极其紧凑的中心群
        inner_size = X_size * 0.08  # 缩小到仅占总宽的 8%
        inner_dist = X_size * 0.09  # 间距压到 9%，内侧标签几乎紧贴中心，只留1%的防干扰白边
        
        # 【突破点 2】极限膨胀外侧：完全填满四个角落
        # 左上角最大达到 35%，在百米高空也是巨大的黑白块
        outer_sizes = [
            X_size * 0.35,  # 左上最大 (35%)
            X_size * 0.29,  # 右上
            X_size * 0.32,  # 左下
            X_size * 0.26   # 右下 (26%)
        ]
        # 将外侧标签中心往边缘推，给中间留出不重叠的安全区
        outer_dist = X_size * 0.32  

        return [
            {'id': start_id + 0, 'cx': 0, 'cy': 0, 'size': inner_size},
            {'id': start_id + 1, 'cx': 0, 'cy': -inner_dist, 'size': inner_size},
            {'id': start_id + 2, 'cx': 0, 'cy': inner_dist, 'size': inner_size},
            {'id': start_id + 3, 'cx': -inner_dist, 'cy': 0, 'size': inner_size},
            {'id': start_id + 4, 'cx': inner_dist, 'cy': 0, 'size': inner_size},
            {'id': start_id + 5, 'cx': -outer_dist, 'cy': -outer_dist, 'size': outer_sizes[0]},
            {'id': start_id + 6, 'cx': outer_dist, 'cy': -outer_dist, 'size': outer_sizes[1]},
            {'id': start_id + 7, 'cx': -outer_dist, 'cy': outer_dist, 'size': outer_sizes[2]},
            {'id': start_id + 8, 'cx': outer_dist, 'cy': outer_dist, 'size': outer_sizes[3]}
        ]

class UniformGridLayout(BaseLayoutStrategy):
    """标准 3x3 均匀等距阵列"""
    def generate_layout(self, X_size, start_id=0):
        tag_size = X_size * 0.20
        spacing = X_size * 0.30
        layout = []
        current_id = start_id
        for row in [-1, 0, 1]:
            for col in [-1, 0, 1]:
                layout.append({
                    'id': current_id, 'cx': col * spacing, 'cy': row * spacing, 'size': tag_size
                })
                current_id += 1
        return layout