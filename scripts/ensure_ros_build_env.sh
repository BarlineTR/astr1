#!/usr/bin/env bash
# colcon --symlink-install needs setuptools < 80 (develop --editable was removed in v80+)
set -euo pipefail

echo "==> ROS 2 build ortamı hazırlanıyor..."
pip3 install --upgrade "setuptools>=65,<80" wheel

python3 - <<'PY'
import setuptools
v = setuptools.__version__
print(f"setuptools {v}")
major = int(v.split(".")[0])
if major >= 80:
    raise SystemExit("HATA: setuptools hâlâ >= 80. pip3 install 'setuptools==69.5.1' deneyin.")
print("✅ setuptools sürümü colcon --symlink-install ile uyumlu")
PY

echo ""
echo "Derleme:"
echo "  cd ~/Desktop/astr1/ros2_ws"
echo "  colcon build --symlink-install"
echo ""
echo "Hâlâ hata alırsanız symlink olmadan derleyin:"
echo "  colcon build"
