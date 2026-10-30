"""Launch fc2_controller with the base config and, if usable, the runtime overlay."""
import os

from ament_index_python.packages import get_package_share_directory
from fc2_core.params import DEFAULT_OVERLAY_PATH, usable_overlay
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    """Build the FC-2 launch description."""
    config_file = os.path.join(
        get_package_share_directory('fc2_core'), 'config', 'fc2_config.yaml')

    # Runtime overlay written by the node on accepted param changes; last-wins
    # over the base config. A missing or unreadable overlay must not fail launch.
    overlay_path = os.environ.get('FC2_RUNTIME_OVERLAY', DEFAULT_OVERLAY_PATH)
    params = [LaunchConfiguration('config_file')]
    if usable_overlay(overlay_path):
        params.append(overlay_path)

    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=config_file,
                              description='Path to config file'),
        # A dead node ends the launch, so systemd sees it and restarts.
        Node(
            package='fc2_core',
            executable='fc2_controller',
            name='fc2_controller',
            parameters=params,
            output='screen',
            on_exit=Shutdown(),
        ),
    ])
