#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
import tf
import geometry_msgs.msg

rospy.init_node('camera_pose_in_map')
br = tf.TransformListener()
pub = rospy.Publisher('/camera_pose_in_map', geometry_msgs.msg.PoseStamped, queue_size=1)

rate = rospy.Rate(50)
while not rospy.is_shutdown():
    try:
        # 查询 camera_link 在 map 下的变换
        (trans, rot) = br.lookupTransform('map', 'lidar_link', rospy.Time(0))
        pose = geometry_msgs.msg.PoseStamped()
        pose.header.frame_id = 'map'
        pose.header.stamp = rospy.Time.now()
        pose.pose.position.x = trans[0]
        pose.pose.position.y = trans[1]
        pose.pose.position.z = trans[2]
        pose.pose.orientation.x = rot[0]
        pose.pose.orientation.y = rot[1]
        pose.pose.orientation.z = rot[2]
        pose.pose.orientation.w = rot[3]
        pub.publish(pose)
    except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
        pass
    rate.sleep()
