FROM ros:jazzy-ros-core

RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-jazzy-rmw-cyclonedds-cpp \
    python3-requests \
    python3-psycopg2 \
    python3-apscheduler \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
