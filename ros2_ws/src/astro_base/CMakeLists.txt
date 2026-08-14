cmake_minimum_required(VERSION 3.8)
project(astro_base)

# Compiler settings
if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Find dependencies
find_package(ament_cmake REQUIRED)
find_package(rclpy REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(diagnostic_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

# Generate custom messages (ROS 2 otomatik olarak python mesaj paketini de üretecek)
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/WheelCmd.msg"
  "msg/HeadCmd.msg"
  DEPENDENCIES std_msgs
)

# Install Python executables - Çalıştırılabilir scriptimizi hedefe kopyalıyoruz
install(PROGRAMS
  astro_base/serial_bridge.py
  DESTINATION lib/${PROJECT_NAME}
)

# Linting
if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
