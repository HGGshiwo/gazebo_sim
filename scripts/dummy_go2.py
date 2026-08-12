#!/usr/bin/env python3
import json
import math
import re
import threading
import time

import rospy
import tf
from geometry_msgs.msg import Pose, Quaternion
from nav_msgs.msg import Odometry
from pymavlink import mavutil
from std_msgs.msg import Bool, String


# ==========================================
# ROS 1 核心节点 (Dank 协议 & Map TF 全局坐标对齐)
# ==========================================
class DummyGo2Node:
    def __init__(self):
        rospy.init_node("dank", anonymous=False)

        # --- 1. 状态与坐标系配置 ---
        self.gps_enabled = True
        
        # Mode 状态: 1(站立解锁), 7(站立锁定), 6(趴下/坐下)
        self.mode = 6  # 默认初始为趴下/坐下状态
        self.battery = 100  # 模拟电量 100%
        self.last_status_update = time.time()

        # 狗在本地的实时坐标 (通过 TF 同步 map 全局地图坐标)
        self.current_enu_x = 0.0
        self.current_enu_y = 0.0
        self.current_enu_z = 0.0
        self.current_quat = (0.0, 0.0, 0.0, 1.0)
        self.is_map_aligned = False
        self.latest_odom = None
        self.pose_lock = threading.Lock()

        # TF 监听器：监听 map -> base_footprint 全局坐标系变换
        self.tf_listener = tf.TransformListener()

        # 全局参考原点 (用于将 ENU 转换为注入给飞控的经纬度)
        self.origin_lat = 30.2674  # 基准纬度
        self.origin_lon = 120.1528  # 基准经度
        self.origin_alt = 10.0      # 基准高度 (米)
        self.earth_radius = 6378137.0

        # 导航状态
        self.target_enu_x = None
        self.target_enu_y = None
        self.moving = False

        # 线程安全锁
        self.fc_write_lock = threading.Lock()

        # --- 2. ROS 1 接口 ---
        # Dank 接口 1: 订阅动作指令
        self.sub_dank_action = rospy.Subscriber(
            "/dank/action", String, self.dank_action_callback, queue_size=10
        )
        # Dank 接口 2: 状态上报 (默认 2 Hz)
        self.pub_dank_status = rospy.Publisher(
            "/dank/status", String, queue_size=10
        )

        # 姿态控制接口：发布给 CHAMP 控制器，驱动 Gazebo 中机器狗实际站立/趴下
        self.pub_body_pose = rospy.Publisher(
            "/body_pose", Pose, queue_size=10
        )

        # 备用里程计订阅 (当 map TF 未就绪时回退使用)
        self.sub_odom = rospy.Subscriber(
            "/odom", Odometry, self.odom_callback, queue_size=10
        )

        self.sub_gps_switch = rospy.Subscriber(
            "/gps_switch", Bool, self.gps_switch_callback, queue_size=10
        )
        self.pub_loc = rospy.Publisher("/loc_base", Odometry, queue_size=10)
        self.pub_feedback = rospy.Publisher("/task/feedback", String, queue_size=10)

        # 启动时立刻执行初始姿态设置（趴下/坐下）
        self.publish_posture_cmd()

        # 定时器：2 Hz 发布 /dank/status
        self.timer_status = rospy.Timer(rospy.Duration(0.5), self.publish_dank_status)

        # 定时器：10 Hz 处理姿态维持、坐标更新、导航到达检测与定位转发
        self.timer_loop = rospy.Timer(rospy.Duration(0.1), self.control_loop)

        rospy.loginfo("DummyGo2 Dank 适配节点已启动：支持 map 全局地图坐标对齐与 /dank 接口。")

    @property
    def is_standing(self):
        """当前是否处于站立状态 (mode 为 1 或 7)"""
        return self.mode in [1, 7]

    # ---------------------------------------------------------
    # [Gazebo 姿态控制] 驱动 CHAMP 控制器实现趴下/坐下或站立
    # ---------------------------------------------------------
    def publish_posture_cmd(self):
        """根据当前 mode 发布 /body_pose，控制 Gazebo 机器狗姿态"""
        pose = Pose()
        pose.orientation.w = 1.0
        if self.mode == 6:
            # 趴下/坐下：降低机身高度使得腿部完全折叠伏地
            pose.position.z = -0.18
        else:
            # 站立 (mode 1 或 7)：恢复标称高度
            pose.position.z = 0.0
        self.pub_body_pose.publish(pose)

    # ---------------------------------------------------------
    # [全局地图坐标同步] 通过 TF 获取 map -> base_footprint
    # ---------------------------------------------------------
    def update_pose_from_tf(self):
        """从 TF 树查询机器狗在 map 全局地图坐标系下的位姿"""
        try:
            (trans, rot) = self.tf_listener.lookupTransform("map", "base_footprint", rospy.Time(0))
            with self.pose_lock:
                self.current_enu_x = trans[0]
                self.current_enu_y = trans[1]
                self.current_enu_z = trans[2]
                self.current_quat = rot
                self.is_map_aligned = True
            return True
        except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
            # 若 map TF 尚未发布（如 SLAM 刚启动），则保留 odom 回退值
            return False

    def odom_callback(self, msg: Odometry):
        with self.pose_lock:
            self.latest_odom = msg
            if not self.is_map_aligned:
                self.current_enu_x = msg.pose.pose.position.x
                self.current_enu_y = msg.pose.pose.position.y
                self.current_enu_z = msg.pose.pose.position.z
                p_quat = msg.pose.pose.orientation
                self.current_quat = (p_quat.x, p_quat.y, p_quat.z, p_quat.w)

    # ---------------------------------------------------------
    # [Dank 接口 1] 动作指令处理 (/dank/action)
    # ---------------------------------------------------------
    def dank_action_callback(self, msg: String):
        """在独立后台线程中执行动作，不阻塞 ROS 回调"""
        threading.Thread(target=self._process_action, args=(msg.data,), daemon=True).start()

    def _process_action(self, raw_data: str):
        content = raw_data.strip()
        rospy.loginfo(f"[/dank/action] 收到指令: {content}")

        # 1. 尝试解析 JSON 格式指令
        action_cmd = content
        if content.startswith("{") and content.endswith("}"):
            try:
                data = json.loads(content)
                for key in ["action", "name", "cmd", "data"]:
                    if key in data:
                        action_cmd = str(data[key]).strip()
                        break
            except Exception as e:
                rospy.logwarn(f"JSON 解析失败: {e}")

        cmd_lower = action_cmd.lower()

        # 2. 状态机动作匹配与 mode 更新
        if cmd_lower in ["stand", "standup", "站立", "站起来", "起立"]:
            self.mode = 1  # 站立解锁
            self.last_status_update = time.time()
            self.publish_posture_cmd()
            rospy.loginfo("[Dank] 动作执行: 站立解锁 -> mode 1 (物理站立)")

        elif cmd_lower in ["lie", "standdown", "sit", "趴下", "坐下"]:
            self.mode = 6  # 趴下/坐下
            self.moving = False
            self.last_status_update = time.time()
            self.publish_posture_cmd()
            rospy.loginfo("[Dank] 动作执行: 趴下/坐下 -> mode 6 (物理趴下)")

        elif cmd_lower in ["lock", "锁定"]:
            # 锁定规则：若当前已是 6 (趴下)，保持趴下(mode=6)；否则进入站立锁定(mode=7)
            if self.mode == 6:
                rospy.loginfo("[Dank] 当前已趴下(mode=6)，锁定指令保持趴下状态。")
            else:
                self.mode = 7  # 站立锁定
                rospy.loginfo("[Dank] 动作执行: 站立锁定 -> mode 7")
            self.last_status_update = time.time()
            self.publish_posture_cmd()

        elif cmd_lower in ["unlock", "解锁"]:
            self.mode = 1  # 站立解锁
            self.last_status_update = time.time()
            self.publish_posture_cmd()
            rospy.loginfo("[Dank] 动作执行: 解锁 -> mode 1 (物理站立)")

        else:
            # 兼容地图点导航命令（如：前往地图点1.5米-2.0米）
            match = re.search(r"前往地图点([-+]?\d*\.?\d+)米([-+]?\d*\.?\d+)米", action_cmd)
            if match:
                if self.mode != 1:
                    rospy.logwarn(f"拒绝执行导航：当前 mode={self.mode}，必须处于站立解锁(mode=1)状态！")
                    return
                target_x = float(match.group(1))
                target_y = float(match.group(2))
                self.execute_navigation(target_x, target_y)
            else:
                rospy.logwarn(f"[Dank] 未知指令: {action_cmd}")

    # ---------------------------------------------------------
    # [Dank 接口 2] 状态定时发布 (/dank/status @ 2Hz)
    # ---------------------------------------------------------
    def publish_dank_status(self, event):
        status_payload = {
            "mode": self.mode,
            "battery": self.battery,
            "last_update": self.last_status_update,
        }
        msg = String()
        msg.data = json.dumps(status_payload, ensure_ascii=False)
        self.pub_dank_status.publish(msg)

    def execute_navigation(self, enu_x, enu_y):
        self.target_enu_x = enu_x
        self.target_enu_y = enu_y
        self.moving = True
        rospy.loginfo(f"开始前往地图目标点 (map frame): [{enu_x}, {enu_y}]")

    def gps_switch_callback(self, msg):
        self.gps_enabled = msg.data
        status = "室外(恢复注入GPS)" if self.gps_enabled else "室内(停止注入GPS并拦截输出)"
        rospy.loginfo(f"收到环境切换信号: {status}")

    def control_loop(self, event):
        """10Hz 控制循环：持续维持物理姿态、更新全局位姿、检测导航到达，并发布 /loc_base"""
        # 1. 维持物理姿态 (趴下或站立)
        self.publish_posture_cmd()

        # 2. 从 TF 更新 map 坐标系下的真实全局位姿
        self.update_pose_from_tf()

        with self.pose_lock:
            cur_x = self.current_enu_x
            cur_y = self.current_enu_y
            cur_z = self.current_enu_z
            cur_q = self.current_quat
            frame_id = "map" if self.is_map_aligned else "odom"

        # 3. 检测是否到达目标地图点 (基于全局 map 坐标系)
        if (
            self.moving
            and self.target_enu_x is not None
            and self.target_enu_y is not None
        ):
            distance = math.hypot(self.target_enu_x - cur_x, self.target_enu_y - cur_y)
            if distance < 0.2:  # 到达容差 0.2 米
                self.moving = False
                rospy.loginfo(f"已到达地图目标点 [{self.target_enu_x}, {self.target_enu_y}]，发送反馈。")
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

        # 4. 定位发布 (/loc_base)：严格对齐全局 map 坐标系
        loc_msg = Odometry()
        loc_msg.header.stamp = rospy.Time.now()
        loc_msg.header.frame_id = frame_id
        loc_msg.child_frame_id = "base_footprint"
        loc_msg.pose.pose.position.x = cur_x
        loc_msg.pose.pose.position.y = cur_y
        loc_msg.pose.pose.position.z = cur_z
        loc_msg.pose.pose.orientation = Quaternion(*cur_q)
        self.pub_loc.publish(loc_msg)


def main():
    DummyGo2Node()
    try:
        rospy.spin()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()