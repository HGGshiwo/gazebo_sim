#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import re
import rospy
import rospkg  # 引入 ROS 包管理库
from gazebo_msgs.srv import SpawnModel
from geometry_msgs.msg import Pose, Point, Quaternion

def spawn_drone_with_regex(instance_id, x, y, z):
    # 1. 根据传入的 ID 计算对应的端口和名称
    idx = int(instance_id)
    port_in = 9002 + (idx * 10)
    port_out = 9003 + (idx * 10)
    model_name = "iris_{}".format(idx)
    imu_name = "{}::iris::iris/imu_link::imu_sensor".format(model_name)
    
    # 2. 使用 rospack 自动查找包路径
    try:
        rospack = rospkg.RosPack()
        # 自动获取 gazebo_sim 功能包的绝对路径
        pkg_path = rospack.get_path('gazebo_sim')
        # 拼接完整的 SDF 文件路径
        sdf_path = os.path.join(pkg_path, 'models', 'ros_iris_with_ardupilot_realsense/model.sdf')
    except rospkg.ResourceNotFound:
        print("Error: ROS package 'gazebo_sim' not found. Please source your workspace.")
        sys.exit(1)

    if not os.path.exists(sdf_path):
        print("Error: Base SDF file not found at calculated path: {}".format(sdf_path))
        sys.exit(1)

    # 3. 读取原始 SDF 文件内容
    with open(sdf_path, 'r') as f:
        sdf_content = f.read()

    # 4. 使用正则表达式进行精确匹配和内容替换
    # 替换 <model name="..."> 为新名称 (count=1 确保只替换最外层的模型名)
    sdf_content = re.sub(r'<model\s+name=["\'][^"\']+["\']>', '<model name="{}">'.format(model_name), sdf_content, count=1)
    
    # 替换 <fdm_port_in> 标签中的数字
    sdf_content = re.sub(r'<fdm_port_in>\s*\d+\s*</fdm_port_in>', '<fdm_port_in>{}</fdm_port_in>'.format(port_in), sdf_content)
    
    # 替换 <fdm_port_out> 标签中的数字
    sdf_content = re.sub(r'<fdm_port_out>\s*\d+\s*</fdm_port_out>', '<fdm_port_out>{}</fdm_port_out>'.format(port_out), sdf_content)
    
    # 替换 <imuName> 标签中的完整路径
    sdf_content = re.sub(r'<imuName>\s*[^<]+\s*</imuName>', '<imuName>{}</imuName>'.format(imu_name), sdf_content)

    # 5. 封装 ROS 的初始位姿 (Pose)
    initial_pose = Pose()
    initial_pose.position = Point(float(x), float(y), float(z))
    initial_pose.orientation = Quaternion(0, 0, 0, 1) # 默认无旋转

    # 6. 初始化 ROS 节点并调用 Gazebo Spawn 服务
    rospy.init_node("spawn_drone_{}".format(idx), anonymous=True)
    
    rospy.loginfo("Waiting for gazebo spawn service...")
    rospy.wait_for_service("/gazebo/spawn_sdf_model")
    
    try:
        spawn_srv = rospy.ServiceProxy("/gazebo/spawn_sdf_model", SpawnModel)
        
        # 将通过正则修改后的 xml 字符串直接传入
        res = spawn_srv(
            model_name=model_name,
            model_xml=sdf_content,
            robot_namespace=model_name,
            initial_pose=initial_pose
        )
        rospy.loginfo("Successfully spawned {} at ({}, {}, {})".format(model_name, x, y, z))
        rospy.loginfo("Gazebo response: {}".format(res.status_message))
        
    except rospy.ServiceException as e:
        rospy.logerr("Service call failed: {}".format(e))

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: rosrun your_package spawn_drone_regex.py <instance_id> <x> <y> <z>")
        sys.exit(1)
        
    spawn_drone_with_regex(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])