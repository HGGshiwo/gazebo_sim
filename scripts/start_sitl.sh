#!/bin/bash
echo "正在启动sitl..."
sleep 2
sim_vehicle.py --no-rebuild --no-mavproxy -v Copter  --custom-location=30.1119319,120.140883,0,0