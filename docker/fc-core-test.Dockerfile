# Offline test environment for fc_core.
#
# Why this exists: elder-plops is Linux Mint 21.2 (jammy-based) and ROS 2 Jazzy
# only ships for noble, so it cannot be apt-installed on the host. Running the
# suite on fc1 instead is unsafe -- test nodes would join ROS_DOMAIN_ID 69, the
# live chamber's domain, where a stray publisher could drive the real
# humidifier.
#
# Build:
#   docker build -f docker/fc-core-test.Dockerfile -t fc-core-test .
#
# Run (ALWAYS with --network none so no DDS traffic can escape):
#   docker run --rm --network none -v "$PWD/src/chambers:/src:ro" fc-core-test
FROM ros:jazzy

RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-jazzy-std-msgs \
        ros-jazzy-sensor-msgs \
        ros-jazzy-diagnostic-msgs \
        ros-jazzy-rosidl-default-generators \
        ros-jazzy-ament-cmake \
        python3-pytest \
        python3-colcon-common-extensions \
        python3-scipy \
    && rm -rf /var/lib/apt/lists/*

COPY docker/fc-core-test-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Isolated domain as belt-and-braces; --network none is the real guarantee.
ENV ROS_DOMAIN_ID=77
ENV PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["/entrypoint.sh"]
