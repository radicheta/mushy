from setuptools import setup
import os
from glob import glob

package_name = 'mission_control_bridge'

setup(
    name=package_name,
    version='0.0.1',
    packages=['mission_control_bridge'],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='santi',
    maintainer_email='santi@example.com',
    description='Mission Control Bridge Package',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'fake_sensors = mission_control_bridge.fake_sensors:main',
        ],
    },
    package_dir={'': '.'},
) 