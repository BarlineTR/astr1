import os
from glob import glob

from setuptools import setup

package_name = "astro_audio"

setup(
    name=package_name,
    version="1.0.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Baran Eren",
    maintainer_email="baran@example.com",
    description="ASTRO V1 ReSpeaker audio capture, STT and TTS",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "audio_capture_node = astro_audio.audio_capture_node:main",
            "speech_recognition_node = astro_audio.speech_recognition_node:main",
            "tts_node = astro_audio.tts_node:main",
        ],
    },
)
