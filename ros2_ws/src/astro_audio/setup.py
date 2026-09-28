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
        # XTTS ses klonlaması için referans ses(ler)i
        (os.path.join("share", package_name, "voices"), glob("voices/*.wav")),
    ],
    install_requires=["setuptools", "edge-tts", "groq", "sounddevice", "scipy"],
    zip_safe=True,
    maintainer="Baran Eren",
    maintainer_email="baran@example.com",
    description="ASTRO V1 ReSpeaker audio capture, STT and TTS",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "audio_capture_node = astro_audio.audio_capture_node:main",
            "audio_stream_node = astro_audio.audio_stream_node:main",
            "speech_recognition_node = astro_audio.speech_recognition_node:main",
            "tts_node = astro_audio.tts_node:main",
        ],

    },
)
