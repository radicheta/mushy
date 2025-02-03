from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch.substitutions import PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare
from launch_ros.actions import Node

def generate_launch_description():
    pkg_ic_simulation = FindPackageShare('ic_simulation')
    
    # Launch Ignition with our world
    ign_sim = ExecuteProcess(
        cmd=['/usr/local/bin/gz-sim', '-r',
             PathJoinSubstitution([pkg_ic_simulation, 'worlds', 'incubator.sdf'])],
        output='screen'
    )

    # Bridge between ROS 2 and Ignition for temperature data
    bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        name='temperature_bridge',
        parameters=[{
            'config_file': PathJoinSubstitution([pkg_ic_simulation, 'config', 'temperature_bridge.yaml'])
        }],
        output='screen'
    )

    return LaunchDescription([
        ign_sim,
        bridge,
    ])