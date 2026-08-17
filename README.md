# ASTRO V1

ASTRO V1 is a modular ROS 2 based robotics project containing drivers and launch files for base movement, LiDAR (RPLIDAR), Vision (OAK-D Lite), and Audio (ReSpeaker 4-Mic Array) systems.

## 🚀 ROS 2 Architecture

The system has been completely modularized into ROS 2 Humble packages:

### 📦 Packages
- `astro_base`: Arduino Mega serial bridge for motor control and base sensors.
- `astro_lidar`: RPLIDAR A1 wrapper and NaN/Range filter node (`scan_filter_node`).
- `astro_vision`: OAK-D Lite driver wrapper and OpenCV Face Detection node.
- `astro_audio`: ReSpeaker array driver handling Audio Capture, Speech Recognition (Vosk/Faster-Whisper), and TTS (ElevenLabs/edge-tts/XTTS/pyttsx3/gTTS).
- `astro_ai`: AI Brain Node managing LLM interactions and memory via OpenAI API standard.
- `astro_bringup`: Centralized launch files and parameters for the whole system.
- `astro_description`: URDF models and Robot State Publisher (tf2).

## 🛠️ Installation & Build

**Prerequisites:** Ubuntu 22.04 with ROS 2 Humble and Python 3.10 (Jetson Orin Nano or an x86 dev machine). Everything else the installer handles.

### Quick install (one command)

```bash
git clone <this-repo> astr1 && cd astr1
./scripts/install.sh                 # apt packages + venv + build + verification
./scripts/install.sh --with-xtts     # also install local XTTS voice cloning (~5 GB)
```

The script is re-runnable — it completes what is missing and never overwrites an existing `.env`. Flags:

| Flag | Effect |
|---|---|
| `--with-xtts` | Also run `scripts/install_xtts.sh` (local XTTS voice cloning) |
| `--skip-apt` | Skip the apt step (no sudo, or packages already present) |
| `--skip-build` | Skip `colcon build` |
| `--clean` | Delete `build/ install/ log/` and rebuild from scratch |

It ends with a verification pass — 7 ROS packages present, every node importable, `serial_bridge.py` executable, entry points pointing at the venv — and exits non-zero if any check fails. Missing apt packages are reported as warnings with the exact `sudo apt install` line, since apt needs a terminal for the password.

Then:

```bash
source .venv/bin/activate
source ros2_ws/install/setup.bash
ros2 launch astro_bringup robot.launch.py
```

| Script | Purpose |
|---|---|
| `scripts/install.sh` | Full install: apt packages, uv, venv, `.env`, workspace build, verification |
| `scripts/build.sh` | Rebuild the workspace correctly (right directory, right interpreter) |
| `scripts/install_xtts.sh` | XTTS voice cloning only — clones the TTS fork from GitHub into its own venv |
| `scripts/install_stt_deps.sh` | Legacy: `pip3 install`s the STT/TTS packages system-wide. Superseded by `requirements.txt` + the venv; kept only for machines set up before the venv layout |

The sections below document what the installer does, in case you want to run the steps by hand or debug one of them.

### 1. System packages (apt)

These cannot come from pip — ROS packages, and the native libraries that `sounddevice` / `pyttsx3` bind to:

```bash
sudo apt update
sudo apt install -y python3-rosdep python3-colcon-common-extensions
sudo apt install -y ros-humble-rplidar-ros ros-humble-depthai-ros ros-humble-robot-state-publisher
sudo apt install -y libportaudio2 espeak-ng mpg123 alsa-utils
```

| Package | Needed by |
|---|---|
| `libportaudio2` | `sounddevice` — without it `audio_capture_node` fails with `OSError: PortAudio library not found` |
| `espeak-ng` | `pyttsx3` offline TTS engine, and XTTS phonemisation |
| `mpg123` | MP3 playback in `tts_node` — the `edge-tts`, `gTTS` and ElevenLabs engines all shell out to it, so without it TTS generates audio but plays nothing |
| `alsa-utils` | WAV playback in `tts_node` — XTTS produces WAV, which `mpg123` cannot play |

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

```bash
./scripts/build.sh                 # everything
./scripts/build.sh astro_audio     # one package
./scripts/build.sh --clean         # wipe build/ install/ log/ first
```

**Do not run bare `colcon build`.** Two things about this workspace make the plain command produce a broken system, and the wrapper handles both:

1. **Build from `ros2_ws/`, never from the repository root.** A root build creates a *second* `install/` tree next to the source, and `ros2 launch` then runs whichever one your shell happens to have sourced — usually the stale one. The repo root carries a `COLCON_IGNORE` file so an accidental root build finds 0 packages instead of silently shadowing the real tree.
2. **Build with the venv's Python** (`../.venv/bin/python -m colcon build --symlink-install`). setuptools writes the shebang of every generated entry point (`install/astro_audio/lib/astro_audio/tts_node`, …) from the interpreter that runs the build. `/usr/bin/colcon` runs under the system Python, so the entry points get `#!/usr/bin/python3` — and then `ros2 run` cannot see a single venv package. The symptom is a launch full of lines like:

   ```text
   [tts_node] edge-tts paketi kurulu değil, pyttsx3'e düşürülüyor
   [speech_recognition_node] faster-whisper kütüphanesi kurulu değil! Vosk'a dönülüyor
   [audio_capture_node] sounddevice başlatılamadı. arecord fallback moduna geçiliyor...
   ```

   Those messages are lying: the packages are installed, just not visible to `/usr/bin/python3`. Building through the venv points the entry points at `.venv/bin/python`, and `ros2 run` / `ros2 launch` then work whether or not the venv is activated. (`colcon` stays importable inside the venv because it was created with `--system-site-packages`.)

To check which tree a running node came from, look at the path in the launch output: it must start with `<repo-root>/ros2_ws/install/`, not `<repo-root>/install/`. If your shell still has a deleted tree sourced, open a new shell and `source ros2_ws/install/setup.bash`.

Expected result: 7 packages finished. Warnings about `tests_require` and CMake policy `CMP0148` are harmless.

**Verify the build:**

```bash
ros2 pkg list | grep astro                 # 7 packages
ros2 pkg executables | grep astro          # 7 executables
```

Or just re-run `./scripts/install.sh --skip-apt`, which performs the same checks and prints a pass/fail line per node.

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

> ⚠️ **Do not use `distil-*` models for Turkish.** Every Distil-Whisper checkpoint (`distil-large-v3`, `distil-medium.en`, …) is an English-only distillation — it ignores `language="tr"` and returns English text. Use the multilingual `large-v3` (or `medium` / `small` on weaker GPUs).
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

### 5. Advanced TTS (Ses Sentezi) Options

`TTS_ENGINE` in `.env` selects the engine: `elevenlabs`, `edge-tts` (default), `xtts`, `pyttsx3`, `gtts`. The first two and `gtts` need internet; `xtts` and `pyttsx3` are fully offline.

**XTTS v2 — local voice cloning (offline, GPU recommended)**

`xtts` speaks with a cloned voice taken from a short reference recording, with no internet and no API key. It is **not** installed from PyPI: `pip install TTS` resolves Coqui TTS 0.22.0 against today's package versions and produces an environment that imports but does not work. Instead a dedicated script clones the maintained fork and pins the version set that is known to work:

```bash
./scripts/install_xtts.sh
```

The script clones <https://github.com/yunusemretom/TTS.git> into `~/.astro/tts` (override with `TTS_XTTS_HOME`), creates a Python 3.10 venv there, installs the repo with `uv pip install -e .`, picks the torch CUDA build matching your driver, pins `librosa`/`transformers`/`numpy`/`scipy`, symlinks `espeak` → `espeak-ng`, and pre-downloads the ~1.8 GB XTTS v2 checkpoint (skip with `XTTS_SKIP_DOWNLOAD=1`). It is re-runnable: an existing clone is updated instead of re-cloned.

> **Why a second virtualenv?** XTTS needs `numpy==1.26.4` — its compiled `monotonic_align` Cython extension is built against the NumPy 1.x ABI — while this repo pins `numpy==2.2.6` to match `rclpy`. The two cannot share an interpreter. So `tts_node` never imports XTTS: it launches `xtts_worker.py` with the XTTS venv's Python as a long-lived child process and talks to it over line-based JSON on stdin/stdout (`xtts_client.py`). The model and speaker latents are loaded once at node start, so each sentence pays only inference cost.

Enable it in `.env`:

```ini
TTS_ENGINE="xtts"
TTS_XTTS_HOME="$HOME/.astro/tts"
TTS_XTTS_SPEAKER_WAV=""      # empty → packaged voices/astro.wav
TTS_XTTS_DEVICE="auto"       # "auto" | "cuda" | "cpu"
TTS_XTTS_HALF=1              # fp16, CUDA only
TTS_XTTS_BATCH_SIZE=4        # batch sentence decoding on long text
```

**Changing the robot's voice.** The reference clip ships with the package at `ros2_ws/src/astro_audio/voices/astro.wav` (~9 s). Replace that file, or point `TTS_XTTS_SPEAKER_WAV` at an absolute path. Use 6–30 s of clean, single-speaker audio.

**Behaviour and expectations.**
- Startup takes ~10–30 s (model load + warm-up) and much longer on the first run if the checkpoint still has to download. The node does not block: sentences arriving before XTTS is ready are spoken by `edge-tts` instead, and `✅ [TTS] XTTS hazır` is logged when the worker is warm.
- If the install is missing, the worker fails to start, or it dies mid-run, `tts_node` logs the reason and falls back to `edge-tts` (or `pyttsx3` when there is no internet package) — the robot never goes silent.
- XTTS emits WAV, so playback uses `paplay`/`aplay`/`ffplay`, not `mpg123`. Install `alsa-utils` if none is present.
- On CPU XTTS is very slow (RTF > 1, i.e. slower than real time). On an RTX 4050 Laptop with fp16 + batch=4 a paragraph runs at RTF ≈ 0.09 using ~1.5 GB VRAM.

> **Note:** For AI API keys (`AI_API_KEY`), use the `.env` file at the root of the project (copy from `.env.example`). Do not hardcode API keys in the source code!
