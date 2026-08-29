#!/usr/bin/env python3
"""Regression tests for the DOA -> head yaw path.

Each test here pins down one defect found while tracing why the head drifts,
spins continuously, or jumps between the neck limits after running for a while.
"""

import os
import re
import sys
import time
import unittest

pkg_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
repo_root = os.path.abspath(os.path.join(pkg_dir, "..", "..", ".."))
astro_base_inner = os.path.join(pkg_dir, "astro_base")
for p in (pkg_dir, astro_base_inner):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from astro_base.head_tracker_node import (
        HeadTrackerNode,
        angular_diff_deg,
        doa_to_robot_yaw,
    )
except ImportError:
    from head_tracker_node import (
        HeadTrackerNode,
        angular_diff_deg,
        doa_to_robot_yaw,
    )

try:
    from astro_base.head_tracker_node import HEAD_TRACKER_DEFAULTS
except ImportError:
    try:
        from head_tracker_node import HEAD_TRACKER_DEFAULTS
    except ImportError:
        HEAD_TRACKER_DEFAULTS = None

LAUNCH_FILE = os.path.join(
    repo_root, "ros2_ws", "src", "astro_bringup", "launch", "base.launch.py"
)
PARAMS_FILE = os.path.join(
    repo_root, "ros2_ws", "src", "astro_bringup", "config", "astro_params.yaml"
)


class MockMsg:
    def __init__(self, data):
        self.data = data


def make_node() -> HeadTrackerNode:
    """A head tracker parked at 0 deg, awake, hearing a loud steady voice."""
    node = HeadTrackerNode()
    node.enabled = True
    node._is_sleeping = False
    node._is_speaking = False
    node._is_playback_active = False
    node._vad_active = True
    node._latest_rms = 3000.0
    node._ambient_rms = 120.0
    node.vision_fusion_enabled = False
    node.lidar_fusion_enabled = False
    node._vision_person_detected = False
    node._target_yaw = 0.0
    node._estimated_yaw = 0.0
    node._doa_history.clear()
    node._last_gaze_switch_time = 0.0
    return node


class TestShippedConfigurationIsApplied(unittest.TestCase):
    """The YAML in astro_bringup must actually reach the running node."""

    def test_params_yaml_key_matches_launched_node_name(self):
        launch_src = open(LAUNCH_FILE, encoding="utf-8").read()
        params_src = open(PARAMS_FILE, encoding="utf-8").read()

        m = re.search(
            r'executable="head_tracker"[^)]*?name="([^"]+)"', launch_src, re.S
        )
        self.assertIsNotNone(m, "head_tracker Node blogu base.launch.py'da bulunamadi")
        launched_name = m.group(1)

        top_level_keys = set(re.findall(r"^([A-Za-z_/][\w/]*):", params_src, re.M))
        self.assertIn(
            launched_name,
            top_level_keys,
            f"astro_params.yaml '{launched_name}' node adiyla eslesmiyor; "
            f"parametreler sessizce yok sayilir. Mevcut anahtarlar: {sorted(top_level_keys)}",
        )

    def test_code_default_for_doa_invert_matches_shipped_yaml(self):
        self.assertIsNotNone(
            HEAD_TRACKER_DEFAULTS,
            "head_tracker_node tek bir HEAD_TRACKER_DEFAULTS kaynagi disari vermeli",
        )
        params_src = open(PARAMS_FILE, encoding="utf-8").read()
        m = re.search(r"^\s+doa_invert:\s*(\w+)", params_src, re.M)
        self.assertIsNotNone(m, "astro_params.yaml icinde doa_invert yok")
        yaml_value = m.group(1).lower() == "true"

        self.assertEqual(
            HEAD_TRACKER_DEFAULTS["doa_invert"],
            yaml_value,
            "Parametre yuklenemezse kod varsayilani devreye girer; ters isaret "
            "kafayi sesin ayna yonune cevirir.",
        )


class TestYawSignConvention(unittest.TestCase):
    def test_sound_from_the_right_yaws_like_the_look_right_gesture(self):
        # The node's own gesture table is the reference: positive yaw = left (REP-103).
        look_right = HeadTrackerNode.GESTURE_PROFILES["look_right"][0]
        self.assertLess(look_right, 0.0, "jest tablosu bozulmus")

        node = make_node()
        yaw = doa_to_robot_yaw(
            90.0, offset_deg=node.doa_offset_deg, invert=node.doa_invert
        )
        self.assertLess(
            yaw,
            0.0,
            "ReSpeaker 90 derece (sag) ile look_right jesti zit isaret veriyor: "
            "kafa sesin ayna yonune doner.",
        )


class TestConsensusAgainstBackSector(unittest.TestCase):
    def test_sound_from_behind_does_not_flip_between_neck_limits(self):
        """A source behind the robot straddles +-180 and must not split the cluster."""
        node = make_node()
        node.doa_invert = False
        node.consensus_tolerance_deg = 22.0
        # Hold the gaze dwell so no target is committed mid-run; this test is about what
        # lands in the consensus buffer, not about when the head decides to move.
        node._last_gaze_switch_time = time.monotonic()

        # Same physical source, +-5 deg of measurement noise around straight back.
        for doa in (175.0, 185.0, 175.0, 185.0, 175.0, 185.0):
            node._on_doa(MockMsg(doa))

        yaws = [y for _, y in node._doa_history]
        self.assertTrue(yaws, "DOA gecmisi bos")
        spread = max(abs(angular_diff_deg(y, yaws[0])) for y in yaws)
        self.assertLessEqual(
            spread,
            node.consensus_tolerance_deg,
            f"Arkadaki tek kaynak {spread:.0f} derecelik saciliyor: konsensus "
            f"gecmisine kirpilmis degerler yaziliyor. Ornekler: {yaws}",
        )


class TestSelfNoiseGate(unittest.TestCase):
    def test_doa_ignored_right_after_the_head_is_commanded_to_move(self):
        """Head motor noise reaches the head-mounted mic array; do not track during motion."""
        node = make_node()
        node._target_yaw = 60.0  # arbitrated elsewhere (gesture, turn_to_sound, LiDAR)
        node._last_update_time = time.monotonic() - 0.05
        node._control_loop()  # publishes /head_cmd -> the yaw motor starts running

        for _ in range(8):
            node._on_doa(MockMsg(45.0))

        self.assertEqual(
            len(node._doa_history),
            0,
            "Kafa hareket ederken gelen DOA ornekleri kabul edildi.",
        )


class TestVisionServoing(unittest.TestCase):
    def test_stale_vision_measurement_is_applied_only_once(self):
        """One face measurement must produce one correction, not one per control tick."""
        node = make_node()
        node.vision_fusion_enabled = True
        node.vision_gain = 0.35
        node._on_vision_head_yaw(MockMsg(10.0))
        node._vision_person_detected = True
        node._vision_last_seen_time = time.monotonic()

        for _ in range(40):  # 2 s at 20 Hz, no new vision measurement arrives
            node._last_update_time = time.monotonic() - 0.05
            node._control_loop()

        self.assertLessEqual(
            abs(node._target_yaw),
            5.0,
            f"Bayat gorsel olcum hedefi {node._target_yaw:.1f} dereceye tasidi; "
            f"tek olcum her dongude yeniden uygulaniyor.",
        )


if __name__ == "__main__":
    unittest.main()
