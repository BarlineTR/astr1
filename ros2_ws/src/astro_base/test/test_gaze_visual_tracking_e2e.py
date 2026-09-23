#!/usr/bin/env python3
"""Comprehensive End-to-End Test Suite for ASTRO Gaze & Visual Tracking Stability.

Validates the Behavior Contract (A, B, C, D, E, F) and 10 E2E scenarios:
  1. Audio-to-Visual Lock Handoff
  2. Visual Primacy over Audio Noise
  3. No Return-to-Zero Bounce (Hunting prevention with estimated head pose)
  4. Single-Frame Dropout Immunity (Coasting & Attention Dwell)
  5. Mechanical Angle Clamping (Strictly +-75.0 deg)
  6. Body Alignment Suppression within Head Limits (|yaw| <= 75 deg -> No Wheel Turn)
  7. Body Alignment Trigger at True Mechanical Limit (|yaw| > 75 deg & Encoder verified)
  8. Graceful Target Loss Settlement (Target=NONE -> Soft reset to 0.0 deg)
  9. Encoder Decoupling with Software Estimate (actual_yaw_deg is None, source is ESTIMATED)
  10. Standalone vs ROS Pipeline Equivalence
  11. Extra Test: Encoder UNKNOWN with person at +30°, -30°, +60°, -60° -> Body Wheel Cmd = 0
"""

import math
import os
import sys
import time
import unittest
from typing import List, Optional

pkg_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if pkg_dir not in sys.path:
    sys.path.insert(0, pkg_dir)

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
astro_ai_dir = os.path.join(repo_root, "ros2_ws", "src", "astro_ai")
if astro_ai_dir not in sys.path:
    sys.path.insert(0, astro_ai_dir)

standalone_dir = os.path.join(repo_root, "standalone")
if standalone_dir not in sys.path:
    sys.path.insert(0, standalone_dir)

from astro_base.gaze.attention_arbiter import AttentionArbiterCore
from astro_base.gaze.coordinate_frames import CalibrationConfig, CoordinateTransformer
from astro_base.gaze.gaze_runtime import GazeRuntimeCore
from astro_base.gaze.gaze_state_machine import SocialGazeFSM
from astro_base.gaze.head_controller import HeadControllerCore
from astro_base.gaze.head_state import HeadStateManager, PositionSource
from astro_base.gaze.motion_planner import MotionPlannerCore
from astro_base.gaze.sensor_fusion import AudioVisualFusionCore
from astro_base.gaze.target_manager import TargetManagerCore
from astro_base.gaze.respeaker_localizer import ReSpeakerAudioLocalizer
from astro_base.gaze.gaze_tracker import Detection, GazeResult, GazeTracker
from astro_base.gaze.types import (
    AttentionDecision,
    FilteredAudioState,
    FusedTarget,
    GazeCommand,
    GazeStateEnum,
    GestureGazeIntent,
    Modality,
    PrioritySource,
    TargetState,
    TrackingState,
    VisualMeasurement,
    VisualObservation,
    VisualTargetTrack,
)
from astro_base.gaze.visual_perception import VisualPerceptionCore
from astro_base.gaze.visual_tracker import VisualTrackerCore

from astro_ai.brain.behavior_engine import BehaviorEngine
from astro_ai.brain.world_model import WorldModel
from astro_ai.contracts.behavior_types import (
    BehaviorPriority,
    BehaviorType,
    behavior_intent_to_action_intent,
)
from astro_ai.contracts.consciousness_types import SelfState
from astro_ai.contracts.person_state import UnifiedPersonState


class TestGazeVisualTrackingE2E(unittest.TestCase):
    """Authoritative test suite for Astro Gaze & Visual Tracking stability."""

    def setUp(self):
        self.calib = CalibrationConfig()
        self.transformer = CoordinateTransformer(self.calib)
        self.perception = VisualPerceptionCore(transformer=self.transformer)
        self.tracker = VisualTrackerCore(transformer=self.transformer, coasting_timeout_s=2.0)
        self.fusion = AudioVisualFusionCore()
        self.target_mgr = TargetManagerCore(acquisition_threshold=0.75, hold_threshold=0.40)
        self.arbiter = AttentionArbiterCore(min_limit_deg=-75.0, max_limit_deg=75.0)
        self.fsm = SocialGazeFSM(min_limit_deg=-75.0, max_limit_deg=75.0)
        self.planner = MotionPlannerCore(min_limit_deg=-75.0, max_limit_deg=75.0)

    # -------------------------------------------------------------------------
    # Behavior Contract Scenarios A through D: Transformation Chain Tests
    # -------------------------------------------------------------------------
    def test_scenario_a_bearing_pos15_estimated_0(self):
        """Test A: Camera bearing +15°, estimated_head 0° -> target ≈ +15° (Real chain)."""
        tracker = GazeTracker(calibration=self.calib)
        det = Detection(x=147, y=200, w=80, h=80, confidence=0.88)
        now = 1000.0
        result = tracker.step(
            faces=[det],
            frame_size=(640, 480),
            doa_deg=None,
            measured_head_deg=None,
            timestamp=now,
            estimated_head_deg=0.0,
        )
        self.assertAlmostEqual(result.target_yaw_deg, 15.0, delta=1.5)
        self.assertEqual(result.owner, PrioritySource.VISUAL_TRACKING)

    def test_scenario_b_bearing_neg30_estimated_0(self):
        """Test B: Camera bearing -30°, estimated_head 0° -> target ≈ -26°..-30° (Real chain with parallax)."""
        tracker = GazeTracker(calibration=self.calib)
        det = Detection(x=547, y=200, w=80, h=80, confidence=0.88)
        now = 1000.0
        result = tracker.step(
            faces=[det],
            frame_size=(640, 480),
            doa_deg=None,
            measured_head_deg=None,
            timestamp=now,
            estimated_head_deg=0.0,
        )
        self.assertAlmostEqual(result.target_yaw_deg, -26.2, delta=2.0)
        self.assertEqual(result.owner, PrioritySource.VISUAL_TRACKING)

    def test_scenario_c_bearing_0_estimated_pos30(self):
        """Test C: Camera bearing 0°, fixation_baseline +30° -> target ≈ +30° (Real chain)."""
        tracker = GazeTracker(calibration=self.calib)
        tracker.fsm.fixation_baseline_yaw_deg = 30.0
        det = Detection(x=280, y=200, w=80, h=80, confidence=0.88)
        now = 1000.0
        result = tracker.step(
            faces=[det],
            frame_size=(640, 480),
            doa_deg=None,
            measured_head_deg=None,
            timestamp=now,
            estimated_head_deg=30.0,
        )
        self.assertAlmostEqual(result.target_yaw_deg, 30.0, delta=1.5)
        self.assertEqual(result.owner, PrioritySource.VISUAL_TRACKING)

    def test_scenario_d_bearing_0_estimated_neg30(self):
        """Test D: Camera bearing 0°, fixation_baseline -30° -> target ≈ -30° (Real chain)."""
        tracker = GazeTracker(calibration=self.calib)
        tracker.fsm.fixation_baseline_yaw_deg = -30.0
        det = Detection(x=280, y=200, w=80, h=80, confidence=0.88)
        now = 1000.0
        result = tracker.step(
            faces=[det],
            frame_size=(640, 480),
            doa_deg=None,
            measured_head_deg=None,
            timestamp=now,
            estimated_head_deg=-30.0,
        )
        self.assertAlmostEqual(result.target_yaw_deg, -30.0, delta=1.5)
        self.assertEqual(result.owner, PrioritySource.VISUAL_TRACKING)

    def test_decoupling_proof_constant_phi_cam_varying_estimated_yaw(self):
        """Decoupling Proof: With constant phi_cam = -35°, varying estimated_head_yaw wildly does NOT alter target_yaw."""
        tracker = GazeTracker(calibration=self.calib)
        tracker.fsm.fixation_baseline_yaw_deg = 60.0
        # phi_cam = -35.0 deg -> u in image
        norm_u = -(-35.0) / 36.0
        u = 320.0 + norm_u * 320.0
        det = Detection(x=int(round(u - 40)), y=200, w=80, h=80, confidence=0.88)

        now = 1000.0
        estimates = [60.0, 50.0, 40.0, 30.0, 20.0, 0.0, -20.0, 55.0]
        initial_target = None
        for i, est_yaw in enumerate(estimates):
            t = now + i * 0.04
            result = tracker.step(
                faces=[det],
                frame_size=(640, 480),
                doa_deg=None,
                measured_head_deg=None,
                timestamp=t,
                estimated_head_deg=est_yaw,
            )
            if initial_target is None:
                initial_target = result.target_yaw_deg
                # Baseline = 60°, pinhole bearing ≈ -29.8° -> target ≈ 30.2°
                self.assertAlmostEqual(initial_target, 30.2, delta=1.5)
            # Decoupling proof: target must stay strictly locked regardless of estimated_head_deg
            self.assertAlmostEqual(
                result.target_yaw_deg, initial_target, delta=0.5,
                msg=f"Target changed with estimated_head_deg={est_yaw}°: {result.target_yaw_deg} vs {initial_target}",
            )

    def test_motor_stall_immunity_constant_phi_cam(self):
        """Scenario 3: Motor stall with constant phi_cam = -35° holds target at +30.2° for 50+ cycles without drift."""
        tracker = GazeTracker(calibration=self.calib)
        tracker.fsm.fixation_baseline_yaw_deg = 60.0
        norm_u = -(-35.0) / 36.0
        u = 320.0 + norm_u * 320.0
        det = Detection(x=int(round(u - 40)), y=200, w=80, h=80, confidence=0.88)

        now = 1000.0
        targets = []
        for i in range(60):  # 60 cycles = 2.4 seconds
            t = now + i * 0.04
            sim_est = max(25.0, 60.0 - i * 1.5)
            result = tracker.step(
                faces=[det],
                frame_size=(640, 480),
                doa_deg=None,
                measured_head_deg=None,
                timestamp=t,
                estimated_head_deg=sim_est,
            )
            targets.append(result.target_yaw_deg)

        # In every single frame across 60 cycles, target must remain near initial target (~30.2°)
        # It must NEVER drift to -10°, -58°, or ±75°!
        expected_tgt = targets[0]
        for i, tgt in enumerate(targets):
            self.assertAlmostEqual(
                tgt, expected_tgt, delta=1.0,
                msg=f"Cycle {i}: target drifted to {tgt}° (expected ~{expected_tgt}°)",
            )

    def test_optical_evidence_arrival_and_baseline_promotion(self):
        """In UNKNOWN mode, baseline is ONLY promoted when optical evidence (|phi_cam| <= 3.0°) is held for >= 3 frames."""
        tracker = GazeTracker(calibration=self.calib)
        tracker.fsm.fixation_baseline_yaw_deg = 0.0
        now = 1000.0

        # Frame 1 & 2: Target appears off-center
        norm_u = -(25.0) / 36.0
        u = 320.0 + norm_u * 320.0
        det_offcenter = Detection(x=int(round(u - 40)), y=200, w=80, h=80, confidence=0.88)
        res1 = tracker.step(faces=[det_offcenter], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=now)
        res2 = tracker.step(faces=[det_offcenter], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=now + 0.04)

        expected_yaw = res2.target_yaw_deg
        self.assertAlmostEqual(expected_yaw, 22.3, delta=2.0)
        # Saccade is locked, baseline is still 0.0
        self.assertEqual(tracker.fsm.fixation_baseline_yaw_deg, 0.0)

        # Now simulate head physically arriving: face is centered in camera (phi_cam = 0°)
        det_centered = Detection(x=280, y=200, w=80, h=80, confidence=0.88)  # u=320, phi_cam=0°
        # Frame 3 (optical center count = 1): baseline still 0.0
        tracker.step(faces=[det_centered], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=now + 0.08)
        self.assertEqual(tracker.fsm.fixation_baseline_yaw_deg, 0.0)

        # Frame 4 (optical center count = 2): baseline still 0.0
        tracker.step(faces=[det_centered], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=now + 0.12)
        self.assertEqual(tracker.fsm.fixation_baseline_yaw_deg, 0.0)

        # Frame 5 (optical center count = 3): arrival confirmed -> baseline promoted!
        res5 = tracker.step(faces=[det_centered], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=now + 0.16)
        self.assertAlmostEqual(tracker.fsm.fixation_baseline_yaw_deg, expected_yaw, delta=2.0)
        self.assertEqual(res5.gaze_state, GazeStateEnum.HOLDING_ATTENTION)

    def test_unknown_to_encoder_handoff_zero_jump(self):
        """Handoff from UNKNOWN to ENCODER mode: zero discontinuous jump in target yaw."""
        tracker = GazeTracker(calibration=self.calib)
        tracker.fsm.fixation_baseline_yaw_deg = 25.0
        now = 1000.0

        # Person centered at baseline +25.0° in open-loop
        det_centered = Detection(x=280, y=200, w=80, h=80, confidence=0.88)
        res_unknown = tracker.step(
            faces=[det_centered],
            frame_size=(640, 480),
            doa_deg=None,
            measured_head_deg=None,
            timestamp=now,
        )

        # Encoder comes online reporting 25.0°
        res_encoder = tracker.step(
            faces=[det_centered],
            frame_size=(640, 480),
            doa_deg=None,
            measured_head_deg=25.0,
            timestamp=now + 0.04,
        )

        # Target yaw should have virtually zero jump (|delta| <= 1.0°)
        jump = abs(res_encoder.target_yaw_deg - res_unknown.target_yaw_deg)
        self.assertLessEqual(jump, 1.0)

    # -------------------------------------------------------------------------
    # Behavior Contract Scenarios E and F: Trajectory & Anomaly Tests
    # -------------------------------------------------------------------------
    def test_scenario_e_normal_tracking_ramp(self):
        """Test E: Ramp +15° -> +16° -> +18° -> +20° tracks smoothly without overshoot."""
        tracker = GazeTracker(calibration=self.calib)
        head = HeadStateManager()
        now = 1000.0
        world_angles = [15.0, 15.0, 15.0, 15.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0]
        for i, world_yaw in enumerate(world_angles):
            t = now + i * 0.04
            hstate = head.evaluate(timestamp=t)
            h_yaw = hstate.estimated_yaw_deg or 0.0
            cam_bearing = world_yaw - h_yaw
            norm_u = -cam_bearing / 36.0
            u = 320.0 + norm_u * 320.0
            det = Detection(x=int(round(u - 40)), y=200, w=80, h=80, confidence=0.88)
            result = tracker.step(
                faces=[det],
                frame_size=(640, 480),
                doa_deg=None,
                measured_head_deg=None,
                timestamp=t,
                estimated_head_deg=hstate.estimated_yaw_deg,
            )
            head.on_command_accepted(result.target_yaw_deg, timestamp=t)
            self.assertLess(abs(result.target_yaw_deg), 35.0)
            self.assertGreater(result.target_yaw_deg, 5.0)

    def test_scenario_f_single_frame_anomaly_rejection(self):
        """Test F: Single-frame anomaly (+15° -> sudden >30° jump) is rejected/coasted."""
        tracker = GazeTracker(calibration=self.calib)
        now = 1000.0
        # Frame 1: +15°
        u_15 = 320.0 - (15.0 / 36.0) * 320.0
        det1 = Detection(x=int(round(u_15 - 40)), y=200, w=80, h=80, confidence=0.90)
        res1 = tracker.step(faces=[det1], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=now, estimated_head_deg=0.0)

        # Frame 2: +15° (confirms track)
        res2 = tracker.step(faces=[det1], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=now + 0.04, estimated_head_deg=0.0)
        self.assertAlmostEqual(res2.target_yaw_deg, 15.0, delta=2.0)

        # Frame 3: Anomalous jump in observation (-30° bearing vs +15° track -> 45° jump)
        u_neg30 = 320.0 + (30.0 / 36.0) * 320.0
        det_anomaly = Detection(x=int(round(u_neg30 - 40)), y=200, w=80, h=80, confidence=0.90)
        res3 = tracker.step(faces=[det_anomaly], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=now + 0.08, estimated_head_deg=0.0)

        # Must NOT jump to -30° or ±75°; must coast near +15°!
        self.assertAlmostEqual(res3.target_yaw_deg, 15.0, delta=4.0)

    # -------------------------------------------------------------------------
    # Scenario 1: Audio-to-Visual Lock Handoff
    # -------------------------------------------------------------------------
    def test_scenario_1_audio_to_visual_lock_handoff(self):
        """Audio orienting hands over immediately to visual tracking when face is detected."""
        now = 100.0
        # 1. Start with audio target at +45°
        audio_state = FilteredAudioState(timestamp=now, valid=True, azimuth_deg=45.0, confidence=0.80)
        fused = self.fusion.fuse(audio_state=audio_state, visual_tracks=[], timestamp=now)
        t_state = self.target_mgr.update(fused, now)
        self.assertIsNotNone(t_state.active_target)
        self.assertEqual(t_state.active_target.modality, Modality.AUDIO)

        # 2. Face appears in camera frame
        obs = self.perception.process_detection(
            x=280, y=200, w=80, h=80, depth_m=1.5,
            timestamp=now + 0.05,
            actual_head_yaw_deg=None,
            estimated_head_yaw_deg=45.0,
            frame_width=640, frame_height=480,
            confidence=0.85,
        )
        tracks = self.tracker.update([obs], now + 0.05, estimated_head_yaw_deg=45.0)
        fused = self.fusion.fuse(audio_state=audio_state, visual_tracks=tracks, timestamp=now + 0.05)
        t_state = self.target_mgr.update(fused, now + 0.05)

        # Visual target must immediately preempt audio!
        self.assertIsNotNone(t_state.active_target)
        self.assertIn(t_state.active_target.modality, (Modality.VISION, Modality.FUSED))
        decision = self.arbiter.arbitrate(t_state, timestamp=now + 0.05)
        self.assertIn(decision.owner, (PrioritySource.VISUAL_TRACKING, PrioritySource.ACTIVE_SPEAKER))

    # -------------------------------------------------------------------------
    # Scenario 2: Visual Primacy over Audio Noise
    # -------------------------------------------------------------------------
    def test_scenario_2_visual_primacy_over_audio_noise(self):
        """Noisy audio packets cannot hijack gaze while actively tracking a person."""
        now = 200.0
        # Established visual track
        obs = self.perception.process_detection(
            x=320, y=240, w=100, h=100, depth_m=1.2,
            timestamp=now,
            actual_head_yaw_deg=None,
            estimated_head_yaw_deg=0.0,
            confidence=0.90,
        )
        tracks = self.tracker.update([obs], now, estimated_head_yaw_deg=0.0)
        fused = self.fusion.fuse(audio_state=None, visual_tracks=tracks, timestamp=now)
        t_state = self.target_mgr.update(fused, now)
        self.assertEqual(t_state.active_target.modality, Modality.VISION)

        # Audio noise packet arrives at -50°
        noisy_audio = FilteredAudioState(timestamp=now + 0.05, valid=True, azimuth_deg=-50.0, confidence=0.75)
        fused_with_noise = self.fusion.fuse(audio_state=noisy_audio, visual_tracks=tracks, timestamp=now + 0.05)
        t_state_noise = self.target_mgr.update(fused_with_noise, now + 0.05)

        # Active target must remain the visual face!
        self.assertEqual(t_state_noise.active_target.target_id, tracks[0].target_id)
        decision = self.arbiter.arbitrate(t_state_noise, timestamp=now + 0.05)
        self.assertEqual(decision.owner, PrioritySource.VISUAL_TRACKING)

    # -------------------------------------------------------------------------
    # Scenario 3: No Return-to-Zero Bounce
    # -------------------------------------------------------------------------
    def test_scenario_3_no_return_to_zero_bounce(self):
        """When head is at baseline +30° and person is centered (cam_az=0°), target_yaw stays at +30°."""
        now = 300.0
        # Head fixation baseline is at +30° (open-loop baseline)
        baseline = 30.0

        # Person is centered in camera (x=270, w=100 -> center_u=320 -> cam_azimuth = 0.0°)
        obs = self.perception.process_detection(
            x=270, y=190, w=100, h=100, depth_m=1.5,
            timestamp=now,
            actual_head_yaw_deg=None,
            fixation_baseline_yaw_deg=baseline,
            frame_width=640, frame_height=480,
            confidence=0.88,
        )
        self.assertEqual(obs.body_yaw_source, "UNKNOWN")
        self.assertAlmostEqual(obs.body_azimuth_deg, 30.0, places=0)

        tracks = self.tracker.update([obs], now, fixation_baseline_yaw_deg=baseline)
        self.assertAlmostEqual(tracks[0].body_azimuth_deg, 30.0, places=0)
        self.assertEqual(tracks[0].body_yaw_source, "UNKNOWN")

        fused = self.fusion.fuse(audio_state=None, visual_tracks=tracks, timestamp=now)
        t_state = self.target_mgr.update(fused, now)
        decision = self.arbiter.arbitrate(t_state, timestamp=now)

        # The target yaw must stay around +30.0°, NOT bounce back to 0.0°!
        self.assertAlmostEqual(decision.target_yaw_deg, 30.0, places=0)
        self.assertNotAlmostEqual(decision.target_yaw_deg, 0.0, places=1)

    # -------------------------------------------------------------------------
    # Scenario 4: Single-Frame Dropout Immunity
    # -------------------------------------------------------------------------
    def test_scenario_4_single_frame_dropout_immunity(self):
        """1-2 missed frames do not reset target yaw or trigger audio takeover."""
        now = 400.0
        # Frame 1: Person tracked at +25°
        obs = self.perception.process_detection(
            x=300, y=240, w=80, h=80, depth_m=1.5,
            timestamp=now, estimated_head_yaw_deg=25.0, confidence=0.85,
        )
        tracks = self.tracker.update([obs], now, estimated_head_yaw_deg=25.0)
        t_state = self.target_mgr.update(self.fusion.fuse(None, tracks, now), now)
        decision1 = self.arbiter.arbitrate(t_state, timestamp=now)
        self.assertEqual(decision1.owner, PrioritySource.VISUAL_TRACKING)

        # Frame 2: Detection dropout (empty list)
        tracks_drop = self.tracker.update([], now + 0.04, estimated_head_yaw_deg=25.0)
        self.assertTrue(len(tracks_drop) > 0)
        self.assertEqual(tracks_drop[0].tracking_state, TrackingState.COASTING)

        # TargetManager holds active target during coasting
        t_state_drop = self.target_mgr.update(self.fusion.fuse(None, tracks_drop, now + 0.04), now + 0.04)
        self.assertIsNotNone(t_state_drop.active_target)
        decision2 = self.arbiter.arbitrate(t_state_drop, timestamp=now + 0.04)
        self.assertEqual(decision2.owner, PrioritySource.VISUAL_TRACKING)
        self.assertAlmostEqual(decision2.target_yaw_deg, decision1.target_yaw_deg, places=1)

    # -------------------------------------------------------------------------
    # Scenario 5: Mechanical Angle Clamping
    # -------------------------------------------------------------------------
    def test_scenario_5_mechanical_angle_clamping(self):
        """Any angle beyond +-75.0 deg is strictly clamped before sending to actuator."""
        # Test arbiter clamping
        fake_target = FusedTarget(
            target_id="extreme",
            modality=Modality.VISION,
            body_azimuth_deg=121.0,
            body_elevation_deg=0.0,
            distance_m=1.0,
            confidence=0.90,
            is_speaking=False,
            eye_contact=False,
            person_name=None,
            is_known=False,
            timestamp=500.0,
            tracking_state=TrackingState.TRACKING,
        )
        t_state = TargetState(active_target=fake_target, candidate_targets=[fake_target], timestamp=500.0)
        decision = self.arbiter.arbitrate(t_state, timestamp=500.0)
        self.assertLessEqual(decision.target_yaw_deg, 75.0)
        self.assertGreaterEqual(decision.target_yaw_deg, -75.0)

        # Test motion planner clamping
        cmd = GazeCommand(
            target_yaw_deg=121.0,
            target_pitch_deg=0.0,
            priority_source=PrioritySource.VISUAL_TRACKING,
            gaze_state=GazeStateEnum.TRACKING,
            active_target_id="extreme",
            confidence=0.90,
            timestamp=500.0,
        )
        traj = self.planner.plan_step(cmd, actual_pos_deg=0.0, timestamp=500.0)
        self.assertLessEqual(traj.position_deg, 75.0)
        self.assertGreaterEqual(traj.position_deg, -75.0)

    # -------------------------------------------------------------------------
    # Scenario 6: Body Alignment Suppression within Head Limits
    # -------------------------------------------------------------------------
    def test_scenario_6_body_alignment_suppression_within_head_limits(self):
        """When person is at +60° (within +-75°), head tracks person but body stays still."""
        engine = BehaviorEngine()
        world_model = WorldModel()
        self_state = SelfState()
        self_state.current_head_yaw_deg = 0.0
        self_state.focused_person_id = "p1"

        # Person at +60° (head can comfortably reach)
        person = UnifiedPersonState(
            person_id="p1",
            is_present=True,
            distance_m=1.5,
            azimuth_deg=60.0,
            visual_confidence=0.85,
        )
        world_model.update_people([person])

        intent = engine.step(world_model, self_state)
        # ALIGN_BODY_TO_TARGET must NOT be triggered!
        if intent:
            self.assertNotEqual(intent.behavior_type, BehaviorType.ALIGN_BODY_TO_TARGET)
            action = behavior_intent_to_action_intent(intent)
            if action and action.action_type == "move_robot":
                self.fail("Body wheel command was generated when person is within head limits!")

    # -------------------------------------------------------------------------
    # Scenario 7: Body Alignment Trigger at True Mechanical Limit
    # -------------------------------------------------------------------------
    def test_scenario_7_body_alignment_trigger_at_true_mechanical_limit(self):
        """When person is at +80° (>75°) with verified encoder, ALIGN_BODY_TO_TARGET triggers."""
        engine = BehaviorEngine()
        world_model = WorldModel()
        self_state = SelfState()
        self_state.head_position_source = "ENCODER"
        self_state.current_head_yaw_deg = 70.0
        self_state.focused_person_id = "p1"

        person = UnifiedPersonState(
            person_id="p1",
            is_present=True,
            distance_m=1.5,
            azimuth_deg=80.0,
            visual_confidence=0.85,
        )
        person.body_yaw_source = "ENCODER"
        world_model.update_people([person])

        intent = engine.step(world_model, self_state)
        self.assertIsNotNone(intent)
        self.assertEqual(intent.behavior_type, BehaviorType.ALIGN_BODY_TO_TARGET)
        action = behavior_intent_to_action_intent(intent)
        self.assertIsNotNone(action)
        self.assertEqual(action.action_type, "move_robot")
        self.assertEqual(action.parameters["direction"], "left")

    # -------------------------------------------------------------------------
    # Scenario 8: Graceful Target Loss Settlement
    # -------------------------------------------------------------------------
    def test_scenario_8_graceful_target_loss_settlement(self):
        """When target is completely lost after timeout, FSM softly resets to 0.0°."""
        now = 600.0
        # Initialize with target at +40°
        obs = self.perception.process_detection(
            x=320, y=240, w=80, h=80, depth_m=1.5,
            timestamp=now, actual_head_yaw_deg=40.0, confidence=0.85,
        )
        tracks = self.tracker.update([obs], now, actual_head_yaw_deg=40.0)
        t_state = self.target_mgr.update(self.fusion.fuse(None, tracks, now), now)
        cmd = self.fsm.update(t_state, actual_head_yaw_deg=40.0, timestamp=now)
        self.assertEqual(cmd.gaze_state, GazeStateEnum.TRACKING)

        # 1. 0.1s with no detection: Target is NOT dropped, it enters COASTING mode
        now += 0.1
        tracks_coasting = self.tracker.update([], now, actual_head_yaw_deg=40.0)
        t_state_coasting = self.target_mgr.update(self.fusion.fuse(None, tracks_coasting, now), now)
        self.assertIsNotNone(t_state_coasting.active_target)
        self.assertEqual(t_state_coasting.active_target.tracking_state, TrackingState.COASTING)

        # 2. After coasting timeout (2.5s > 2.0s): Track expires, TargetManager drops active target
        now += 2.5
        tracks_lost = self.tracker.update([], now, actual_head_yaw_deg=40.0)
        t_state_lost = self.target_mgr.update(self.fusion.fuse(None, tracks_lost, now), now)
        self.assertIsNone(t_state_lost.active_target)

        # FSM enters HOLDING_ATTENTION (dropout coasting)
        cmd_hold = self.fsm.update(t_state_lost, actual_head_yaw_deg=40.0, timestamp=now)
        self.assertEqual(cmd_hold.gaze_state, GazeStateEnum.HOLDING_ATTENTION)

        # 3. Attention dwell expires (2.6s > min_attention_dwell_s 2.5s) -> transitions to TARGET_LOST
        now += 2.6
        cmd_lost = self.fsm.update(t_state_lost, actual_head_yaw_deg=40.0, timestamp=now)
        self.assertEqual(cmd_lost.gaze_state, GazeStateEnum.TARGET_LOST)

        # 4. Target lost timeout expires (1.1s > target_lost_timeout_s 1.0s) -> transitions to RECOVERING
        now += 1.1
        cmd_recovering = self.fsm.update(t_state_lost, actual_head_yaw_deg=40.0, timestamp=now)
        self.assertEqual(cmd_recovering.gaze_state, GazeStateEnum.RECOVERING)
        self.assertAlmostEqual(cmd_recovering.target_yaw_deg, 0.0, places=1)

        # 5. Head arrives at center -> transitions to IDLE
        now += 0.5
        cmd_idle = self.fsm.update(t_state_lost, actual_head_yaw_deg=0.0, timestamp=now)
        self.assertEqual(cmd_idle.gaze_state, GazeStateEnum.IDLE)
        self.assertAlmostEqual(cmd_idle.target_yaw_deg, 0.0, places=1)

    # -------------------------------------------------------------------------
    # Scenario 9: Encoder Decoupling with Software Estimate
    # -------------------------------------------------------------------------
    def test_scenario_9_encoder_decoupling_with_software_estimate(self):
        """When encoder is absent, actual_yaw_deg is None and optical transform source is UNKNOWN."""
        state_mgr = HeadStateManager(ticks_per_deg=1.5)
        # Accept motor command to +35.0°
        state_mgr.on_command_accepted(35.0, timestamp=700.0)
        hstate = state_mgr.evaluate(timestamp=700.1)

        self.assertEqual(hstate.position_source, PositionSource.ESTIMATED)
        self.assertIsNone(hstate.actual_yaw_deg)
        self.assertIsNotNone(hstate.estimated_yaw_deg)

        # Verify perception correctly labels optical transform source as UNKNOWN (decoupled from software simulation)
        obs = self.perception.process_detection(
            x=320, y=240, w=80, h=80, depth_m=1.5,
            timestamp=700.1,
            actual_head_yaw_deg=hstate.actual_yaw_deg,
            estimated_head_yaw_deg=hstate.estimated_yaw_deg,
        )
        self.assertEqual(obs.body_yaw_source, "UNKNOWN")

    # -------------------------------------------------------------------------
    # Scenario 10: Standalone vs ROS Pipeline Equivalence
    # -------------------------------------------------------------------------
    def test_scenario_10_standalone_vs_ros_pipeline_equivalence(self):
        """Both standalone GazeTracker and ROS GazeRuntimeCore yield identical outputs."""
        runtime = GazeRuntimeCore(calibration=self.calib)
        det = [Detection(x=300, y=200, w=100, h=100, confidence=0.88, detector_source="oak_d")]

        t0 = 800.0
        result_ros = runtime.step(faces=det, frame_size=(640, 480), timestamp=t0)
        result_standalone = runtime.tracker.step(faces=det, frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=t0)

        self.assertAlmostEqual(result_ros.target_yaw_deg, result_standalone.target_yaw_deg, places=2)
        self.assertEqual(result_ros.owner, result_standalone.owner)
        self.assertEqual(result_ros.gaze_state, result_standalone.gaze_state)

    # -------------------------------------------------------------------------
    # Extra Test: Encoder UNKNOWN with person at +30°, -30°, +60°, -60°
    # -------------------------------------------------------------------------
    def test_extra_encoder_unknown_body_wheel_command_zero(self):
        """When encoder is UNKNOWN, person at +30°, -30°, +60°, -60° generates NO body wheel commands."""
        engine = BehaviorEngine()
        angles = [30.0, -30.0, 60.0, -60.0]

        for angle in angles:
            world_model = WorldModel()
            self_state = SelfState()
            self_state.head_position_source = "UNKNOWN"
            self_state.is_head_encoder_valid = False

            person = UnifiedPersonState(
                person_id="target_person",
                is_present=True,
                distance_m=1.8,
                azimuth_deg=angle,
                visual_confidence=0.85,
            )
            person.body_yaw_source = "UNKNOWN"
            world_model.update_people([person])

            intent = engine.step(world_model, self_state)
            if intent:
                self.assertNotEqual(
                    intent.behavior_type,
                    BehaviorType.ALIGN_BODY_TO_TARGET,
                    f"ALIGN_BODY_TO_TARGET was incorrectly triggered at angle {angle}° when encoder is UNKNOWN!",
                )
                action = behavior_intent_to_action_intent(intent)
                if action and action.action_type == "move_robot":
                    self.fail(f"Body wheel command was generated at angle {angle}° with UNKNOWN encoder!")

    # Aliases for Behavior Contract Scenarios G, H, I, J
    test_scenario_g_visual_primacy_over_audio = test_scenario_2_visual_primacy_over_audio_noise
    test_scenario_h_encoder_unknown_body_wheel_command_zero = test_extra_encoder_unknown_body_wheel_command_zero
    test_scenario_i_graceful_target_loss_settlement = test_scenario_8_graceful_target_loss_settlement
    test_scenario_j_standalone_vs_ros_pipeline_equivalence = test_scenario_10_standalone_vs_ros_pipeline_equivalence

    # -------------------------------------------------------------------------
    # Mandatory Regression Tests (Regression Suite)
    # -------------------------------------------------------------------------
    def test_regression_1_15_consecutive_face_loss_frames_holds_target(self):
        """15 consecutive face-loss frames -> target yaw stays within +-5 deg of last confirmed heading."""
        tracker = GazeTracker(calibration=self.calib)
        t = 1000.0
        # 5 frames of solid detection at x=147 (bearing ~ +14°)
        det = Detection(x=147, y=200, w=80, h=80, confidence=0.88)
        last_confirmed_yaw = None
        for i in range(5):
            res = tracker.step(faces=[det], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=t)
            t += 0.033
            last_confirmed_yaw = res.target_yaw_deg

        self.assertIsNotNone(last_confirmed_yaw)
        self.assertGreater(last_confirmed_yaw, 5.0)

        # 15 consecutive face-loss frames (approx 500 ms)
        for i in range(15):
            res = tracker.step(faces=[], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=t)
            t += 0.033
            # During coasting/dwell, target must stay within +-5 deg of last confirmed heading, no runaway or sign flip!
            self.assertLessEqual(
                abs(res.target_yaw_deg - last_confirmed_yaw),
                5.0,
                f"Frame {i+1}/15 face loss drifted: {res.target_yaw_deg} vs confirmed {last_confirmed_yaw}",
            )

    def test_regression_2_150ms_face_dropout_preserves_track_id(self):
        """150 ms face dropout (5 frames) -> track ID preserved (person_1), zero TARGET_SWITCH."""
        tracker = GazeTracker(calibration=self.calib)
        t = 1000.0
        det = Detection(x=200, y=200, w=80, h=80, confidence=0.90)
        # Establish track
        res = None
        for _ in range(5):
            res = tracker.step(faces=[det], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=t)
            t += 0.033

        self.assertEqual(res.target_id, "person_1")

        # 5 frames (approx 165ms) of dropout
        for _ in range(5):
            tracker.step(faces=[], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=t)
            t += 0.033

        # Face reappears near same position
        det_reappear = Detection(x=205, y=200, w=80, h=80, confidence=0.88)
        res_after = tracker.step(faces=[det_reappear], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=t)

        self.assertEqual(res_after.target_id, "person_1", "Track ID must be preserved as person_1 after 150ms dropout")

    def test_regression_3_high_velocity_dropout_no_target_jump(self):
        """High initial velocity (vy = 1.0 m/s) during face dropout -> gaze target does not jump or flip signs."""
        # 1. Positive heading test
        tracker = GazeTracker(calibration=self.calib)
        t = 1000.0
        xs_pos = [220, 200, 180, 160]
        res = None
        for x in xs_pos:
            det = Detection(x=x, y=200, w=80, h=80, confidence=0.90)
            res = tracker.step(faces=[det], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=t)
            t += 0.033

        confirmed_yaw_pos = res.target_yaw_deg
        self.assertGreater(confirmed_yaw_pos, 0.0)
        # Dropout for 10 frames
        for i in range(10):
            res_drop = tracker.step(faces=[], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=t)
            t += 0.033
            self.assertGreaterEqual(res_drop.target_yaw_deg, 0.0, "Positive target yaw must not flip signs during dropout")
            self.assertLessEqual(abs(res_drop.target_yaw_deg - confirmed_yaw_pos), 5.0, "Gaze target must stay within +-5 deg of confirmed heading")

        # 2. Negative heading test
        tracker_neg = GazeTracker(calibration=self.calib)
        t = 2000.0
        xs_neg = [420, 440, 460, 480]
        for x in xs_neg:
            det = Detection(x=x, y=200, w=80, h=80, confidence=0.90)
            res = tracker_neg.step(faces=[det], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=t)
            t += 0.033

        confirmed_yaw_neg = res.target_yaw_deg
        self.assertLess(confirmed_yaw_neg, 0.0)
        for i in range(10):
            res_drop = tracker_neg.step(faces=[], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=t)
            t += 0.033
            self.assertLessEqual(res_drop.target_yaw_deg, 0.0, "Negative target yaw must not flip signs during dropout")
            self.assertLessEqual(abs(res_drop.target_yaw_deg - confirmed_yaw_neg), 5.0, "Gaze target must stay within +-5 deg of confirmed heading")

    def test_regression_4_face_reacquisition_after_dropout_smoothly_resumes(self):
        """Face reacquisition after dropout smoothly resumes visual tracking."""
        tracker = GazeTracker(calibration=self.calib)
        t = 1000.0
        det = Detection(x=150, y=200, w=80, h=80, confidence=0.90)
        for _ in range(5):
            tracker.step(faces=[det], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=t)
            t += 0.033

        # Dropout for 8 frames
        for _ in range(8):
            tracker.step(faces=[], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=t)
            t += 0.033

        # Reacquisition
        res_reacquired = None
        for _ in range(3):
            res_reacquired = tracker.step(faces=[det], frame_size=(640, 480), doa_deg=None, measured_head_deg=None, timestamp=t)
            t += 0.033

        self.assertEqual(res_reacquired.owner, PrioritySource.VISUAL_TRACKING)
        self.assertEqual(res_reacquired.target_id, "person_1")
        self.assertAlmostEqual(res_reacquired.target_yaw_deg, 14.0, delta=3.0)

    def test_regression_5_respeaker_sector_hysteresis_55deg_oscillation(self):
        """54.5-55.5 deg DOA oscillation -> no LEFT/CENTER chatter."""
        localizer = ReSpeakerAudioLocalizer()
        t = 100.0
        # 1. Establish confirmed LEFT sector with DOA = 40°
        yaw = localizer.update(doa_raw=40.0, voice_activity=True, timestamp=t)
        t += 0.05
        self.assertEqual(localizer.confirmed_sector, "LEFT")
        self.assertEqual(yaw, 60.0)

        # 2. Oscillate across the nominal 55° boundary: 54.5°, 55.5°, 54.8°, 55.3°...
        oscillations = [54.5, 55.5, 54.8, 55.3, 54.6, 55.4, 54.7, 55.2]
        for doa in oscillations:
            yaw = localizer.update(doa_raw=doa, voice_activity=True, timestamp=t)
            t += 0.05
            self.assertEqual(
                localizer.confirmed_sector,
                "LEFT",
                f"Sector chattered to {localizer.confirmed_sector} at DOA {doa}° while in LEFT!",
            )
            self.assertEqual(yaw, 60.0)

        # 3. Test from CENTER sector
        localizer.reset()
        yaw = localizer.update(doa_raw=70.0, voice_activity=True, timestamp=t)
        t += 0.05
        self.assertEqual(localizer.confirmed_sector, "CENTER")
        self.assertEqual(yaw, 0.0)

        # Oscillate across 55° boundary: 55.2, 54.8, 55.4, 54.6...
        for doa in [55.2, 54.8, 55.4, 54.6, 55.1, 54.9]:
            yaw = localizer.update(doa_raw=doa, voice_activity=True, timestamp=t)
            t += 0.05
            self.assertEqual(
                localizer.confirmed_sector,
                "CENTER",
                f"Sector chattered to {localizer.confirmed_sector} at DOA {doa}° while in CENTER!",
            )
            self.assertEqual(yaw, 0.0)

    def test_regression_e2e_encoder_unavailable_fixed_pixel_no_runaway(self):
        """Regression test: Encoder unavailable (VIRTUAL_ENCODER), target remains at fixed camera bearing.

        End-to-end chain:
        camera detection -> camera bearing -> canonical head yaw -> target yaw -> head command -> virtual head update -> next camera frame.

        Even though head commands are accepted and virtual yaw advances from 0° towards target,
        repeated frames at a fixed camera bearing (e.g. +15°) MUST NOT cause target yaw to drift or
        run away to limits (+-75°) because camera bearing must never feedback into virtual yaw.
        """
        head_mgr = HeadStateManager(ticks_per_deg=2.5882, software_max_vel_deg_s=20.0)
        tracker = GazeTracker(calibration=self.calib)

        t = 1000.0
        # Detection at fixed pixel: x=147 (yields approx +15° bearing on 640x480)
        det = Detection(x=147, y=200, w=80, h=80, confidence=0.88)

        initial_target_yaw = None

        for frame_idx in range(50):
            # 1. Centrally evaluate HeadStateManager
            hstate = head_mgr.evaluate(timestamp=t)
            if frame_idx > 0:
                self.assertEqual(hstate.position_source, PositionSource.VIRTUAL_ENCODER)
            self.assertIsNone(hstate.actual_yaw_deg)
            self.assertTrue(math.isnan(hstate.position_deg))

            canonical_yaw = hstate.canonical_yaw_deg

            # 2. Step GazeTracker with canonical estimated head yaw
            res = tracker.step(
                faces=[det],
                frame_size=(640, 480),
                doa_deg=None,
                measured_head_deg=None,
                timestamp=t,
                estimated_head_deg=canonical_yaw,
            )

            if initial_target_yaw is None:
                initial_target_yaw = res.target_yaw_deg
                self.assertAlmostEqual(initial_target_yaw, 15.0, delta=2.5)

            # 3. Simulate command dispatch & acceptance by HeadStateManager
            head_mgr.on_command_accepted(res.target_yaw_deg, timestamp=t)

            # 4. Invariant: target_yaw must remain stable around initial_target_yaw (~15°)
            # It must NEVER drift or run away to +-75°
            self.assertAlmostEqual(
                res.target_yaw_deg,
                initial_target_yaw,
                delta=3.0,
                msg=f"Frame {frame_idx}: target_yaw drifted to {res.target_yaw_deg}°! (virtual yaw={canonical_yaw}°)",
            )
            self.assertLess(abs(res.target_yaw_deg), 30.0)

            t += 0.05  # 20 Hz frame rate

    def test_head_state_zero_jump_rebase_encoder_virtual_transitions(self):
        """Zero-jump rebase test between ENCODER and VIRTUAL_ENCODER authority modes."""
        head_mgr = HeadStateManager(ticks_per_deg=1.0, stale_timeout_s=0.50, software_max_vel_deg_s=20.0)
        t = 100.0

        # 1. Physical encoder active at 25.0° (25 ticks with 1 tick/deg)
        head_mgr.on_encoder_feedback(head_ticks=10, timestamp=t)
        t += 0.05
        head_mgr.on_encoder_feedback(head_ticks=25, timestamp=t)
        hstate = head_mgr.evaluate(timestamp=t)
        self.assertEqual(hstate.position_source, PositionSource.ENCODER)
        self.assertEqual(hstate.actual_yaw_deg, 25.0)
        self.assertEqual(hstate.canonical_yaw_deg, 25.0)

        # 2. Encoder dies (times out past stale_timeout_s = 0.50s)
        t += 0.60
        hstate = head_mgr.evaluate(timestamp=t)
        self.assertEqual(hstate.position_source, PositionSource.VIRTUAL_ENCODER)
        self.assertIsNone(hstate.actual_yaw_deg)
        # Invariant: Zero-jump rebase seeds virtual estimate with last known physical encoder angle
        self.assertEqual(hstate.estimated_yaw_deg, 25.0)
        self.assertEqual(hstate.canonical_yaw_deg, 25.0)

        # 3. In virtual mode, command to 45.0°
        head_mgr.on_command_accepted(45.0, timestamp=t)
        t += 0.50  # at 20 deg/s, advances by 10.0° to 35.0°
        hstate = head_mgr.evaluate(timestamp=t)
        self.assertEqual(hstate.position_source, PositionSource.VIRTUAL_ENCODER)
        self.assertAlmostEqual(hstate.canonical_yaw_deg, 35.0, delta=0.5)

        # 4. Encoder comes back online at 36.0°
        t += 0.05
        head_mgr.on_encoder_feedback(head_ticks=36, timestamp=t)
        hstate = head_mgr.evaluate(timestamp=t)
        self.assertEqual(hstate.position_source, PositionSource.ENCODER)
        self.assertEqual(hstate.actual_yaw_deg, 36.0)
        self.assertEqual(hstate.canonical_yaw_deg, 36.0)
        # Invariant: Commanded target is NOT overwritten by the encoder sample
        self.assertEqual(hstate.target_position_deg, 45.0)


if __name__ == "__main__":
    unittest.main()
