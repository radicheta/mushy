from setuptools import setup
import os
from glob import glob

package_name = 'fc_core'

setup(
    name=package_name,
    version='0.0.1',
    packages=[package_name, package_name + '.sim', package_name + '.vendor', package_name + '.vendor.simple_pid'],
    package_data={'fc_core.sim': ['data/*.csv']},
    include_package_data=True,
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=[
        'setuptools',
        'websockets',
        'rclpy',
        'sensor_msgs',
        'std_msgs',
        'rpi_hardware_pwm',
        'RPi.GPIO',
        'adafruit-circuitpython-dht',
        'pyyaml',
    ],
    zip_safe=True,
    maintainer='Santi',
    maintainer_email='santi@example.com',
    description='Fruiting Chamber Control Package',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'fc_controller = fc_core.fc_controller:main',
            'fc_pwm_driver = fc_core.fc_pwm_driver:main',
            'fc_sensors = fc_core.fc_sensors:main',
            'fc_display = fc_core.fc_display:main',
            'fc_telemetry = fc_core.fc_telemetry:main',
            'fc_camera = fc_core.fc_camera:main',
            'fc_buffer = fc_core.fc_buffer:main',
        ],
    },
)
