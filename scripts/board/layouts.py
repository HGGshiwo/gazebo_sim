class BaseLayoutStrategy:
    """布局策略基类"""
    def generate_layout(self, X_size, start_id=0):
        """
        返回坐标列表，中心点为 (0,0)
        格式: [{'id': int, 'cx': float, 'cy': float, 'size': float}, ...]
        """
        raise NotImplementedError("子类必须实现此方法")

class ProgressiveLayout(BaseLayoutStrategy):
    """榨干白边版：单位统一修正，绝对长度计算"""
    def generate_layout(self, X_size, start_id=0):
        # 1. 内部星团 (绝对长度)
        inner_size = X_size * 0.07 
        inner_dist = X_size * 0.07 
        
        # 内侧最大绝对边界
        inner_max_edge = inner_dist + (inner_size / 2.0)
        
        # 2. 外部阵列尺寸 (绝对长度)
        # 【修正点】画布一半的绝对长度是 0.5 * X_size，用它减去内侧绝对边界
        s1 = (0.5 * X_size) - inner_max_edge  
        
        s2 = 0.36 * X_size
        s3 = 0.32 * X_size
        s4 = 0.28 * X_size 
        
        # 3. 计算中心坐标 (绝对长度)
        # 外侧标签的中心坐标 = 内部极限边界 + 自身尺寸的一半
        cx1 = inner_max_edge + s1 / 2.0
        cx2 = inner_max_edge + s2 / 2.0
        cx3 = inner_max_edge + s3 / 2.0
        cx4 = inner_max_edge + s4 / 2.0

        return [
            # ----- 内侧十字星团 -----
            {'id': start_id + 0, 'cx': 0, 'cy': 0, 'size': inner_size},
            {'id': start_id + 1, 'cx': 0, 'cy': -inner_dist, 'size': inner_size},
            {'id': start_id + 2, 'cx': 0, 'cy': inner_dist, 'size': inner_size},
            {'id': start_id + 3, 'cx': -inner_dist, 'cy': 0, 'size': inner_size},
            {'id': start_id + 4, 'cx': inner_dist, 'cy': 0, 'size': inner_size},
            
            # ----- 外侧高密度阵列 -----
            {'id': start_id + 5, 'cx': -cx1, 'cy': -cx1, 'size': s1},
            {'id': start_id + 6, 'cx': cx2, 'cy': -cx2, 'size': s2},
            {'id': start_id + 7, 'cx': -cx3, 'cy': cx3, 'size': s3},
            {'id': start_id + 8, 'cx': cx4, 'cy': cx4, 'size': s4}
        ]

class SupernovaLayout(BaseLayoutStrategy):
    """超新星17码阵列：三阶接力 + 零缝隙俄罗斯方块堆叠 + 涡轮视场脱离"""
    def generate_layout(self, X_size, start_id=0):
        layout = []
        id_curr = start_id

        # ==========================================
        # 【第一阶：内核星团】 (保障最后 10cm 贴地盲区)
        # ==========================================
        # 1. 中心微型锚点
        s_core = 0.06 * X_size
        layout.append({'id': id_curr, 'cx': 0, 'cy': 0, 'size': s_core})
        id_curr += 1

        # 2. 内侧紧密十字
        s_inner = 0.08 * X_size
        d_inner = 0.07 * X_size
        layout.extend([
            {'id': id_curr+0, 'cx': d_inner, 'cy': 0, 'size': s_inner},   # E
            {'id': id_curr+1, 'cx': -d_inner, 'cy': 0, 'size': s_inner},  # W
            {'id': id_curr+2, 'cx': 0, 'cy': d_inner, 'size': s_inner},   # S
            {'id': id_curr+3, 'cx': 0, 'cy': -d_inner, 'size': s_inner},  # N
        ])
        id_curr += 4

        # ==========================================
        # 【第二阶：中空齿轮过渡】 (极其巧妙的卡位)
        # ==========================================
        # 内侧十字在坐标轴上凸出，但在四个角落留下了完美的方形空隙。
        # 第一阶的 X/Y 几何边缘刚好都在 0.04 (距中心)。
        # 我们把第二阶的内角死死顶在这个 (0.04, 0.04) 的坐标上！
        s_mid = 0.14 * X_size
        d_mid = 0.11 * X_size  # 中心点 = 0.04 + (0.14 / 2)
        layout.extend([
            {'id': id_curr+0, 'cx': d_mid, 'cy': d_mid, 'size': s_mid},   # SE
            {'id': id_curr+1, 'cx': -d_mid, 'cy': d_mid, 'size': s_mid},  # SW
            {'id': id_curr+2, 'cx': -d_mid, 'cy': -d_mid, 'size': s_mid}, # NW
            {'id': id_curr+3, 'cx': d_mid, 'cy': -d_mid, 'size': s_mid},  # NE
        ])
        id_curr += 4

        # ==========================================
        # 【第三阶：高空涡轮护卫】 (极限填充与平滑脱离)
        # ==========================================
        # 第二阶的外边缘精准停在了 0.04 + 0.14 = 0.18。
        # 我们将第三阶所有的 8 个超大标签的内边缘，统一对齐到 0.18！
        inner_edge = 0.18 * X_size

        # 定义四个不对称的渐进尺寸，形成漏斗效应 (最大达到画板宽度的 32%)
        sizes = [0.32 * X_size, 0.30 * X_size, 0.28 * X_size, 0.26 * X_size]
        # 根据内边缘对齐原理，自动反推它们的中心点坐标
        centers = [inner_edge + s/2.0 for s in sizes]

        # 第一级脱离：东侧组合 (最大的 2 个 Tag，极限高空用)
        layout.extend([
            {'id': id_curr+0, 'cx': centers[0], 'cy': 0, 'size': sizes[0]},             # 正东
            {'id': id_curr+1, 'cx': centers[0], 'cy': centers[0], 'size': sizes[0]},    # 东南角
        ])
        id_curr += 2

        # 第二级脱离：南侧组合
        layout.extend([
            {'id': id_curr+0, 'cx': 0, 'cy': centers[1], 'size': sizes[1]},             # 正南
            {'id': id_curr+1, 'cx': -centers[1], 'cy': centers[1], 'size': sizes[1]},   # 西南角
        ])
        id_curr += 2

        # 第三级脱离：西侧组合
        layout.extend([
            {'id': id_curr+0, 'cx': -centers[2], 'cy': 0, 'size': sizes[2]},            # 正西
            {'id': id_curr+1, 'cx': -centers[2], 'cy': -centers[2], 'size': sizes[2]},  # 西北角
        ])
        id_curr += 2

        # 第四级脱离：北侧组合 (哪怕是最小的一组，边长也占了 26%，充当中低空桥梁)
        layout.extend([
            {'id': id_curr+0, 'cx': 0, 'cy': -centers[3], 'size': sizes[3]},            # 正北
            {'id': id_curr+1, 'cx': centers[3], 'cy': -centers[3], 'size': sizes[3]},   # 东北角
        ])

        return layout      
        
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

class OptimizedLayout(BaseLayoutStrategy):
    def generate_layout(self, X_size, start_id=0):
        # 把控制台生成的代码原封不动粘贴到这里
        inner_size = X_size * 0.0400
        inner_dist = X_size * 0.0400
        
        s1 = 0.4400 * X_size
        s2 = 0.4200 * X_size
        s3 = 0.4000 * X_size
        s4 = 0.3800 * X_size
        
        cx1 = 0.2800 * X_size
        cx2 = 0.2700 * X_size
        cx3 = 0.2600 * X_size
        cx4 = 0.2500 * X_size

        return [
            # 内侧十字
            {'id': start_id + 0, 'cx': 0, 'cy': 0, 'size': inner_size},
            {'id': start_id + 1, 'cx': 0, 'cy': -inner_dist, 'size': inner_size},
            {'id': start_id + 2, 'cx': 0, 'cy': inner_dist, 'size': inner_size},
            {'id': start_id + 3, 'cx': -inner_dist, 'cy': 0, 'size': inner_size},
            {'id': start_id + 4, 'cx': inner_dist, 'cy': 0, 'size': inner_size},
            
            # 外侧漏斗
            {'id': start_id + 5, 'cx': -cx1, 'cy': -cx1, 'size': s1},
            {'id': start_id + 6, 'cx': cx2, 'cy': -cx2, 'size': s2},
            {'id': start_id + 7, 'cx': -cx3, 'cy': cx3, 'size': s3},
            {'id': start_id + 8, 'cx': cx4, 'cy': cx4, 'size': s4}
        ]

class OptimizedRunwayLayout(BaseLayoutStrategy):
    """16h5字典物理极限适配版：25标双轨短拉链阵列"""
    def generate_layout(self, X_size, start_id=0):
        # ==========================================
        # 1. 核心大标与中心微标 (占用 9 个 ID)
        # ==========================================
        inner_size = X_size * 0.0400
        inner_dist = X_size * 0.0400  # 中心标网格步长
        
        s1 = 0.4400 * X_size
        s2 = 0.4200 * X_size
        s3 = 0.4000 * X_size
        s4 = 0.3800 * X_size
        
        cx1 = 0.2800 * X_size
        cx2 = 0.2700 * X_size
        cx3 = 0.2600 * X_size
        cx4 = 0.2500 * X_size

        layout = [
            # ----- 内侧十字星团 (ID: start_id + 0 到 4) -----
            # 它们占据了距离中心 0 和 0.04 的位置
            {'id': start_id + 0, 'cx': 0, 'cy': 0, 'size': inner_size},
            {'id': start_id + 1, 'cx': 0, 'cy': -inner_dist, 'size': inner_size},
            {'id': start_id + 2, 'cx': 0, 'cy': inner_dist, 'size': inner_size},
            {'id': start_id + 3, 'cx': -inner_dist, 'cy': 0, 'size': inner_size},
            {'id': start_id + 4, 'cx': inner_dist, 'cy': 0, 'size': inner_size},
            
            # ----- 外侧极限漏斗 (ID: start_id + 5 到 8) -----
            {'id': start_id + 5, 'cx': -cx1, 'cy': -cx1, 'size': s1},
            {'id': start_id + 6, 'cx': cx2, 'cy': -cx2, 'size': s2},
            {'id': start_id + 7, 'cx': -cx3, 'cy': cx3, 'size': s3},
            {'id': start_id + 8, 'cx': cx4, 'cy': cx4, 'size': s4}
        ]

        # ==========================================
        # 2. 无缝延伸刻度线 (单臂 5 标，占用 20 个 ID)
        # ==========================================
        runway_size = 0.0400 * X_size
        
        # 完美继承中心星团 0.04 的网格步长，零缝隙往外贴合！
        # 一直铺满到 0.24 的核心视场区
        distances = [
            0.0800 * X_size, 
            0.1200 * X_size, 
            0.1600 * X_size, 
            0.2000 * X_size, 
            0.2400 * X_size
        ]
        
        curr_id = start_id + 9
        for d in distances:
            layout.extend([
                {'id': curr_id+0, 'cx': 0, 'cy': -d, 'size': runway_size},  # 正北通道
                {'id': curr_id+1, 'cx': 0, 'cy': d, 'size': runway_size},   # 正南通道
                {'id': curr_id+2, 'cx': -d, 'cy': 0, 'size': runway_size},  # 正西通道
                {'id': curr_id+3, 'cx': d, 'cy': 0, 'size': runway_size},   # 正东通道
            ])
            curr_id += 4

        return layout