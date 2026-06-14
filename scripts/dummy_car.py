#!/usr/bin/env python3
"""
报错找不到CAN bus:

sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set up vcan0
"""

import rospy
import can
import cantools
import math
import os
import threading

from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry

class VcuCanRosBridge:
    def __init__(self):
        rospy.init_node('vcu_can_ros_bridge', anonymous=True)
        
        # ==========================================
        # 1. 基础配置与参数
        # ==========================================
        # 根据 W6 规格书，三轴车阿克曼转向轴距(前轴到中轴)为 0.82m
        self.wheelbase = rospy.get_param('~wheelbase', 0.82) 
        self.can_interface = rospy.get_param('~can_interface', 'vcan0')
        
        # 原地掉头时的最大角速度映射基准 (rad/s)，需配合 Gazebo 物理属性调整
        self.max_rot_yaw_rate = rospy.get_param('~max_rot_yaw_rate', 1.0) 
        
        script_dir = os.path.dirname(os.path.realpath(__file__))
        try:
            self.db = cantools.database.load_file(os.path.join(script_dir, "..", "config", 'IPC_VCU_ZRD.dbc'))
            self.bus = can.interface.Bus(channel=self.can_interface, interface='socketcan')
            rospy.loginfo("成功连接 CAN 总线并加载 DBC。")
        except Exception as e:
            rospy.logerr(f"初始化失败: {e}")
            exit(1)

        # ==========================================
        # 2. ROS 接口
        # ==========================================
        self.cmd_pub = rospy.Publisher('/ugv_0/cmd_vel', Twist, queue_size=10)
        self.odom_sub = rospy.Subscriber('/ugv_0/odom', Odometry, self.odom_callback)

        # ==========================================
        # 3. 内部状态机 (用于 0x201 上报)
        # ==========================================
        self.state_lock = threading.Lock()
        self.current_gear = 0         # P档
        self.current_angle_deg = 0.0  # 当前角度/转速指令
        self.current_speed_kmh = 0.0  # 当前车速
        self.current_epo_sts = 0      # 急停状态

        # ==========================================
        # 4. 启动双向通信
        # ==========================================
        self.rx_thread = threading.Thread(target=self.can_rx_loop)
        self.rx_thread.daemon = True
        self.rx_thread.start()

        self.tx_timer = rospy.Timer(rospy.Duration(0.02), self.can_tx_callback)

        rospy.loginfo("桥接节点已就绪：支持阿克曼与原地掉头双模式解析。")

    # ---------------------------------------------------------
    # [上行] 获取仿真真实速度
    # ---------------------------------------------------------
    def odom_callback(self, msg):
        real_speed_ms = msg.twist.twist.linear.x
        with self.state_lock:
            self.current_speed_kmh = abs(real_speed_ms) * 3.6

    # ---------------------------------------------------------
    # [上行] 打包并发送 0x201 状态报文
    # ---------------------------------------------------------
    def can_tx_callback(self, event):
        with self.state_lock:
            status_data = {
                'Drive_Mode': 1,  # 1: 自动模式(线控)
                'Gear': self.current_gear,
                'EPOSts': self.current_epo_sts,
                'Car_Speed': self.current_speed_kmh,
                'Angle': self.current_angle_deg,
                
                'YK_H': 0, 'YK_F': 0,
                'FLMCU_Fatus': 0, 'FRMCU_Fault': 0,
                'MLMCU_Fault': 0, 'MRMCU_Fault': 0,
                'RLMCU_Fault': 0, 'RRMCU_Fault': 0,
                'EBS1_Fault': 0, 'EBS2_Fault': 0,
                'EPB_LFRSts': 0, 'EPB_RFRSts': 0,
                'EPB_MLSts': 0, 'EPB_MRSts': 0
            }

        try:
            payload = self.db.encode_message(513, status_data) # 0x201 = 513
            msg = can.Message(arbitration_id=513, data=payload, is_extended_id=False)
            self.bus.send(msg)
        except Exception as e:
            pass # 抑制高频日志

    # ---------------------------------------------------------
    # [下行] 监听 0x210 指令并转化为 ROS 控制
    # ---------------------------------------------------------
    def can_rx_loop(self):
        twist_msg = Twist()
        
        while not rospy.is_shutdown():
            try:
                msg = self.bus.recv(timeout=0.1)
                if msg is not None and msg.arbitration_id == 528: # 0x210 = 528
                    # cantools 自动处理了 signed 补码转换，这里拿到的就是带符号的十进制整数
                    data = self.db.decode_message(msg.arbitration_id, msg.data, decode_choices=False)

                    # 1. 提取指令数据
                    domain_ctrl_epo = data.get('DomainCtrl_EPO', 0)
                    car_off = data.get('Car_OFF', 0)
                    ipc_en = data.get('IPC_En', 0)
                    target_gear = data.get('Target_Gear', 0)
                    brake_en = data.get('Brake_En', 0)
                    target_pressure = data.get('Target_Pressure', 0.0)
                    
                    steering_mode = data.get('SteeringMode', 0)      # 0: 阿克曼, 1: 原地掉头
                    target_speed_kmh = data.get('Target_Speed', 0.0)
                    target_angle_val = data.get('Target_Angle', 0.0) # 注意：含义随 mode 改变

                    # 2. 状态机同步
                    with self.state_lock:
                        self.current_gear = target_gear
                        self.current_angle_deg = target_angle_val
                        self.current_epo_sts = 2 if domain_ctrl_epo == 1 else 0 

                    # 3. 准备 ROS 速度指令
                    twist_msg.linear.x = 0.0
                    twist_msg.angular.z = 0.0

                    # 4. 安全拦截 (切断动力)
                    if (domain_ctrl_epo == 1 or car_off == 1 or ipc_en == 0 or 
                        target_gear == 0 or target_gear == 2 or 
                        (brake_en == 1 and target_pressure > 0.1)):
                        self.cmd_pub.publish(twist_msg)
                        continue

                    # 5. 运动学逆向解析 (CAN -> Gazebo)
                    if steering_mode == 1:
                        # 【状态 A：原地掉头】
                        # Target_Angle 被劫持为自转速度映射 [-300, 300]
                        # cantools 已将 0xFFB0 自动解析为 -80，直接使用即可
                        
                        twist_msg.linear.x = 0.0 # 差速掉头时无前后位移
                        
                        # 线性映射：将 [-300, 300] 映射到真实的角速度 rad/s 以驱动 Gazebo
                        # 符号一致性：底盘协议 CCW(正数)为左转，在 ROS 中正角速度也是左转，直接按比例相乘
                        twist_msg.angular.z = (target_angle_val / 300.0) * self.max_rot_yaw_rate
                        
                    else:
                        # 【状态 B：阿克曼正常转向】
                        speed_ms = target_speed_kmh / 3.6
                        if target_gear == 1: # 倒挡
                            speed_ms = -abs(speed_ms)
                        
                        # 保护性限幅：防止上层下发越界的物理角度
                        clamped_angle_deg = max(min(target_angle_val, 25.0), -25.0)
                        angle_rad = clamped_angle_deg * (math.pi / 180.0)

                        twist_msg.linear.x = speed_ms
                        if speed_ms != 0.0:
                            # 逆向单轨模型计算偏航角速度：ω = v * tan(δ) / L
                            twist_msg.angular.z = speed_ms * math.tan(angle_rad) / self.wheelbase
                    
                    # 6. 发布指令给 Gazebo
                    self.cmd_pub.publish(twist_msg)

            except Exception as e:
                pass 

if __name__ == '__main__':
    try:
        VcuCanRosBridge()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass