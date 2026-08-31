#!/usr/bin/env python3
"""Two-stage gaze: the sound says roughly where, then the camera says exactly who.

The microphones give a coarse direction. Once the head is looking that way the camera can
pick out the person who is actually speaking, using the name the voice recogniser
reports. When the camera is off there is still the LiDAR, which cannot see a face but can
say whether something person-sized is standing there. These tests pin the whole chain,
including what happens as each sensor drops out.
"""

import json
import os
import sys
import time
import unittest

pkg_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
astro_base_inner = os.path.join(pkg_dir, "astro_base")
for p in (pkg_dir, astro_base_inner):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from astro_base.head_tracker_node import HeadTrackerNode, angular_diff_deg
except ImportError:
    from head_tracker_node import HeadTrackerNode, angular_diff_deg


class MockMsg:
    def __init__(self, data):
        self.data = data


class FakeClock:
    def __init__(self):
        self.t = time.monotonic()

    def monotonic(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class MockScan:
    """A LiDAR sweep with objects at given bearings, in the message shape ROS delivers."""

    def __init__(self, objects, step_deg=1.0):
        import math

        self.angle_min = -math.pi
        self.angle_increment = math.radians(step_deg)
        n = int(360.0 / step_deg)
        self.ranges = []
        for i in range(n):
            bearing = -180.0 + i * step_deg
            r = float("inf")
            for centre, width_m, dist in objects:
                half = math.degrees(math.atan2(width_m / 2.0, dist))
                if abs((bearing - centre + 180.0) % 360.0 - 180.0) <= half:
                    r = min(r, dist)
            self.ranges.append(r)


def make_node(clock):
    node = HeadTrackerNode()
    node.enabled = True
    node._is_sleeping = node._is_speaking = node._is_playback_active = False
    node._vad_active = True
    node._latest_rms = 3000.0
    node._ambient_rms = 120.0
    node.head_motion_settle_s = 0.0
    node.lidar_fusion_enabled = False
    node.vision_fusion_enabled = True
    node._target_yaw = node._estimated_yaw = 0.0
    node._last_published_cmd_yaw = 0.0
    node._last_update_time = clock.monotonic()
    node._last_speech_time = clock.monotonic()
    node._last_gaze_switch_time = 0.0
    node._doa_history.clear()
    node._speech_map.clear()
    return node


def faces_msg(entries):
    """entries: [(camera_azimuth_deg, name, is_known, distance_m)]"""
    return MockMsg(
        json.dumps(
            [
                {
                    "camera_azimuth_deg": az,
                    "recognized_name": name,
                    "is_known": known,
                    "distance_m": dist,
                }
                for az, name, known, dist in entries
            ]
        )
    )


def speaker_msg(name, confidence=0.85, is_known=True):
    return MockMsg(
        json.dumps({"name": name, "confidence": confidence, "is_known": is_known})
    )


def talk(node, clock, doa_deg, frames=14, dt=0.05):
    for _ in range(frames):
        node._on_doa(MockMsg(doa_deg))
        clock.advance(dt)


class GazeFusionCase(unittest.TestCase):
    def setUp(self):
        import astro_base.head_tracker_node as H

        self.H = H
        self.clock = FakeClock()
        self._real_time = H.time
        H.time = self.clock
        self.node = make_node(self.clock)

    def tearDown(self):
        self.H.time = self._real_time


class TestSpeakerSelectedGaze(GazeFusionCase):
    def test_the_speaking_face_is_chosen_over_the_larger_one(self):
        """Two people in frame. /vision/head_yaw only ever reports the first (largest)
        face, so following it looks at whoever happens to be nearer the camera rather
        than whoever is talking."""
        self.node._on_vision_faces(
            faces_msg([(-30.0, "Misafir", False, 1.0), (25.0, "Baran", True, 1.8)])
        )
        self.node._on_speaker_id(speaker_msg("Baran"))

        chosen = self.node._select_speaker_face(self.clock.monotonic(), acoustic_bearing=20.0)

        self.assertIsNotNone(chosen, "Konusan kisi karede goruluyordu")
        self.assertEqual(chosen["name"], "Baran")
        self.assertAlmostEqual(chosen["world_yaw"], 25.0, delta=2.0)

    def test_an_unknown_speaker_falls_back_to_the_face_nearest_the_sound(self):
        self.node._on_vision_faces(
            faces_msg([(-70.0, "Misafir", False, 1.2), (40.0, "Misafir", False, 1.4)])
        )
        self.node._on_speaker_id(speaker_msg("Misafir", confidence=0.2, is_known=False))

        chosen = self.node._select_speaker_face(self.clock.monotonic(), acoustic_bearing=45.0)

        self.assertIsNotNone(chosen, "Taninmayan konusmaci da olsa bir yuze bakilmali")
        self.assertAlmostEqual(
            chosen["world_yaw"],
            40.0,
            delta=2.0,
            msg="Sese en yakin yuz secilmeliydi.",
        )

    def test_a_stale_name_match_is_not_preferred_over_a_fresh_face(self):
        """The voice and face databases are separate, so a name can go missing. When the
        named person has aged out of memory the fallback must take over rather than
        steering the head at a position nobody has confirmed for half a minute."""
        self.node._on_vision_faces(faces_msg([(80.0, "Baran", True, 1.5)]))
        self.clock.advance(self.node.people_memory_s + 5.0)
        self.node._on_vision_faces(faces_msg([(10.0, "Misafir", False, 1.2)]))
        self.node._on_speaker_id(speaker_msg("Baran"))

        chosen = self.node._select_speaker_face(self.clock.monotonic(), acoustic_bearing=12.0)

        self.assertIsNotNone(chosen)
        self.assertAlmostEqual(
            chosen["world_yaw"],
            10.0,
            delta=2.0,
            msg="Suresi dolmus kayit hala kullaniliyor.",
        )


class TestVisualServoFollowsTheSpeaker(GazeFusionCase):
    def test_the_servo_centres_the_speaking_face_not_the_first_one(self):
        """/vision/head_yaw carries only faces[0], the largest face in frame. Servoing on
        it centres whoever stands nearest the camera, which with two people in view is a
        coin toss about who gets looked at."""
        self.node._vision_person_detected = True
        self.node._vision_last_seen_time = self.clock.monotonic()
        self.node._last_published_cmd_yaw = 0.0
        self.node._estimated_yaw = 0.0
        self.node._target_yaw = 0.0
        self.node._vad_active = False

        # faces[0] is the big close guest on the left; Baran, who is talking, is on the right.
        self.node._on_vision_faces(
            faces_msg([(-28.0, "Misafir", False, 0.9), (22.0, "Baran", True, 1.9)])
        )
        self.node._on_speaker_id(speaker_msg("Baran"))
        self.node._on_vision_head_yaw(MockMsg(-28.0))  # what the topic reports: faces[0]

        self.node._control_loop()

        self.assertGreater(
            self.node._target_yaw,
            0.0,
            f"Hedef {self.node._target_yaw:.1f}; kafa konusan Baran'a (+22) degil, "
            "karedeki en buyuk yuze (-28) yoneldi.",
        )


class TestPeopleMemory(GazeFusionCase):
    def test_someone_who_walks_out_of_frame_is_remembered(self):
        """The camera only sees +-36 deg. The whole point of turning to a sound is to look
        somewhere the camera is not looking yet, so people cannot be forgotten the instant
        they leave the frame."""
        self.node._on_vision_faces(faces_msg([(30.0, "Baran", True, 1.5)]))
        self.clock.advance(2.0)
        self.node._on_vision_faces(faces_msg([]))  # nobody in frame any more

        remembered = self.node._recall_person("Baran", self.clock.monotonic())
        self.assertIsNotNone(remembered, "Kameradan cikan kisi aninda unutuldu")
        self.assertAlmostEqual(remembered["world_yaw"], 30.0, delta=2.0)

    def test_memory_expires(self):
        self.node._on_vision_faces(faces_msg([(30.0, "Baran", True, 1.5)]))
        self.clock.advance(self.node.people_memory_s + 1.0)

        self.assertIsNone(
            self.node._recall_person("Baran", self.clock.monotonic()),
            "Cok eski konum kaydi hala hatirlaniyor.",
        )

    def test_positions_are_recorded_against_the_commanded_head_angle(self):
        """A face bearing is relative to the camera, which rides on the head. Composing it
        onto the software slew trajectory instead of the angle the firmware was actually
        given puts the person in the wrong place in the room."""
        self.node._last_published_cmd_yaw = 50.0
        self.node._estimated_yaw = 5.0  # still crawling toward 50

        self.node._on_vision_faces(faces_msg([(10.0, "Baran", True, 1.5)]))
        remembered = self.node._recall_person("Baran", self.clock.monotonic())

        self.assertIsNotNone(remembered)
        self.assertAlmostEqual(
            remembered["world_yaw"],
            60.0,
            delta=2.0,
            msg=f"Kisi {remembered['world_yaw']:.1f} dereceye yazildi; kafa 50 derecede "
            "iken +10 derece ofsetli yuz govdede 60 derecededir.",
        )


class TestDegradingSensors(GazeFusionCase):
    def test_with_no_camera_the_lidar_sharpens_the_direction(self):
        """The tilted array puts the sound at +50 while the person is really at +65. The
        LiDAR should pull the target onto the figure it can see -- and must not be
        distracted by the chair at the robot's knee, which is much closer but silent."""
        self.node.vision_fusion_enabled = False
        self.node.lidar_fusion_enabled = True
        self.node._on_laser_scan(MockScan([(-70.0, 0.45, 0.6), (65.0, 0.45, 1.9)]))

        talk(self.node, self.clock, 310.0)  # 310 deg -> +50 with doa_invert=True

        self.assertAlmostEqual(
            self.node._target_yaw,
            65.0,
            delta=6.0,
            msg=f"Hedef {self.node._target_yaw:.1f}; LiDAR figuru +65'te, akustik yon "
            "+50'ydi, dizdeki sandalye ise -70'te. Dogrulama isini yapmadi.",
        )

    def test_with_no_camera_and_no_lidar_the_head_still_turns_to_the_sound(self):
        """Neither sensor is an error condition; they are confirmations that may be absent."""
        self.node.vision_fusion_enabled = False
        self.node.lidar_fusion_enabled = False

        talk(self.node, self.clock, 310.0)  # -> +50

        self.assertAlmostEqual(
            self.node._target_yaw,
            50.0,
            delta=8.0,
            msg="Hicbir dogrulama yokken bile akustik yone donulmeli.",
        )

    def test_a_wall_does_not_confirm_anything(self):
        self.node.vision_fusion_enabled = False
        self.node.lidar_fusion_enabled = True
        # A wall spanning the whole front of the room, right where the sound came from.
        self.node._on_laser_scan(MockScan([(50.0, 6.0, 1.5)]))

        talk(self.node, self.clock, 310.0)  # -> +50

        self.assertAlmostEqual(
            self.node._target_yaw,
            50.0,
            delta=6.0,
            msg=f"Hedef {self.node._target_yaw:.1f}; duvar insan sayilip kafa cekilmis. "
            "Dogrulama olmayinca akustik yonde kalinmali.",
        )


if __name__ == "__main__":
    unittest.main()
