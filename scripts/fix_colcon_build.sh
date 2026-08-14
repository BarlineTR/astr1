#!/usr/bin/env bash
# ROS2 colcon --symlink-install breaks with setuptools >= 80
set -euo pipefail

echo "==> setuptools sürümü düzeltiliyor (colcon --symlink-install için <80 gerekli)..."
pip3 install 'setuptools>=58,<80'

echo "==> colcon build..."
cd "$(dirname "$0")/../ros2_ws"
colcon build --symlink-install "$@"

echo ""
echo "✅ Build tamam. source install/setup.bash ile ortamı yükleyin."
