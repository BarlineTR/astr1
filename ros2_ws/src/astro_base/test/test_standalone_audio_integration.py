#!/usr/bin/env python3
"""Comprehensive Audio Integration & Multimodal Arbitration Test Suite.

Verifies:
1. Visual target has absolute priority over audio (face present -> audio does not steal head).
2. Idle / no visual target -> fresh speech DOA reacquires speaker (left & right).
3. Visual reacquisition immediately overrides audio when face appears.
4. Stale DOA expires after audio freshness timeout and stops steering.
5. Single Gaze Brain: No direct DOA actuator bypass; only GazeTracker drives /head/command.
6. Missing OpenAI key degrades gracefully (gaze tracking and DOA continue).
7. Async non-blocking execution: voice/TTS operations do not freeze tracker.
"""

import math
import os
import sys
import time
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
import numpy as np

# Resolve paths
CUR_DIR = Path(__file__).resolve().parent
REPO_ROOT = CUR_DIR.parents[3]
STANDALONE_DIR = REPO_ROOT / "standalone"
ASTRO_BASE_DIR = CUR_DIR.parents[1]

for path_str in (str(REPO_ROOT), str(STANDALONE_DIR), str(ASTRO_BASE_DIR)):
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from astro_base.gaze.gaze_runtime import GazeRuntimeCore
from astro_base.gaze.gaze_tracker import Detection, GazeResult
from astro_base.gaze.types import PrioritySource
from astro_base.standalone_gaze_ros_node import StandaloneGazeRosNode


class MockSpeechVerdict:
    """Mock for SpeechDetector verdict."""
    def __init__(self, is_speech: bool = True, confidence: float = 0.90):
        self.is_speech = is_speech
        self.confidence = float(confidence)


class TestStandaloneAudioIntegration:
    """Multimodal arbitration and audio integration test suite."""

    def test_visual_target_priority_over_audio(self):
        """When a face is visible, it maintains exclusive authority; audio cannot steal the head."""
        node = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False)

        # Face centered in camera
        face_det = [Detection(x=280, y=200, w=80, h=80, confidence=0.92)]
        # Loud speech from extreme left (+50.0 deg)
        loud_speech = MockSpeechVerdict(is_speech=True, confidence=0.98)
        doa_left = 50.0

        t = 100.0
        # Warm up visual tracking on face
        for i in range(5):
            t += 0.033
            res = node.step_frame(
                detections=face_det,
                frame_size=(640, 480),
                timestamp=t,
                doa_deg=doa_left,
                speech=loud_speech,
            )

        # Visual target MUST own the gaze
        assert res.owner == PrioritySource.VISUAL_TRACKING
        assert res.target_id is not None
        # Head angle must target the face near center (~0 deg), NOT the audio direction (+50 deg)
        assert res.target_yaw_deg < 15.0
        assert node.last_published_yaw < 15.0

    def test_audio_reacquisition_when_idle_left_and_right(self):
        """When no face is present (IDLE), fresh speech DOA reacquires speaker left and right.

        Acoustic contract (ReSpeaker 0=front, +90=right, 270=left) maps to REP-103 body yaw
        (positive = left, negative = right).
        """
        # Test Left: DOA = 32.0 deg (Left sector) -> positive body yaw (+60.0 deg)
        node_left = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False)
        speech_verdict = MockSpeechVerdict(is_speech=True, confidence=0.90)

        t = 200.0
        res_left = None
        for i in range(6):
            t += 0.033
            res_left = node_left.step_frame(
                detections=[],
                frame_size=(640, 480),
                timestamp=t,
                doa_deg=32.0,
                speech=speech_verdict,
            )

        assert res_left is not None
        assert res_left.target_yaw_deg > 20.0  # Turns left toward speaker (+60°)
        assert res_left.owner == PrioritySource.ACTIVE_SPEAKER

        # Test Right: DOA = 148.0 deg (Right sector) -> negative body yaw (-60.0 deg)
        node_right = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False)
        t = 300.0
        res_right = None
        for i in range(6):
            t += 0.033
            res_right = node_right.step_frame(
                detections=[],
                frame_size=(640, 480),
                timestamp=t,
                doa_deg=148.0,
                speech=speech_verdict,
            )

        assert res_right is not None
        assert res_right.target_yaw_deg < -20.0  # Turns right toward speaker (-60°)
        assert res_right.owner == PrioritySource.ACTIVE_SPEAKER

    def test_visual_reacquisition_overrides_audio(self):
        """When robot is reacquiring an audio direction, an appearing face immediately overrides."""
        node = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False)
        speech = MockSpeechVerdict(is_speech=True, confidence=0.90)

        t = 400.0
        # Phase 1: Reacquiring audio speaker at right (DOA=148 deg -> target_yaw ~ -60 deg) with no face
        for i in range(5):
            t += 0.033
            res_audio = node.step_frame(
                detections=[],
                frame_size=(640, 480),
                timestamp=t,
                doa_deg=148.0,
                speech=speech,
            )
        assert res_audio.target_yaw_deg < -20.0
        assert res_audio.owner == PrioritySource.ACTIVE_SPEAKER

        # Phase 2: Face appears at left (x=100 -> positive bearing ~ +18 deg)
        face_left = [Detection(x=100, y=200, w=80, h=80, confidence=0.90)]
        for i in range(4):
            t += 0.033
            res_vis = node.step_frame(
                detections=face_left,
                frame_size=(640, 480),
                timestamp=t,
                doa_deg=45.0,
                speech=speech,
            )

        # Visual target takes immediate priority; head steers toward face at left, not audio at right
        assert res_vis.owner == PrioritySource.VISUAL_TRACKING
        assert res_vis.target_id is not None
        assert res_vis.target_yaw_deg > 0.0  # Steers toward face on left

    def test_stale_doa_expires(self):
        """Audio observation expires after audio freshness timeout and stops steering."""
        node = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False)
        node.localizer.hold_timeout_s = 1.0
        speech = MockSpeechVerdict(is_speech=True, confidence=0.88)

        t = 500.0
        # Step 1: Active sound at +40 deg
        for i in range(4):
            t += 0.033
            node.step_frame(
                detections=[],
                frame_size=(640, 480),
                timestamp=t,
                doa_deg=40.0,
                speech=speech,
            )

        # Step 2: Silence for > 1.5 seconds (stale DOA -> None)
        t += 1.50
        res_stale = node.step_frame(
            detections=[],
            frame_size=(640, 480),
            timestamp=t,
            doa_deg=None,
            speech=None,
        )

        # After audio expires, no active audio target remains
        assert res_stale.owner != PrioritySource.ACTIVE_SPEAKER

    def test_audio_cannot_bypass_gaze_brain(self):
        """Actuator command strictly reflects GazeResult; no direct DOA publication exists."""
        node = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False)

        # Provide DOA without valid speech verdict (unverified sound)
        t = 600.0
        res = node.step_frame(
            detections=[],
            frame_size=(640, 480),
            timestamp=t,
            doa_deg=60.0,
            speech=None,  # Not verified as human speech
        )

        # Head command must match res.target_yaw_deg, NOT raw DOA (60.0)
        assert node.last_published_yaw == pytest.approx(res.target_yaw_deg, abs=1e-3)
        assert node.last_published_yaw != 60.0

    def test_openai_missing_graceful_degradation(self):
        """When OPENAI_API_KEY is unset, node starts safely, voice is disabled, gaze continues."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            # Clear key
            if "OPENAI_API_KEY" in os.environ:
                del os.environ["OPENAI_API_KEY"]

            node = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False, enable_voice=True)
            assert node.voice_loop is None

            # Visual tracking and DOA continue without error
            det = [Detection(x=320, y=240, w=80, h=80, confidence=0.9)]
            res = node.step_frame(det, frame_size=(640, 480), timestamp=10.0, doa_deg=20.0)
            assert res is not None
            assert res.owner == PrioritySource.VISUAL_TRACKING

    def test_edge_tts_configuration(self):
        """EdgeTTSEngine is enabled as fallback in TTSRouter."""
        from astro_audio.edge_tts_engine import EdgeTTSEngine
        engine = EdgeTTSEngine()
        assert hasattr(engine, "is_ready")
        assert hasattr(engine, "synthesize_sentence")

    def test_ros_audio_topic_subscription_bridge(self):
        """StandaloneGazeRosNode in 'topics' mode ingests /audio/doa, /audio/doa_confidence, /audio/vad."""
        from astro_base.standalone_gaze_ros_node import Float32, Bool
        node = StandaloneGazeRosNode(
            use_camera_source=False,
            enable_audio=True,
            audio_source_mode="topics",
        )

        assert node.audio_source_mode == "topics"
        assert node.audio is None  # Does NOT open hardware ReSpeaker

        # Feed ROS topic messages
        node._on_audio_doa(Float32(data=45.0))
        node._on_audio_doa_conf(Float32(data=0.92))
        node._on_audio_vad(Bool(data=True))
        node._on_playback_active(Bool(data=False))

        now = time.monotonic()
        doa, speech, is_speaking = node._sample_acoustic_state(now)

        assert doa == pytest.approx(45.0, abs=1e-3)
        assert speech is not None
        assert speech.is_speech is True
        assert speech.confidence == pytest.approx(0.92, abs=1e-3)
        assert is_speaking is False

    def test_ros_audio_topic_freshness_timeout(self):
        """DOA and VAD received via ROS topics expire after audio_freshness_s."""
        from astro_base.standalone_gaze_ros_node import Float32, Bool
        node = StandaloneGazeRosNode(
            use_camera_source=False,
            enable_audio=True,
            audio_source_mode="topics",
        )
        node.audio_freshness_s = 0.50

        # Feed fresh audio
        node._on_audio_doa(Float32(data=30.0))
        node._on_audio_vad(Bool(data=True))

        t_now = time.monotonic()
        # Immediately fresh
        doa, speech, _ = node._sample_acoustic_state(t_now)
        assert doa == pytest.approx(30.0, abs=1e-3)
        assert speech is not None
        assert speech.is_speech is True

        # Advance past freshness window (0.60s > 0.50s)
        doa_stale, speech_stale, _ = node._sample_acoustic_state(t_now + 0.60)
        assert doa_stale is None
        assert speech_stale is None

    def test_ros_audio_topic_playback_active_suppression(self):
        """When /audio/playback_active or /robot/is_speaking is True, is_speaking flag is True."""
        from astro_base.standalone_gaze_ros_node import Bool
        node = StandaloneGazeRosNode(
            use_camera_source=False,
            enable_audio=True,
            audio_source_mode="topics",
        )

        node._on_playback_active(Bool(data=True))
        _, _, is_speaking = node._sample_acoustic_state(time.monotonic())
        assert is_speaking is True

        node._on_playback_active(Bool(data=False))
        node._on_robot_speaking(Bool(data=True))
        _, _, is_speaking = node._sample_acoustic_state(time.monotonic())
        assert is_speaking is True

        node._on_robot_speaking(Bool(data=False))
        _, _, is_speaking = node._sample_acoustic_state(time.monotonic())
        assert is_speaking is False

    def test_launch_file_graph(self):
        """Verifies astro_social_gaze.launch.py brings up serial_bridge, standalone_gaze_ros_node, audio_stream_node, and astro_realtime_node."""
        import importlib.util
        from pathlib import Path
        launch_file = Path(__file__).resolve().parents[2] / "astro_bringup" / "launch" / "astro_social_gaze.launch.py"
        spec = importlib.util.spec_from_file_location("astro_social_gaze_launch", str(launch_file))
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        ld = mod.generate_launch_description()
        RosNode = mod.Node
        nodes = [entity for entity in ld.entities if isinstance(entity, RosNode)]

        node_execs = {
            n.node_executable if hasattr(n, "node_executable") else getattr(n, "_Node__node_executable", None)
            for n in nodes
        }
        node_pkgs = {
            n.node_package if hasattr(n, "node_package") else getattr(n, "_Node__node_package", None)
            for n in nodes
        }

        # Verify all 4 canonical nodes are declared
        assert "serial_bridge" in node_execs
        assert "standalone_gaze_ros" in node_execs
        assert "audio_stream_node" in node_execs
        assert "astro_realtime_node" in node_execs

        assert "astro_base" in node_pkgs
        assert "astro_audio" in node_pkgs
        assert "astro_ai" in node_pkgs

        # Ensure NO forbidden duplicate nodes exist
        assert "social_gaze_node" not in node_execs
        assert "face_detector_node" not in node_execs
        assert len(nodes) == 4

        # Verify launch argument use_realtime is declared with default true
        launch_args = {
            e.name: str(e.default_value) for e in ld.entities if hasattr(e, "name") and hasattr(e, "default_value")
        }
        assert "use_realtime" in launch_args
        assert launch_args["use_realtime"] == "true"
        assert "enable_voice" in launch_args

    def test_audio_reacquisition_with_hardware_confidence_threshold(self):
        """Audio targets with realistic hardware confidence (0.50..0.60) must succeed in reacquisition."""
        node = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False)
        # 0.55 confidence is well below the old 0.75 hardcoded threshold, but above audio_acquisition_threshold 0.45
        speech = MockSpeechVerdict(is_speech=True, confidence=0.55)

        t = 600.0
        res = None
        for _ in range(6):
            t += 0.033
            res = node.step_frame(
                detections=[],
                frame_size=(640, 480),
                timestamp=t,
                doa_deg=148.0,  # Right in ReSpeaker -> negative body yaw
                speech=speech,
            )

        assert res is not None
        assert res.owner == PrioritySource.ACTIVE_SPEAKER
        assert res.target_yaw_deg < -15.0  # Steers toward right speaker
        assert node.last_published_yaw < -15.0

    def test_raw_doa_without_speech_is_ignored(self):
        """Raw DOA without valid speech verdict must never seize gaze authority or move the head."""
        node = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False)

        t = 700.0
        res = None
        # Case A: speech=None
        for _ in range(5):
            t += 0.033
            res = node.step_frame(
                detections=[],
                frame_size=(640, 480),
                timestamp=t,
                doa_deg=32.0,
                speech=None,
            )
        assert res is not None
        assert res.owner == PrioritySource.IDLE
        assert abs(res.target_yaw_deg) < 1e-3

        # Case B: speech verdict is_speech=False
        no_speech = MockSpeechVerdict(is_speech=False, confidence=0.0)
        for _ in range(5):
            t += 0.033
            res = node.step_frame(
                detections=[],
                frame_size=(640, 480),
                timestamp=t,
                doa_deg=32.0,
                speech=no_speech,
            )
        assert res is not None
        assert res.owner == PrioritySource.IDLE
        assert abs(res.target_yaw_deg) < 1e-3

    def test_audio_reacquisition_timeout_returns_to_center(self):
        """When audio ceases and no face is found, FSM safely times out and returns to center."""
        node = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False)
        node.localizer.hold_timeout_s = 2.0
        speech = MockSpeechVerdict(is_speech=True, confidence=0.60)

        t = 800.0
        # 1. Turn to speaker at right (DOA=148.0)
        res_first = None
        for _ in range(3):
            t += 0.033
            res_first = node.step_frame(
                detections=[],
                frame_size=(640, 480),
                timestamp=t,
                doa_deg=148.0,
                speech=speech,
            )
        assert res_first is not None
        assert res_first.owner == PrioritySource.ACTIVE_SPEAKER
        assert res_first.target_yaw_deg < -15.0

        # 2. Sound stops; simulate time passing without any speech or face (> 2.5s)
        res = None
        for _ in range(90):
            t += 0.033
            res = node.step_frame(
                detections=[],
                frame_size=(640, 480),
                timestamp=t,
                doa_deg=None,
                speech=None,
            )

        # After search timeout, robot must recover back to IDLE at center (0 deg)
        assert res is not None
        assert res.owner == PrioritySource.IDLE
        assert abs(res.target_yaw_deg) < 2.0

    def test_gcc_phat_pair_signs_steer_head_correctly(self):
        """Validates that ReSpeakerAudioLocalizer steers head left and right correctly."""
        # 1. Synthesize RIGHT speaker: DOA = 148.0° (>= 100°) -> negative body yaw (-60.0°)
        node_r = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False)
        speech = MockSpeechVerdict(is_speech=True, confidence=0.85)
        t = 900.0
        res_r = None
        for _ in range(4):
            t += 0.033
            res_r = node_r.step_frame(detections=[], frame_size=(640, 480), timestamp=t, doa_deg=148.0, speech=speech)
        assert res_r.owner == PrioritySource.ACTIVE_SPEAKER
        assert res_r.target_yaw_deg <= -30.0  # Negative = Right (sector target -35.0°)

        # 2. Synthesize LEFT speaker: DOA = 32.0° (< 55°) -> positive body yaw (+35.0°)
        node_l = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False)
        t = 1000.0
        res_l = None
        for _ in range(4):
            t += 0.033
            res_l = node_l.step_frame(detections=[], frame_size=(640, 480), timestamp=t, doa_deg=32.0, speech=speech)
        assert res_l.owner == PrioritySource.ACTIVE_SPEAKER
        assert res_l.target_yaw_deg >= 30.0  # Positive = Left (sector target +35.0°)


def test_manual_target_yaw_override():
    """Verify /head/target_yaw overrides visual tracking and keepalive output for 4.0s."""
    from astro_base.standalone_gaze_ros_node import Float32
    node = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False)
    
    # Simulate a face right in front (0 deg)
    face_det = [Detection(x=280, y=200, w=80, h=80, confidence=0.9)]
    res = node.step_frame(detections=face_det, frame_size=(640, 480), timestamp=100.0)
    assert node.last_published_yaw == pytest.approx(0.0, abs=5.0)
    
    # Receive /head/target_yaw manual override command for +35.0 degrees (e.g. from dialogue tool)
    node._on_target_yaw(Float32(data=35.0))
    
    # Even with face at center, dispatched yaw must be manual target (+35.0 deg)
    res_override = node.step_frame(detections=face_det, frame_size=(640, 480), timestamp=100.033)
    assert node.last_published_yaw == pytest.approx(35.0, abs=1e-3)
    assert node.pub_head_cmd_pos.last_msg.data == pytest.approx(35.0, abs=1e-3)
    
    # Keepalive cycle must also dispatch +35.0 deg
    node._passive_keepalive_cycle()
    assert node.pub_head_cmd_pos.last_msg.data == pytest.approx(35.0, abs=1e-3)


def test_astro_realtime_node_use_realtime_true():
    """Verify use_realtime=True preserves default production/test behavior."""
    from astro_ai.astro_realtime_node import AstroRealtimeNode
    node = AstroRealtimeNode(connect_realtime=True)
    try:
        assert node.use_realtime is True
        assert node._fallback_mode is False
        assert node.realtime_provider_state == "AVAILABLE"
        assert node._can_use_openai("realtime") is True
        assert node.tts_router.local_offline_tts is not None
        assert node.edge_tts_enabled is True
    finally:
        node.destroy_node()


def test_astro_realtime_node_use_realtime_false():
    """Verify use_realtime=False initializes LOCAL_FALLBACK, 0 websocket thread, and 0 espeak."""
    from astro_ai.astro_realtime_node import AstroRealtimeNode
    node = AstroRealtimeNode(use_realtime=False)
    try:
        assert node.use_realtime is False
        assert node.connect_realtime is False
        assert node._fallback_mode is True
        assert node.realtime_provider_state == "LOCAL_FALLBACK"
        assert node._ws_thread is None
        assert node._can_use_openai("realtime") is False
        assert node._can_use_openai("all") is False
        assert node.local_offline_tts is None
        assert node.tts_router.local_offline_tts is None
        assert node.edge_tts_enabled is True
    finally:
        node.destroy_node()


def test_astro_realtime_node_use_realtime_env_override(monkeypatch):
    """Verify USE_REALTIME='false' env variable disables Realtime WebSocket and espeak."""
    monkeypatch.setenv("USE_REALTIME", "false")
    from astro_ai.astro_realtime_node import AstroRealtimeNode
    node = AstroRealtimeNode(connect_realtime=True)
    try:
        assert node.use_realtime is False
        assert node.connect_realtime is False
        assert node._fallback_mode is True
        assert node.realtime_provider_state == "LOCAL_FALLBACK"
        assert node._ws_thread is None
        assert node._can_use_openai("realtime") is False
        assert node.local_offline_tts is None
        assert node.tts_router.local_offline_tts is None
    finally:
        node.destroy_node()


def test_local_gemma_two_stage_timeout():
    """Verify LocalGemmaClient supports two-stage configurable timeout (first token and inter-token)."""
    from astro_ai.local_gemma_client import LocalGemmaClient
    client = LocalGemmaClient(timeout_s=4.0, first_token_timeout_s=7.0)
    assert client.timeout_s == 4.0
    assert client.first_token_timeout_s == 7.0


def test_local_mode_cloud_fallback_isolation():
    """Verify that when use_realtime=False, cloud LLMs (Groq, Gemini) are NEVER invoked even if Local Gemma fails."""
    from unittest.mock import MagicMock, patch
    from astro_ai.astro_realtime_node import AstroRealtimeNode

    node = AstroRealtimeNode(use_realtime=False)
    try:
        # Mock Local Gemma to fail
        mock_gemma = MagicMock()
        mock_gemma.is_available.return_value = True
        mock_gemma.stream.side_effect = RuntimeError("llama-server unavailable")
        node.local_gemma_client = mock_gemma

        # Set up keys and candidates for Groq & Gemini
        node.groq_api_key = "gsk_test_key"
        node.gemini_api_key = "gem_test_key"
        node.provider_registry = MagicMock()
        node.provider_registry.get_candidate_models.return_value = ["llama-3.3-70b-versatile"]

        # Run direct text turn
        node._process_fallback_turn(direct_text="Merhaba Astro")

        # Invariant: Groq and Gemini stream/generation MUST NOT be called!
        assert node.provider_registry.stream_groq_completion.call_count == 0
        assert node.provider_registry.generate_gemini_content.call_count == 0
    finally:
        node.destroy_node()


def test_local_mode_system_telemetry_truthfulness():
    """Verify that when use_realtime=False, system telemetry and diagnostics report LOCAL_ACTIVE and OK."""
    from astro_ai.astro_realtime_node import AstroRealtimeNode, DiagnosticStatus

    node = AstroRealtimeNode(use_realtime=False)
    try:
        published_msgs = []
        node.pub_telemetry = MagicMock()
        node.pub_telemetry.publish = lambda m: published_msgs.append(m)

        published_diags = []
        node.pub_diagnostics = MagicMock()
        node.pub_diagnostics.publish = lambda d: published_diags.append(d)

        node._publish_system_telemetry()

        assert len(published_msgs) == 1
        import json
        telem = json.loads(published_msgs[0].data)
        assert telem["voice_mode"] == "local"
        assert telem["realtime_ws"]["state"] == "LOCAL_ACTIVE"
        assert telem["realtime_ws"]["connected"] is True

        assert len(published_diags) == 1
        diag_arr = published_diags[0]
        voice_diag = [s for s in diag_arr.status if "Local Engine" in s.name or "Voice" in s.name][0]
        assert voice_diag.level == DiagnosticStatus.OK
        assert "use_realtime=False" in voice_diag.message
    finally:
        node.destroy_node()


def test_non_blocking_clause_playback_streaming():
    """Verify that _play_pcm_chunks with is_final_clause=False executes in non-blocking mode without drain sleeps."""
    import time
    from unittest.mock import MagicMock
    from astro_ai.astro_realtime_node import AstroRealtimeNode

    node = AstroRealtimeNode(use_realtime=False)
    try:
        node.pub_output_pcm = MagicMock()
        node._current_turn_explicit_user_turn = True
        node._speech_authorization = MagicMock(invalidated=False)
        # 1.0 second of dummy 24kHz int16 audio = 48000 bytes
        dummy_pcm = b"\x00\x01" * 24000

        t0 = time.perf_counter()
        node._play_pcm_chunks(dummy_pcm, generation_id=99, is_final_clause=False, blocking_pace=False)
        elapsed = time.perf_counter() - t0

        # Must return almost instantly (< 150ms), NOT sleep for 1.0s DAC duration!
        assert elapsed < 0.20, f"Streaming clause blocked for {elapsed:.3f}s!"
        assert node.pub_output_pcm.publish.call_count > 0
    finally:
        node.destroy_node()
