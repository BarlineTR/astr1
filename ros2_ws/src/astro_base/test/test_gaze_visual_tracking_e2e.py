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
import time
import unittest
from typing import List, Optional

from astro_base.gaze.attention_arbiter import AttentionArbiterCore
from astro_base.gaze.coordinate_frames import CalibrationConfig, CoordinateTransformer
from astro_base.gaze.gaze_runtime import GazeRuntimeCore
from astro_base.gaze.gaze_state_machine import SocialGazeFSM
from astro_base.gaze.head_controller import HeadControllerCore
from astro_base.gaze.head_state import HeadStateManager, PositionSource
from astro_base.gaze.motion_planner import MotionPlannerCore
from astro_base.gaze.sensor_fusion import AudioVisualFusionCore
from astro_base.gaze.target_manager import TargetManagerCore
from astro_base.gaze.gaze_tracker import Detection, GazeResult
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
        """When head is at +30° and person is centered (cam_az=0°), target_yaw stays at +30°."""
        now = 300.0
        # Head is turned to +30° (open-loop estimate)
        estimated_head = 30.0

        # Person is centered in camera (x=270, w=100 -> center_u=320 -> cam_azimuth = 0.0°)
        obs = self.perception.process_detection(
            x=270, y=190, w=100, h=100, depth_m=1.5,
            timestamp=now,
            actual_head_yaw_deg=None,
            estimated_head_yaw_deg=estimated_head,
            frame_width=640, frame_height=480,
            confidence=0.88,
        )
        self.assertEqual(obs.body_yaw_source, "ESTIMATED")
        self.assertAlmostEqual(obs.body_azimuth_deg, 30.0, places=0)

        tracks = self.tracker.update([obs], now, estimated_head_yaw_deg=estimated_head)
        self.assertAlmostEqual(tracks[0].body_azimuth_deg, 30.0, places=0)
        self.assertEqual(tracks[0].body_yaw_source, "ESTIMATED")

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
            timestamp=now, estimated_head_yaw_deg=40.0, confidence=0.85,
        )
        tracks = self.tracker.update([obs], now, estimated_head_yaw_deg=40.0)
        t_state = self.target_mgr.update(self.fusion.fuse(None, tracks, now), now)
        cmd = self.fsm.update(t_state, actual_head_yaw_deg=40.0, timestamp=now)
        self.assertEqual(cmd.gaze_state, GazeStateEnum.TRACKING)

        # 1. 0.1s with no detection: Target is NOT dropped, it enters COASTING mode
        now += 0.1
        tracks_coasting = self.tracker.update([], now, estimated_head_yaw_deg=40.0)
        t_state_coasting = self.target_mgr.update(self.fusion.fuse(None, tracks_coasting, now), now)
        self.assertIsNotNone(t_state_coasting.active_target)
        self.assertEqual(t_state_coasting.active_target.tracking_state, TrackingState.COASTING)

        # 2. After coasting timeout (2.5s > 2.0s): Track expires, TargetManager drops active target
        now += 2.5
        tracks_lost = self.tracker.update([], now, estimated_head_yaw_deg=40.0)
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
        """When encoder is absent, actual_yaw_deg is None and source is ESTIMATED."""
        state_mgr = HeadStateManager(ticks_per_deg=1.5)
        # Accept motor command to +35.0°
        state_mgr.on_command_accepted(35.0, timestamp=700.0)
        hstate = state_mgr.evaluate(timestamp=700.1)

        self.assertEqual(hstate.position_source, PositionSource.ESTIMATED)
        self.assertIsNone(hstate.actual_yaw_deg)
        self.assertIsNotNone(hstate.estimated_yaw_deg)

        # Verify perception correctly labels source as ESTIMATED
        obs = self.perception.process_detection(
            x=320, y=240, w=80, h=80, depth_m=1.5,
            timestamp=700.1,
            actual_head_yaw_deg=hstate.actual_yaw_deg,
            estimated_head_yaw_deg=hstate.estimated_yaw_deg,
        )
        self.assertEqual(obs.body_yaw_source, "ESTIMATED")

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


if __name__ == "__main__":
    unittest.main()
