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
            parameters=[LaunchConfiguration('config_file')],
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

        # Launch camera node
        Node(
            package='fc_core',
            executable='fc_camera',
            name='fc_camera',
            parameters=[LaunchConfiguration('config_file')],
            output='screen'
        ),
    ])