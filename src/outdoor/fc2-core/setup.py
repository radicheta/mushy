from setuptools import setup

package_name = 'fc2_core'

setup(
    name=package_name,
    version='0.0.1',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=[
        'setuptools',
        'rclpy',
        'std_msgs',
        'pyyaml',
        'RPi.GPIO',
    ],
    zip_safe=True,
    maintainer='Santi',
    maintainer_email='santi@example.com',
    description='FC-2 log-yard sprinkler control',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'fc2_controller = fc2_core.fc2_node:main',
            'fc2_valve_off = fc2_core.valve:valve_off_main',
        ],
    },
)
