#!/bin/bash
set -e

# Source ROS2 and workspace
source /opt/ros/humble/setup.bash
source /ws/install/setup.bash

exec "$@"
