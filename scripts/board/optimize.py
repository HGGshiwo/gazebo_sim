import numpy as np
from scipy.optimize import minimize

def layout_optimization():
    # ==========================================
    # 1. 定义目标函数 (Cost Function)
    # x = [inner_size, inner_dist, s1, s2, s3, s4, cx1, cx2, cx3, cx4]
    # ==========================================
    def objective(x):
        inner_size, inner_dist = x[0], x[1]
        sizes = x[2:6]
        
        # 总面积 (5个内侧小标 + 4个外侧大标)
        total_area = 5 * (inner_size**2) + np.sum(sizes**2)
        
        # 盲区半径 (内部星团伸出的最远距离)
        # 惩罚项：半径越大，盲区越高，得分越低。我们用 2.0 的权重强压盲区。
        inner_radius = inner_dist + inner_size / 2.0
        
        # SciPy 是求最小值，所以我们要取负面积 (最大化面积) + 惩罚项
        return -total_area + 2.0 * inner_radius

    # ==========================================
    # 2. 定义绝对物理约束 (Hard Constraints)
    # 所有约束条件必须 >= 0
    # ==========================================
    def constraints_dict():
        cons = []
        
        # 约束 1：内侧十字绝不能与中心标签重叠
        # inner_dist - inner_size/2 必须 >= 中心标签的边缘 inner_size/2
        cons.append({'type': 'ineq', 'fun': lambda x: x[1] - x[0]})
        
        # 约束 2：外侧大标签的内边缘，必须 >= 内侧星团的外边缘 (绝不重叠)
        for i in range(4):
            cons.append({'type': 'ineq', 'fun': lambda x, idx=i: (x[6+idx] - x[2+idx]/2.0) - (x[1] + x[0]/2.0)})
            
        # 约束 3：外侧大标签的外边缘，必须 <= 画板的物理极限 (0.5)
        for i in range(4):
            cons.append({'type': 'ineq', 'fun': lambda x, idx=i: 0.5 - (x[6+idx] + x[2+idx]/2.0)})
            
        # 约束 4：FOV 阶梯脱离漏斗 (极其关键)
        # 保证外缘依次向内收缩，差距至少为 0.02 (占总宽的 2%)，确保无人机下降时标签逐个、平滑地飞出画面
        for i in range(3):
            cons.append({'type': 'ineq', 'fun': lambda x, idx=i: (x[6+idx] + x[2+idx]/2.0) - (x[7+idx] + x[3+idx]/2.0) - 0.02})
            
        return cons

    # ==========================================
    # 3. 变量初始猜测与边界 (Bounds)
    # ==========================================
    # 初始猜测值 (随便给一个合法的大概范围)
    x0 = [0.06, 0.08,  0.3, 0.25, 0.2, 0.15,  0.3, 0.25, 0.2, 0.15]
    
    # 每个变量的取值范围 (min, max)
    bounds = [
        (0.04, 0.10),  # x[0]: inner_size (最小不能小于 4%，否则相机分辨率跟不上)
        (0.04, 0.15),  # x[1]: inner_dist
        (0.15, 0.50),  # x[2]: s1
        (0.15, 0.50),  # x[3]: s2
        (0.15, 0.50),  # x[4]: s3
        (0.15, 0.50),  # x[5]: s4
        (0.10, 0.50),  # x[6]: cx1
        (0.10, 0.50),  # x[7]: cx2
        (0.10, 0.50),  # x[8]: cx3
        (0.10, 0.50),  # x[9]: cx4
    ]

    # ==========================================
    # 4. 执行 SLSQP 算法求解
    # ==========================================
    print("🚀 正在启动空间最优化搜索引擎...")
    result = minimize(objective, x0, method='SLSQP', bounds=bounds, constraints=constraints_dict(), options={'disp': True, 'maxiter': 1000})

    if result.success:
        print("\n✅ 寻优成功！以下是达到物理极限的布局参数：\n")
        x = result.x
        inner_size, inner_dist = x[0], x[1]
        s1, s2, s3, s4 = x[2:6]
        cx1, cx2, cx3, cx4 = x[6:10]
        
        # 计算盲区高度 (假设 60° FOV)
        inner_max_span = (inner_dist + inner_size / 2.0) * 2
        blind_spot_ratio = inner_max_span / 1.15
        
        print(f"🔹 贴地盲区评估: 在 60° FOV 下，盲区高度被压缩至画板宽度的 {blind_spot_ratio*100:.1f}%")
        print(f"   (如果打印 1x1 米的画板，无人机下降到离地 {blind_spot_ratio*100:.1f} 厘米时，中心标才会丢失)\n")

        print("将以下代码直接复制到 layouts.py 的 BaseLayoutStrategy 实现中：\n")
        print("-" * 50)
        print(f"        # 机器优化的绝对极限参数")
        print(f"        inner_size = X_size * {inner_size:.4f}")
        print(f"        inner_dist = X_size * {inner_dist:.4f}")
        print(f"        ")
        print(f"        s1 = {s1:.4f} * X_size")
        print(f"        s2 = {s2:.4f} * X_size")
        print(f"        s3 = {s3:.4f} * X_size")
        print(f"        s4 = {s4:.4f} * X_size")
        print(f"        ")
        print(f"        cx1 = {cx1:.4f} * X_size")
        print(f"        cx2 = {cx2:.4f} * X_size")
        print(f"        cx3 = {cx3:.4f} * X_size")
        print(f"        cx4 = {cx4:.4f} * X_size")
        print("-" * 50)
    else:
        print("❌ 寻优失败，未找到满足所有约束的解。")

if __name__ == "__main__":
    layout_optimization()