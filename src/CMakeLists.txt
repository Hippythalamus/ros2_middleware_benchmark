cmake_minimum_required(VERSION 3.16)
project(benchmark_node)

# Modern C++17
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Compiler warnings — we write clean code
add_compile_options(-Wall -Wextra -Wpedantic)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)

# Include headers
include_directories(include)

# ---------- Publisher node ----------
add_executable(publisher
  src/publisher_node.cpp
)
ament_target_dependencies(publisher
  rclcpp std_msgs sensor_msgs geometry_msgs nav_msgs
)

# ---------- Subscriber node ----------
add_executable(subscriber
  src/subscriber_node.cpp
)
ament_target_dependencies(subscriber
  rclcpp std_msgs sensor_msgs geometry_msgs nav_msgs
)

# ---------- Clock sync checker ----------
add_executable(clock_check
  src/clock_check.cpp
)
ament_target_dependencies(clock_check
  rclcpp std_msgs
)

install(TARGETS
  publisher
  subscriber
  clock_check
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
