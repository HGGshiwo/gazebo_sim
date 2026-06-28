import os
import cv2
import numpy as np
import matplotlib.pyplot as plt

def generate_and_visualize():
    # ------------------ 1. 配置输入文件路径 ------------------
    base_path = "/home/hgg/catkin_ws/src/gazebo_sim/models/nathan_benderson_park/materials/textures"
    heightmap_path = f"{base_path}/Heightmap_Fixed.png"  # 使用我们之前清洗过的标准高度图
    if not os.path.exists(heightmap_path):
        heightmap_path = "Heightmap.png"
   
    grass_path = f"{base_path}/Grass_Albedo.png"  # 请根据实际后缀修改(.png/.jpg)
    sand_path = f"{base_path}/Sand_Albedo.png"
    
    output_path = f"{base_path}/Park_Albedo.png"

    print("=" * 60)
    print(" 🌲 Gazebo 11 离线多层地形纹理生成器 🌲")
    print("=" * 60)

    # 检查文件是否存在
    for p in [heightmap_path, grass_path, sand_path]:
        if not os.path.exists(p):
            print(f"❌ 错误: 找不到关键文件 {p}，请检查路径和文件名大小写！")
            return

    # ------------------ 2. 读取图像 ------------------
    print("[1/4] 正在加载地表材质和高度数据...")
    height_img = cv2.imread(heightmap_path, cv2.IMREAD_GRAYSCALE)
    grass_img = cv2.imread(grass_path)
    sand_img = cv2.imread(sand_path)

    H, W = height_img.shape
    
    # 将草地和沙子缩放到和高度图一样的大分辨率，方便像素级混合
    grass_resized = cv2.resize(grass_img, (W, H), interpolation=cv2.INTER_LINEAR)
    sand_resized = cv2.resize(sand_img, (W, H), interpolation=cv2.INTER_LINEAR)

    # ------------------ 3. 核心：基于物理高度生成混合权重图 ------------------
    print("[2/4] 正在根据高度分布计算沙、草混色权重...")
    
    # 你的地形最高像素是 143，我们设定一个合理的过渡区间
    # 假设像素值低于 50 (约1.3米) 为纯沙子（水边/低洼）
    # 像素值高于 90 (约2.5米) 为纯草地
    # 50 到 90 之间做柔和渐变
    min_pixel = 50 
    max_pixel = 90 

    # 计算草地的权重矩阵 (0.0 代表纯沙子，1.0 代表纯草地)
    weight = (height_img.astype(np.float32) - min_pixel) / (max_pixel - min_pixel)
    weight = np.clip(weight, 0.0, 1.0) # 将数据限制在 0~1 之间
    
    # 扩展成 3 通道 (BGR)，以便和彩色图片做矩阵乘法
    weight_3ch = np.repeat(weight[:, :, np.newaxis], 3, axis=2)

    # 混合公式：最终图像 = 草地 * 权重 + 沙子 * (1 - 权重)
    park_albedo = (grass_resized.astype(np.float32) * (1.0 - weight_3ch) + 
                   sand_resized.astype(np.float32) * weight_3ch)
    park_albedo = np.clip(park_albedo, 0, 255).astype(np.uint8)

    # ------------------ 4. 保存最终的铺满大图 ------------------
    print(f"[3/4] 正在保存生成的一整张大贴图到: {output_path}")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cv2.imwrite(output_path, park_albedo)

    # ------------------ 5. 屏幕直接给出可视化图像 ------------------
    print("[4/4] 🚀 正在生成屏幕预览对比图...")
    
    plt.figure(figsize=(12, 5))

    # 左图：高度图起伏预览
    plt.subplot(1, 2, 1)
    plt.imshow(height_img, cmap='gray')
    plt.title('1. Heightmap 起伏分析 (黑低白高)')
    plt.colorbar(label='像素值 (高度)')

    # 右图：生成的最终拼接地表图
    plt.subplot(1, 2, 2)
    # OpenCV 默认是 BGR，Matplotlib 渲染需要转成 RGB
    plt.imshow(cv2.cvtColor(park_albedo, cv2.COLOR_BGR2RGB))
    plt.title('2. 生成的 Park_Albedo.png 效果')

    plt.tight_layout()
    print("\n💡 提示: 已经弹出了图像窗口。如果你在远程SSH或Docker里，请确保开启了X11转发。")
    print("=" * 60)
    plt.show() # 这一步会直接在屏幕上弹出图片窗口

if __name__ == "__main__":
    generate_and_visualize()