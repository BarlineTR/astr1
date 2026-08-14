import os
from glob import glob
from setuptools import setup

package_name = 'astro_control'

setup(
    name=package_name,
    version='1.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Baran Eren',
    maintainer_email='baran@example.com',
    description='ASTRO V1 control, face tracking and collision avoidance',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'navigation_node = astro_control.navigation_node:main',
        ],
    },
)
