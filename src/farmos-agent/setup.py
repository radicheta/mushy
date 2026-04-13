from setuptools import setup

package_name = 'farmos_agent'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Santiago Svirsky',
    maintainer_email='santi@example.com',
    description='FarmOS daily report agent — ROS2 lifecycle node',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'farmos_agent = farmos_agent.farmos_agent_node:main',
        ],
    },
)
