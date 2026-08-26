#!/usr/bin/env bash

# 执行你的具体命令
echo "Running node_task_queue.py..."
python /home/hggshiwo/catkin_ws/src/agent/zbrain/node_task_queue.py

# 如果需要保持进程运行，可加循环或等待命令
exec "$@"