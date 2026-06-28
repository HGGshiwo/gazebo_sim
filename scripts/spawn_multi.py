#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import math
import argparse
import subprocess
import logging
import time
import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

# 初始化日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

app = FastAPI(title="Gazebo ArduPilot 多机自动仿真管理服务")

# ================= 全局配置 & 状态 =================
BASE_LAT = 30.1119319
BASE_LON = 120.140883
EARTH_RADIUS = 6378137.0  # 地球半径（米）

# 存储正在运行的后台进程 { instance_id: [proc1, proc2, ...] }
running_processes = {}
current_instance_id = 0

# 基础脚本与包名配置
SPAWN_SCRIPT_NAME = "spawn_drone.py"
ROS_PACKAGE_NAME = "gazebo_sim"
# ==================================================


class DroneSpawnRequest(BaseModel):
    x: float  # 相对坐标 X (米，指向正北)
    y: float  # 相对坐标 Y (米，指向正东)


def xy_to_latlon(x: float, y: float, base_lat: float, base_lon: float):
    """将相对坐标 (x, y) 转换为绝对经纬度 (X朝北，Y朝东)"""
    delta_lat = (x / EARTH_RADIUS) * (180.0 / math.pi)
    delta_lon = (y / (EARTH_RADIUS * math.cos(math.radians(base_lat)))) * (
        180.0 / math.pi
    )
    return base_lat + delta_lat, base_lon + delta_lon


def execute_spawn_pipeline(idx: int, x_val: float, y_val: float):
    """核心流水线：生成Gazebo模型 -> 启动SITL飞控 -> 启动dankong控制端"""
    z_val = 5.0  # 固定高度为 5，防止卡入地面

    # 1. 计算绝对经纬度和端口
    abs_lat, abs_lon = xy_to_latlon(x_val, y_val, BASE_LAT, BASE_LON)
    mavsdk_port = 5760 + 10 * idx

    logging.info(f"[ID {idx}] 开始部署流水线...")
    logging.info(
        f"[ID {idx}] 相对坐标: ({x_val}, {y_val}, {z_val}) -> 绝对位置: ({abs_lat}, {abs_lon})"
    )

    running_processes[idx] = []

    # ---- 步骤 1: 调用 ROS 正则脚本注入 Gazebo 模型 ----
    spawn_cmd = [
        "rosrun",
        ROS_PACKAGE_NAME,
        SPAWN_SCRIPT_NAME,
        str(idx),
        str(x_val),
        str(y_val),
        str(z_val),
    ]
    logging.info(f"[ID {idx}] 正在向 Gazebo 注入模型...")
    ret = subprocess.call(spawn_cmd)
    if ret != 0:
        logging.error(f"[ID {idx}] Gazebo 模型注入失败，错误码: {ret}")
        return False

    # ---- 步骤 2: 异步启动 ArduPilot SITL 仿真核心 ----
    sitl_cmd = [
        "sim_vehicle.py",
        "--no-rebuild",
        "--no-mavproxy",
        "-v",
        "ArduCopter",
        "-f",
        "gazebo-iris",
        f"--custom-location={abs_lat},{abs_lon},0,0",
        "-I",
        str(idx),
    ]
    logging.info(f"[ID {idx}] 正在后台启动 sim_vehicle.py...")
    sitl_proc = subprocess.Popen(
        sitl_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    running_processes[idx].append(sitl_proc)

    # ---- 步骤 3: 异步启动上层控制端 dankong ----
    dankong_cmd = [
        "dankong",
        "--config",
        "config/drone-config.yaml",
        "--mavsdk_url",
        f"tcp://127.0.0.1:{mavsdk_port}",
        "--port",
        str(8001 + idx),
    ]
    time.sleep(3)
    logging.info(f"[ID {idx}] 正在后台启动 dankong 控制端 (端口: {8001 + idx}, tcp://127.0.0.1:{mavsdk_port})...")
    dankong_proc = subprocess.Popen(
        dankong_cmd, stdout=sys.stdout, stderr=sys.stderr
    )
    running_processes[idx].append(dankong_proc)

    return True


@app.post("/spawn_drone", summary="通过API单架创建无人机")
async def api_spawn_drone(request: DroneSpawnRequest):
    global current_instance_id
    idx = current_instance_id

    success = execute_spawn_pipeline(idx, request.x, request.y)
    if not success:
        raise HTTPException(status_code=500, detail="无人机流水线启动失败")

    current_instance_id += 1
    return {"status": "success", "instance_id": idx}


@app.delete("/clear_all", summary="一键关闭所有仿真进程")
async def clear_all():
    global current_instance_id
    count = 0
    for idx in list(running_processes.keys()):
        for p in running_processes[idx]:
            try:
                p.kill()
            except:
                pass
        del running_processes[idx]
        count += 1
    current_instance_id = 0
    return {"status": "success", "message": f"已成功清理 {count} 个实例的后台进程"}


def load_config_and_spawn(config_path: str):
    """解析外部传入的 YAML 文件并批量动态生成无人机"""
    global current_instance_id
    if not os.path.exists(config_path):
        logging.error(f"找不到配置文件: {config_path}")
        sys.exit(1)

    with open(config_path, "r") as f:
        try:
            config_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            logging.error(f"YAML 解析失败: {e}")
            sys.exit(1)

    drones_list = config_data.get("drones", [])
    if not drones_list:
        logging.warning("配置文件中的 drones 列表为空")
        return

    logging.info(f"===> 检测到配置文件包含 {len(drones_list)} 架无人机，开始批量动态生成 <===")
    for drone in drones_list:
        x = float(drone.get("x", 0.0))
        y = float(drone.get("y", 0.0))

        idx = current_instance_id
        success = execute_spawn_pipeline(idx, x, y)
        if success:
            current_instance_id += 1

    logging.info("===> 批量初始化流水线发射完毕 <===")


if __name__ == "__main__":
    # 1. 解析纯命令行参数，过滤掉 ROS 自动附加的参数
    parser = argparse.ArgumentParser(
        description="FastAPI Simulation Server with Auto Batch Spawn."
    )
    parser.add_argument("--config", type=str, help="传入包含 x, y 坐标列表的 YAML 配置文件路径")

    clean_args = [a for a in sys.argv[1:] if not a.startswith("__")]
    parsed_args = parser.parse_args(clean_args)

    # 2. 如果指定了 --config 参数，则在 FastAPI 服务完全拉起前，先执行批量动态生成逻辑
    if parsed_args.config:
        load_config_and_spawn(parsed_args.config)

    # 3. 启动 FastAPI 服务守护监听
    logging.info("正在启动 FastAPI 接口网关...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
