"""Offline chamber simulation for control development.

Hard rule: everything under this package must import in a vanilla Python venv.
No rclpy, no RPi.GPIO, no ROS message types. The point is to iterate on control
logic without a live chamber, so a ROS dependency here defeats the purpose.
"""
