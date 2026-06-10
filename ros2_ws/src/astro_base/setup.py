from setuptools import setup

package_name = 'astro_base'

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
    description='ASTRO V1 base hardware interface',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'serial_bridge = astro_base.serial_bridge:main',
        ],
    },
)
