from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    # Get the package share directory
    pkg_share = get_package_share_directory('fc_core')
    
    # Declare the config file path
    config_file = os.path.join(pkg_share, 'config', 'fc_config.yaml')

    # Phase 28 D-17 Layer 2: runtime overlay (optional). Bridge POST /control/persist
    # writes here; rclpy launch's parameters=[base, overlay] is last-wins for duplicates.
    # Pitfall (RESEARCH §Pattern 3): missing file MUST NOT fail launch.
    overlay_path = os.environ.get('FC_RUNTIME_OVERLAY', '/var/lib/fc-core/runtime_overrides.yaml')
    fc_controller_params = [LaunchConfiguration('config_file')]
    if os.path.exists(overlay_path):
        fc_controller_params.append(overlay_path)

    return LaunchDescription([
        # Declare launch arguments
        DeclareLaunchArgument(
            'config_file',
            default_value=config_file,
            description='Path to config file'
        ),
        
        # Launch sensor node
        Node(
            package='fc_core',
            executable='fc_sensors',
            name='fc_sensors',
            parameters=[LaunchConfiguration('config_file')],
            output='screen'
        ),
        
        # Launch controller node
        Node(
            package='fc_core',
            executable='fc_controller',
            name='fc_controller',
            parameters=fc_controller_params,
            output='screen'
        ),
        
        # Launch display node
        Node(
            package='fc_core',
            executable='fc_display',
            name='fc_display',
            parameters=[LaunchConfiguration('config_file')],
            output='screen'
        ),

        # Launch slow-PWM actuator driver (Phase 27 — D-03)
        Node(
            package='fc_core',
            executable='fc_pwm_driver',
            name='fc_pwm_driver',
            parameters=[LaunchConfiguration('config_file')],
            output='screen',
        ),

        # Launch local telemetry buffer (Phase 999.1 — D-05/D-06/D-07/D-09/D-10/D-11)
        Node(
            package='fc_core',
            executable='fc_buffer',
            name='fc_buffer',
            parameters=[LaunchConfiguration('config_file')],
            output='screen',
        ),

        # Launch camera node
        Node(
            package='fc_core',
            executable='fc_camera',
            name='fc_camera',
            parameters=[LaunchConfiguration('config_file')],
            output='screen'
        ),
    ])