"""Unit tests for Person-Centric Multi-Modal Identity and Active Speaker Fusion.

Tests the full test matrix:
1. Scenario A: Baran alone at 0°, speaks with Baran's voice -> Speaker is Baran.
2. Scenario B: Baran at 0°, Guest speaks from 45° (unknown voice) -> Speaker is Misafir (NEVER Baran).
3. Scenario C: Baran at 0°, Guest speaks at 0° (unknown voice) -> Speaker is Misafir (unknown voice + known face -> Misafir, NEVER Baran).
4. Scenario D: Two people (Baran at -20°, Oktay at +25°), Oktay speaks -> Speaker is Oktay (NEVER Baran).
5. Scenario E: Depth separation: Two people at 0° (1.0m vs 3.2m) -> Foreground speaker prioritized.
6. Scenario F: Cross-modal conflict: Face=Baran, Voice=Oktay at 0° -> CONFLICT/AMBIGUOUS, neither forced.
7. Scenario G: Unregistered guest speaks alone -> Speaker is Misafir.
8. Scenario H: Spatial ambiguity rejection: Two people at identical angle and depth -> Ambiguous track, no arbitrary guess.
"""

import math
import time
import pytest
from unittest.mock import MagicMock

from astro_ai.contracts.person_state import UnifiedPersonState


class DummyWorldModel:
    def __init__(self, people):
        self._people = {p.person_id: p for p in people}
        import threading
        self._lock = threading.Lock()

    def update_people(self, people_list):
        for p in people_list:
            self._people[p.person_id] = p


class DummySocialBrain:
    def __init__(self, people):
        self.world_model = DummyWorldModel(people)


class DummyNode:
    """Mock node mimicking AstroRealtimeNode's fusion resolution."""
    def __init__(self, people, voice_recognizer=None, speaker_angle=0.0, last_doa_time=0.0):
        self.voice_recognizer = voice_recognizer
        self._speaker_angle = speaker_angle
        self._last_doa_time = last_doa_time
        self.social_brain = DummySocialBrain(people)
        import threading
        self._lock = threading.Lock()
        self._recognized_speaker = None
        self._active_person_name = None
        self._person_hold_until = 0.0
        self._speaker_tentative_name = None
        self._speaker_tentative_count = 0
        self._speaker_tentative_last_time = 0.0
        self.logger_messages = []

    def get_logger(self):
        class Logger:
            def __init__(outer):
                pass
            def info(outer, msg):
                self.logger_messages.append(("INFO", msg))
            def warn(outer, msg):
                self.logger_messages.append(("WARN", msg))
            def debug(outer, msg):
                self.logger_messages.append(("DEBUG", msg))
        return Logger()


# Import the actual method by creating a test harness that binds resolve_active_speaker_and_track
from astro_ai.astro_realtime_node import AstroRealtimeNode

def run_fusion(node, raw_pcm=None):
    return AstroRealtimeNode.resolve_active_speaker_and_track(node, raw_pcm=raw_pcm)


def test_scenario_a_baran_alone_speaking():
    """Baran alone in front of robot (0°, 1.2m), speaks with verified voice."""
    p_baran = UnifiedPersonState(
        person_id="person_baran",
        name="Baran",
        is_known=True,
        identity_confidence=0.90,
        distance_m=1.2,
        azimuth_deg=0.0,
        is_looking_at_robot=True,
        is_present=True,
    )
    mock_vr = MagicMock()
    mock_vr.identify_speaker.return_value = ("Baran", 0.82)

    now = time.monotonic()
    node = DummyNode([p_baran], voice_recognizer=mock_vr, speaker_angle=0.0, last_doa_time=now)
    res = run_fusion(node, raw_pcm=b"\x00\x00" * 1600)

    assert res["name"] == "Baran"
    assert res["is_known"] is True
    assert res["confidence"] >= 0.80
    assert res["conflict"] is False


def test_scenario_b_baran_visible_guest_speaks_off_angle():
    """Baran at 0°, but sound comes from +45° and voice is unrecognized guest."""
    p_baran = UnifiedPersonState(
        person_id="person_baran",
        name="Baran",
        is_known=True,
        identity_confidence=0.90,
        distance_m=1.0,
        azimuth_deg=0.0,
        is_looking_at_robot=True,
        is_present=True,
    )
    mock_vr = MagicMock()
    mock_vr.identify_speaker.return_value = (None, 0.20)  # Unknown voice

    now = time.monotonic()
    # DOA is +45° (sound is from side, far from Baran's 0°)
    node = DummyNode([p_baran], voice_recognizer=mock_vr, speaker_angle=45.0, last_doa_time=now)
    res = run_fusion(node, raw_pcm=b"\x00\x00" * 1600)

    assert res["name"] == "Misafir"
    assert res["is_known"] is False
    assert res["speaker_name"] is None
    # Baran must NOT be claimed as the speaker!
    assert res["name"] != "Baran"


def test_scenario_c_baran_visible_guest_speaks_same_angle():
    """Baran at 0°, voice is unrecognized (Rule 4: Unknown voice + Known face -> Misafir, NEVER Baran)."""
    p_baran = UnifiedPersonState(
        person_id="person_baran",
        name="Baran",
        is_known=True,
        identity_confidence=0.90,
        distance_m=1.0,
        azimuth_deg=0.0,
        is_looking_at_robot=True,
        is_present=True,
    )
    mock_vr = MagicMock()
    mock_vr.identify_speaker.return_value = (None, 0.25)  # Voice unknown

    now = time.monotonic()
    node = DummyNode([p_baran], voice_recognizer=mock_vr, speaker_angle=0.0, last_doa_time=now)
    res = run_fusion(node, raw_pcm=b"\x00\x00" * 1600)

    # Invariant: Unknown voice must NOT adopt Baran's face
    assert res["name"] == "Misafir"
    assert res["is_known"] is False
    assert res["speaker_name"] is None
    assert res["source"] == "unrecognized_voice_guest"


def test_scenario_d_two_people_oktay_speaks():
    """Baran at -20°, Oktay at +25°. Oktay speaks with verified voice and DOA at +25°."""
    p_baran = UnifiedPersonState(
        person_id="person_baran",
        name="Baran",
        is_known=True,
        identity_confidence=0.88,
        distance_m=1.3,
        azimuth_deg=-20.0,
        is_looking_at_robot=False,
        is_present=True,
    )
    p_oktay = UnifiedPersonState(
        person_id="person_oktay",
        name="Oktay",
        is_known=True,
        identity_confidence=0.85,
        distance_m=1.1,
        azimuth_deg=25.0,
        is_looking_at_robot=True,
        is_present=True,
    )
    mock_vr = MagicMock()
    mock_vr.identify_speaker.return_value = ("Oktay", 0.78)

    now = time.monotonic()
    node = DummyNode([p_baran, p_oktay], voice_recognizer=mock_vr, speaker_angle=25.0, last_doa_time=now)
    res = run_fusion(node, raw_pcm=b"\x00\x00" * 1600)

    assert res["name"] == "Oktay"
    assert res["is_known"] is True
    assert res["name"] != "Baran"
    assert res["matched_track"].person_id == "person_oktay"


def test_scenario_e_depth_separation():
    """Two people at 0°: foreground user at 0.9m, background person at 3.0m."""
    p_close = UnifiedPersonState(
        person_id="person_close",
        name="Misafir",
        is_known=False,
        distance_m=0.9,
        azimuth_deg=0.0,
        is_looking_at_robot=True,
        is_present=True,
    )
    p_far = UnifiedPersonState(
        person_id="person_far",
        name="Misafir",
        is_known=False,
        distance_m=3.0,
        azimuth_deg=0.0,
        is_looking_at_robot=False,
        is_present=True,
    )
    mock_vr = MagicMock()
    mock_vr.identify_speaker.return_value = ("Oktay", 0.75)

    now = time.monotonic()
    node = DummyNode([p_close, p_far], voice_recognizer=mock_vr, speaker_angle=0.0, last_doa_time=now)
    res = run_fusion(node, raw_pcm=b"\x00\x00" * 1600)

    # Matched track should be the foreground person at 0.9m, not the person at 3.0m
    assert res["matched_track"].person_id == "person_close"
    assert res["name"] == "Oktay"


def test_scenario_f_cross_modal_conflict():
    """Face is Baran, but voice is Oktay at the same position -> AMBIGUOUS/CONFLICT, neither forced."""
    p_baran = UnifiedPersonState(
        person_id="person_baran",
        name="Baran",
        is_known=True,
        identity_confidence=0.92,
        distance_m=1.0,
        azimuth_deg=0.0,
        is_looking_at_robot=True,
        is_present=True,
    )
    mock_vr = MagicMock()
    mock_vr.identify_speaker.return_value = ("Oktay", 0.75)  # Confirmed Oktay voice

    now = time.monotonic()
    node = DummyNode([p_baran], voice_recognizer=mock_vr, speaker_angle=0.0, last_doa_time=now)
    res = run_fusion(node, raw_pcm=b"\x00\x00" * 1600)

    assert res["conflict"] is True
    assert res["source"] == "cross_modal_conflict"
    assert res["is_known"] is False
    assert res["speaker_name"] is None
    assert res["name"] == "Misafir"


def test_scenario_g_unregistered_guest_alone():
    """Unregistered guest alone speaks, voice not in database."""
    p_guest = UnifiedPersonState(
        person_id="person_guest_1",
        name="Misafir",
        is_known=False,
        distance_m=1.2,
        azimuth_deg=-10.0,
        is_looking_at_robot=True,
        is_present=True,
    )
    mock_vr = MagicMock()
    mock_vr.identify_speaker.return_value = (None, 0.15)

    now = time.monotonic()
    node = DummyNode([p_guest], voice_recognizer=mock_vr, speaker_angle=-10.0, last_doa_time=now)
    res = run_fusion(node, raw_pcm=b"\x00\x00" * 1600)

    assert res["name"] == "Misafir"
    assert res["is_known"] is False
    assert res["speaker_name"] is None


def test_scenario_h_spatial_ambiguity_rejection():
    """Two people at virtually the same angle and depth -> Spatially ambiguous, do not guess arbitrarily."""
    p1 = UnifiedPersonState(
        person_id="person_1",
        name="Misafir",
        is_known=False,
        distance_m=1.2,
        azimuth_deg=5.0,
        is_looking_at_robot=True,
        is_present=True,
    )
    p2 = UnifiedPersonState(
        person_id="person_2",
        name="Misafir",
        is_known=False,
        distance_m=1.3,
        azimuth_deg=6.0,
        is_looking_at_robot=True,
        is_present=True,
    )
    mock_vr = MagicMock()
    mock_vr.identify_speaker.return_value = (None, 0.10)

    now = time.monotonic()
    node = DummyNode([p1, p2], voice_recognizer=mock_vr, speaker_angle=5.5, last_doa_time=now)
    res = run_fusion(node, raw_pcm=b"\x00\x00" * 1600)

    # In spatial ambiguity, matched track is None
    assert res["matched_track"] is None
    assert res["spatial_reason"] == "spatially_ambiguous_tracks"
