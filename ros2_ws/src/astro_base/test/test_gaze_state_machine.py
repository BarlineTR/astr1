"""Unit tests for Social Gaze State Machine (FSM) and Priority Arbitration."""

import unittest
from astro_base.gaze.gaze_state_machine import SocialGazeFSM
from astro_base.gaze.types import (
    FusedTarget,
    GazeStateEnum,
    Modality,
    PrioritySource,
    TargetState,
    TrackingState,
)


class TestGazeStateMachine(unittest.TestCase):
    def setUp(self):
        self.fsm = SocialGazeFSM(
            deadband_deg=3.0,
            idle_return_timeout_s=20.0,
            min_attention_dwell_s=2.50,
            target_lost_timeout_s=1.0,
            idle_saccades_enabled=False,
        )

    def test_initial_state_idle(self):
        """Initial state without targets is IDLE at 0.0°."""
        cmd = self.fsm.update(TargetState(active_target=None), actual_head_yaw_deg=0.0, timestamp=1.0)
        self.assertEqual(cmd.gaze_state, GazeStateEnum.IDLE)
        self.assertEqual(cmd.target_yaw_deg, 0.0)
        self.assertEqual(cmd.priority_source, PrioritySource.IDLE)

    def test_audio_target_initiates_orienting_then_visual_acquire(self):
        """Acoustic target at 45° triggers ORIENTING when error is large (>15°), then VISUAL_ACQUIRE."""
        t = 1.0
        aud_target = FusedTarget(
            target_id="spk_1", modality=Modality.AUDIO, body_azimuth_deg=45.0,
            body_elevation_deg=0.0, distance_m=1.8, confidence=0.80,
            is_speaking=True, eye_contact=False, person_name=None, is_known=False,
            timestamp=t, tracking_state=TrackingState.TRACKING
        )

        # 1. Head is at 0°, target is at 45° (error = 45° > 15°) -> ORIENTING
        cmd1 = self.fsm.update(TargetState(active_target=aud_target), actual_head_yaw_deg=0.0, timestamp=t)
        self.assertEqual(cmd1.gaze_state, GazeStateEnum.ORIENTING)
        self.assertEqual(cmd1.target_yaw_deg, 45.0)
        self.assertEqual(cmd1.priority_source, PrioritySource.ACTIVE_SPEAKER)

        # 2. Head has rotated to 42° (error = 3° <= 15°) -> VISUAL_ACQUIRE
        t += 0.5
        cmd2 = self.fsm.update(TargetState(active_target=aud_target), actual_head_yaw_deg=42.0, timestamp=t)
        self.assertEqual(cmd2.gaze_state, GazeStateEnum.VISUAL_ACQUIRE)
        self.assertEqual(cmd2.target_yaw_deg, 45.0)

    def test_visual_target_triggers_tracking(self):
        """Visual target when aligned enters TRACKING state."""
        t = 1.0
        vis_target = FusedTarget(
            target_id="person_1", modality=Modality.FUSED, body_azimuth_deg=20.0,
            body_elevation_deg=0.0, distance_m=1.5, confidence=0.85,
            is_speaking=True, eye_contact=True, person_name="Alice", is_known=True,
            timestamp=t, tracking_state=TrackingState.TRACKING
        )

        cmd = self.fsm.update(TargetState(active_target=vis_target), actual_head_yaw_deg=18.0, timestamp=t)
        self.assertEqual(cmd.gaze_state, GazeStateEnum.TRACKING)
        self.assertEqual(cmd.target_yaw_deg, 20.0)

    def test_deadband_rejects_micro_jitter(self):
        """Small target changes (<3.0° deadband) do NOT update commanded angle."""
        t = 1.0
        target1 = FusedTarget(
            target_id="person_1", modality=Modality.FUSED, body_azimuth_deg=20.0,
            body_elevation_deg=0.0, distance_m=1.5, confidence=0.85,
            is_speaking=True, eye_contact=True, person_name="Alice", is_known=True,
            timestamp=t, tracking_state=TrackingState.TRACKING
        )
        cmd1 = self.fsm.update(TargetState(active_target=target1), actual_head_yaw_deg=20.0, timestamp=t)
        self.assertEqual(cmd1.target_yaw_deg, 20.0)

        # Micro-jitter: Target reports 21.2° (delta = 1.2° < 3.0° deadband)
        t += 0.1
        target2 = FusedTarget(
            target_id="person_1", modality=Modality.FUSED, body_azimuth_deg=21.2,
            body_elevation_deg=0.0, distance_m=1.5, confidence=0.85,
            is_speaking=True, eye_contact=True, person_name="Alice", is_known=True,
            timestamp=t, tracking_state=TrackingState.TRACKING
        )
        cmd2 = self.fsm.update(TargetState(active_target=target2), actual_head_yaw_deg=20.0, timestamp=t)
        # Commanded target must stay locked at 20.0°!
        self.assertEqual(cmd2.target_yaw_deg, 20.0)

    def test_safety_override_preempts_all_behaviors(self):
        """Safety lock immediately forces head to 0.0° and sets SAFETY priority."""
        t = 1.0
        target = FusedTarget(
            target_id="person_1", modality=Modality.FUSED, body_azimuth_deg=40.0,
            body_elevation_deg=0.0, distance_m=1.5, confidence=0.85,
            is_speaking=True, eye_contact=True, person_name="Alice", is_known=True,
            timestamp=t, tracking_state=TrackingState.TRACKING
        )

        self.fsm.set_safety_lock(True)
        cmd = self.fsm.update(TargetState(active_target=target), actual_head_yaw_deg=40.0, timestamp=t)
        self.assertEqual(cmd.priority_source, PrioritySource.SAFETY)
        self.assertEqual(cmd.target_yaw_deg, 0.0)

    def test_gesture_execution_sequence(self):
        """Tests sequential execution of a scripted nod gesture."""
        t = 1.0
        self.assertTrue(self.fsm.trigger_gesture("nod", timestamp=t))

        # First step of nod is +12.0°
        cmd1 = self.fsm.update(TargetState(active_target=None), actual_head_yaw_deg=0.0, timestamp=t)
        self.assertEqual(cmd1.priority_source, PrioritySource.GESTURE)
        self.assertEqual(cmd1.target_yaw_deg, 12.0)


if __name__ == "__main__":
    unittest.main()
