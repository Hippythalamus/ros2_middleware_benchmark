FROM ros:humble-ros-base

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install CycloneDDS RMW (default in Humble) and dev tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-humble-rmw-cyclonedds-cpp \
    ros-humble-rmw-zenoh-cpp \
    ros-humble-sensor-msgs \
    ros-humble-geometry-msgs \
    ros-humble-nav-msgs \
    python3-pip \
    htop \
    && rm -rf /var/lib/apt/lists/*

# Python deps for analysis (installed in orchestrator only)
RUN pip3 install --no-cache-dir pandas matplotlib

# Create workspace
WORKDIR /ws
RUN mkdir -p src

# Copy source
COPY ./src/ src/benchmark_node/

# Build with C++17 (Release for accurate benchmarking)
RUN . /opt/ros/humble/setup.sh && \
    colcon build \
    --cmake-args \
        -DCMAKE_CXX_STANDARD=17 \
        -DCMAKE_BUILD_TYPE=Release \
    --packages-select benchmark_node

# Source workspace on entry
COPY ./docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
