# ASTRO V1

ASTRO V1 is a modular ROS 2 based robotics project containing drivers and launch files for base movement, LiDAR (RPLIDAR), Vision (OAK-D Lite), and Audio (ReSpeaker 4-Mic Array) systems.

## 🚀 ROS 2 Architecture

The system has been completely modularized into ROS 2 Humble packages:

### 📦 Packages
- `astro_base`: Arduino Mega serial bridge for motor control and base sensors.
- `astro_lidar`: RPLIDAR A1 wrapper and NaN/Range filter node (`scan_filter_node`).
- `astro_vision`: OAK-D Lite driver wrapper and OpenCV Face Detection node.
- `astro_audio`: ReSpeaker array driver handling Audio Capture, Speech Recognition (Vosk), and TTS (pyttsx3/gTTS).
- `astro_ai`: AI Brain Node managing LLM interactions and memory via OpenAI API standard.
- `astro_bringup`: Centralized launch files and parameters for the whole system.
- `astro_description`: URDF models and Robot State Publisher (tf2).

## 🛠️ Installation & Build

**Prerequisites:** Ubuntu 22.04 with ROS 2 Humble and Python 3.10 (Jetson Orin Nano or an x86 dev machine).

### 1. System packages (apt)

These cannot come from pip — ROS packages, and the native libraries that `sounddevice` / `pyttsx3` bind to:

```bash
sudo apt update
sudo apt install -y python3-rosdep python3-colcon-common-extensions
sudo apt install -y ros-humble-rplidar-ros ros-humble-depthai-ros ros-humble-robot-state-publisher
sudo apt install -y libportaudio2 espeak-ng ffmpeg
```

| Package | Needed by |
|---|---|
| `libportaudio2` | `sounddevice` — without it `audio_capture_node` fails with `OSError: PortAudio library not found` |
| `espeak-ng` | `pyttsx3` offline TTS engine |
| `ffmpeg` | playback of `edge-tts` / `gTTS` / ElevenLabs audio |

### 2. Python environment (uv)

Python dependencies live in a project-local virtualenv so they never mix with system or `~/.local` packages. We use [uv](https://docs.astral.sh/uv/); install it once with `curl -LsSf https://astral.sh/uv/install.sh | sh`.

```bash
cd <repo-root>
uv venv --python 3.10 --system-site-packages .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

> **`--system-site-packages` is mandatory.** `rclpy`, `sensor_msgs`, `std_msgs`, `diagnostic_msgs`, `launch`, `launch_ros` and `ament_index_python` are not on PyPI — they come from `/opt/ros/humble`. A fully isolated venv cannot import any node in this repo.

**Dependency files.** `requirements.in` is the hand-edited list of direct dependencies; `requirements.txt` is the fully pinned lock file generated from it (73 packages including transitive ones). Never edit the lock by hand:

```bash
# after adding or removing a package in requirements.in
uv pip compile requirements.in -o requirements.txt   # resolve + pin
uv pip install -r requirements.txt                   # apply to the venv
```

Two pins are deliberate and must not be relaxed:

- `numpy==2.2.6` — matches the system/ROS NumPy so the venv copy cannot break `rclpy`'s ABI.
- `opencv-python<5` — OpenCV 5 removed the Haar cascade API, and `face_detector_node` uses `cv2.CascadeClassifier`. If a 5.x wheel is installed system-wide (`~/.local`), the venv shadows it; outside the venv the node raises `AttributeError: module 'cv2' has no attribute 'CascadeClassifier'`.

### 3. Build the workspace

Run `colcon` **from `ros2_ws/`**, not from the repository root — building at the root scatters `build/ install/ log/` next to the source tree.

```bash
cd <repo-root>/ros2_ws
colcon build --symlink-install
source install/setup.bash   # or setup.zsh
```

Expected result: 7 packages finished. Warnings about `tests_require` and CMake policy `CMP0148` are harmless.

## 🚦 Usage

With the new ROS 2 structure, you no longer need to run separate scripts. The entire system is managed via `astro_bringup`.

### Launching the Entire Robot (All Sensors + Base)
```bash
ros2 launch astro_bringup robot.launch.py
```
*(This will launch the base, lidar, camera, and audio nodes all at once.)*

### Launching Individual Subsystems
If you want to test or launch sensors individually for debugging:

**Vision (OAK-D + Face Detection):**
```bash
ros2 launch astro_vision camera.launch.py
```

**LiDAR (RPLIDAR + Filter):**
```bash
ros2 launch astro_lidar lidar.launch.py
```

**Audio (Mic Capture + STT + TTS):**
```bash
ros2 launch astro_audio audio.launch.py
```

## ⚙️ Configuration

Centralized parameters are stored in `astro_bringup/config/astro_params.yaml`. You can modify:
- Serial ports (e.g., `/dev/astro_lidar`, `/dev/astro_arduino`)
- Camera resolution and FPS
- VAD thresholds and Audio settings
- RPLIDAR ranges and baud rates

### 4. Advanced STT (Ses Tanıma) Options
You can change the STT engine via the `.env` file (`STT_ENGINE`).

**Option 1: Vosk Large Model (Offline, 1GB)**
For much better offline Turkish recognition, download the large model:
```bash
wget https://alphacephei.com/vosk/models/vosk-model-tr-0.3.zip
unzip vosk-model-tr-0.3.zip
sudo mv vosk-model-tr-0.3 /opt/vosk/
```
Then update your `.env` file:
```ini
STT_ENGINE="vosk"
STT_VOSK_MODEL_PATH="/opt/vosk/vosk-model-tr-0.3"
```
Any model directory kept at the repository root (e.g. `vosk-model-small-tr-0.3/`) is git-ignored — point `STT_VOSK_MODEL_PATH` at it with an absolute path instead of committing 57 MB+ of model files.

**Option 2: Faster-Whisper (Recommended — full sentences, offline)**
The `faster-whisper` package is already part of `requirements.txt`, so no extra install step is needed inside the venv. Just set it in `.env`:
```ini
STT_ENGINE="faster-whisper"
STT_FW_MODEL="distil-large-v3"
STT_FW_DEVICE="cuda"          # use "cpu" if no NVIDIA GPU
STT_FW_COMPUTE_TYPE="float16" # use "int8" on CPU
```
On first launch the model downloads (~800MB for distil-large-v3). Expect log:
`✅ Faster-Whisper modeli başarıyla yüklendi.`

**Option 3: Whisper API (Cloud)**
If you want to use OpenAI or Groq Whisper for perfect STT:
```ini
STT_ENGINE="whisper"
STT_API_KEY="sk-YOUR-KEY"
```

> **Note:** For AI API keys (`AI_API_KEY`), use the `.env` file at the root of the project (copy from `.env.example`). Do not hardcode API keys in the source code!
