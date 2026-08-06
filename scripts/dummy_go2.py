#!/usr/bin/env python3
import json
import math
import re
import select
import threading
import time

import rospy
import uvicorn
from fastapi import FastAPI, HTTPException, Form # 引入 Form
from nav_msgs.msg import Odometry
from pymavlink import mavutil
from std_msgs.msg import Bool, String

# ==========================================
# FastAPI 实体与请求结构体定义
# ==========================================
app = FastAPI()
ros_node_instance = None

# 移除了原先的 PushRequest BaseModel，改用 Form 直接在接口中定义参数

@app.post("/api/push")
def api_push(
    content: str = Form(...), 
    sender: str = Form(...), 
    target: str = Form(...)
):
    global ros_node_instance
    if not ros_node_instance:
        raise HTTPException(status_code=500, detail="ROS 1 node not ready")

    # req.content 直接变成了参数 content
    rospy.loginfo(f"FastAPI Received: {content}")

    if content == "趴下":
        ros_node_instance.is_standing = False
        return {"status": "ok", "action": "lay_down"}

    elif content == "站起来":
        ros_node_instance.is_standing = True
        return {"status": "ok", "action": "stand_up"}

    elif content in ["锁定", "解锁"]:
        return {"status": "ok", "action": "mock_arm_disarm"}

    match = re.search(r"前往地图点([-+]?\d*\.?\d+)米([-+]?\d*\.?\d+)米", content)
    if match:
        if not ros_node_instance.is_standing:
            rospy.logwarn("拒绝执行：当前处于趴下状态！")
            raise HTTPException(status_code=403, detail="Dog is not standing")

        target_enu_x = float(match.group(1))
        target_enu_y = float(match.group(2))

        # 触发本地运动学模拟
        ros_node_instance.execute_navigation(target_enu_x, target_enu_y)
        return {
            "status": "ok",
            "action": "moving",
            "target_enu": [target_enu_x, target_enu_y],
        }

    raise HTTPException(status_code=400, detail="Unknown command format")


# ==========================================
# ROS 1 核心网关节点
# ==========================================
class MavlinkBridgeNode:
    def __init__(self):
        # 初始化 ROS 1 节点
        rospy.init_node("mavlink_bridge_node", anonymous=False)

        # --- 1. 状态与坐标系配置 ---
        self.gps_enabled = True
        self.is_standing = False

        # 狗在本地的实时坐标 (ENU) - 现在完全由本节点自主维护
        self.current_enu_x = 0.0
        self.current_enu_y = 0.0
        self.current_enu_z = 0.0

        # 全局参考原点 (用于将 ENU 转换为注入给飞控的经纬度)
        self.origin_lat = 30.2674  # 设定基准纬度
        self.origin_lon = 120.1528  # 设定基准经度
        self.origin_alt = 10.0  # 基准高度 (米)
        self.earth_radius = 6378137.0

        # 导航状态
        self.target_enu_x = None
        self.target_enu_y = None
        self.moving = False
        self.move_speed = 1.0  # 模拟移动速度
        self.i = 0

        # 线程安全锁
        self.fc_write_lock = threading.Lock()

        # --- 2. ROS 1 接口 ---
        self.sub_gps_switch = rospy.Subscriber(
            "/gps_switch", Bool, self.gps_switch_callback, queue_size=10
        )
        self.pub_loc = rospy.Publisher("/loc_base", Odometry, queue_size=10)
        self.pub_feedback = rospy.Publisher("/task/feedback", String, queue_size=10)

        # 10Hz 定时器：处理运动学更新与 GPS 注入
        # ROS 1 的 Timer 回调函数需要接收一个 TimerEvent 参数
        self.timer = rospy.Timer(rospy.Duration(0.1), self.timer_loop)

        # --- 3. MAVLink 连接 ---
        # self.fc_conn = mavutil.mavlink_connection("tcp:localhost:5760")
        # self.upper_conn = mavutil.mavlink_connection("tcpin:localhost:5761")
        # rospy.loginfo("MAVLink 连接初始化完成 (等待注入模式)。")

        # --- 4. 启动后台线程 ---
        # self.mav_thread = threading.Thread(
        #     target=self.mavlink_passthrough_loop, daemon=True
        # )
        # self.mav_thread.start()

        self.fastapi_thread = threading.Thread(
            target=self.start_fastapi_server, daemon=True
        )
        self.fastapi_thread.start()

    def gps_switch_callback(self, msg):
        self.gps_enabled = msg.data
        status = (
            "室外(恢复注入GPS)" if self.gps_enabled else "室内(停止注入GPS并拦截输出)"
        )
        rospy.loginfo(f"收到环境切换信号: {status}")

    def start_fastapi_server(self):
        uvicorn.run(app, host="0.0.0.0", port=8444, log_level="warning")

    def execute_navigation(self, enu_x, enu_y):
        self.target_enu_x = enu_x
        self.target_enu_y = enu_y
        self.moving = True
        rospy.loginfo(f"模拟器开始移动向 ENU: [{enu_x}, {enu_y}]")

    def enu_to_latlon(self, x, y):
        """将当前的 ENU 局部坐标转换为全局经纬度"""
        d_lat = (y / self.earth_radius) * (180.0 / math.pi)
        d_lon = (x / (self.earth_radius * math.cos(math.radians(self.origin_lat)))) * (
            180.0 / math.pi
        )
        return self.origin_lat + d_lat, self.origin_lon + d_lon

    def inject_virtual_gps(self):
        """持续向飞控注入 GPS_INPUT，根据环境开关动态修改信号质量"""
        lat, lon = self.enu_to_latlon(self.current_enu_x, self.current_enu_y)
        time_usec = int(time.time() * 1e6)

        ignore_flags = 8 | 16 | 32

        # 核心逻辑：根据室内外环境改变 GPS 状态
        if self.gps_enabled:
            fix_type = 3  # 3D Fix (卫星锁定)
            satellites = 12
        else:
            fix_type = 1  # 1 = No Fix (有传感器，但无有效定位)
            satellites = 0

        with self.fc_write_lock:
            self.fc_conn.mav.gps_input_send(
                time_usec,
                0,
                ignore_flags,
                0,
                0,
                fix_type,  # 动态注入 fix_type
                int(lat * 1e7),
                int(lon * 1e7),
                self.origin_alt,
                1.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                1.0,
                1.0,
                satellites,  # 动态卫星数
            )

    def mavlink_passthrough_loop(self):
        """纯粹的双向 TCP 透传，不再拦截覆盖位置数据"""
        while not rospy.is_shutdown():
            has_data = False

            # --- 飞控 -> 上位机 ---
            msg_fc = self.fc_conn.recv_match(blocking=False)
            if msg_fc:
                has_data = True
                if msg_fc.get_type() != "BAD_DATA":
                    self.upper_conn.write(msg_fc.get_msgbuf())

            # --- 上位机 -> 飞控 ---
            msg_upper = self.upper_conn.recv_match(blocking=False)
            if msg_upper:
                has_data = True
                if msg_upper.get_type() != "BAD_DATA":
                    with self.fc_write_lock:
                        self.fc_conn.write(msg_upper.get_msgbuf())

            if not has_data:
                time.sleep(0.002)

    def timer_loop(self, event):
        """10Hz 循环：自主运动学模拟计算，ENU 发布，以及 GPS 注入控制"""
        dt = 0.1  # 10Hz = 0.1s

        # 1. 模拟机器狗在本地自主维护的 ENU 坐标系的物理移动
        if (
            self.moving
            and self.target_enu_x is not None
            and self.target_enu_y is not None
        ):
            dx = self.target_enu_x - self.current_enu_x
            dy = self.target_enu_y - self.current_enu_y
            distance = math.hypot(dx, dy)

            if distance < 0.05:  # 到达目标
                self.current_enu_x = self.target_enu_x
                self.current_enu_y = self.target_enu_y
                self.moving = False

                rospy.loginfo("已到达目标地图点，发送反馈。")
                feedback_payload = {
                    "task": "地图点",
                    "params": [self.target_enu_x, self.target_enu_y],
                    "task_id": "zhL4dFAAzbnD",
                    "timestamp": time.time(),
                    "meta": {"stg": "takeover"},
                    "state": "ready",
                    "llm": "success",
                }

                fb_msg = String()
                fb_msg.data = json.dumps(feedback_payload, ensure_ascii=False)
                self.pub_feedback.publish(fb_msg)
            else:
                # 按照给定的速度平滑步进
                step = min(self.move_speed * dt, distance)
                self.current_enu_x += (dx / distance) * step
                self.current_enu_y += (dy / distance) * step

        # 2. 始终对外发布本地 Odometry
        odom = Odometry()
        odom.header.stamp = rospy.Time.now()
        odom.header.frame_id = "odom"
        odom.child_frame_id = "base_link"
        odom.pose.pose.position.x = self.current_enu_x
        odom.pose.pose.position.y = self.current_enu_y
        odom.pose.pose.position.z = self.current_enu_z
        self.pub_loc.publish(odom)

        if self.i % 10 == 0:
            print(f"x={self.current_enu_x:.2f} y={self.current_enu_y:.2f}")
        self.i += 1

        # 3. 将自主维护的 ENU 转回经纬度，注入给飞控
        # self.inject_virtual_gps()


def main():
    global ros_node_instance
    ros_node_instance = MavlinkBridgeNode()

    try:
        rospy.spin()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()