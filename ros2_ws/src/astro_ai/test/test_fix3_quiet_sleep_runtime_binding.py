"""Unit and integration tests for FIX 3: Quiet and Sleep Runtime State Binding.

Verifies:
1. /astro/quiet_mode topic sets authoritative node._is_quiet_mode and reflects in is_in_quiet_or_sleep_state().
2. /astro/sleep_mode topic triggers _go_to_sleep / _wake_up lifecycle transitions and state machine states.
3. Inactivity detection transitions to sleep mode via _go_to_sleep().
4. is_in_quiet_or_sleep_state() is dynamically consumed by _build_current_system_prompt() to trigger SocialBrain quiet overhearing awareness.
5. In quiet/sleep mode:
   - Direct address produces ENGAGED decision with should_speak=True and DOĞRUDAN HİTAP directive.
   - Ambient background conversation produces OBSERVING decision with should_speak=False and SESSİZ KAL directive.
"""

import time
import unittest
from unittest.mock import MagicMock, patch

try:
    from std_msgs.msg import Bool
except ImportError:
    class Bool:  # type: ignore
        def __init__(self, data: bool = False):
            self.data = data

from astro_ai.astro_realtime_node import AstroRealtimeNode
from astro_ai.brain.social_brain import SocialBrain
from astro_ai.contracts.quiet_awareness_types import QuietDecisionMode
from astro_ai.contracts.interaction_gate_types import InteractionGateMode
from astro_ai.state_machine import RobotState


class TestQuietSleepRuntimeBinding(unittest.TestCase):
    """Test suite for FIX 3: Quiet and Sleep Runtime State Binding."""

    def setUp(self):
        with patch.dict("os.environ", {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-test1234"}):
            self.node = AstroRealtimeNode(connect_realtime=False)
            self.node.social_brain = SocialBrain(db_path=":memory:", enable_migration=False)
            self.node._is_sleeping = False
            self.node._is_quiet_mode = False
            self.node.state_machine.transition_to(RobotState.LISTENING)

    def test_01_quiet_mode_ros_topic_binding(self):
        """Publishing to /astro/quiet_mode updates _is_quiet_mode and is_in_quiet_or_sleep_state()."""
        self.assertFalse(self.node.is_in_quiet_or_sleep_state())

        msg_true = Bool()
        msg_true.data = True
        self.node._on_quiet_mode(msg_true)
        self.assertTrue(self.node._is_quiet_mode)
        self.assertTrue(self.node.is_in_quiet_or_sleep_state())

        msg_false = Bool()
        msg_false.data = False
        self.node._on_quiet_mode(msg_false)
        self.assertFalse(self.node._is_quiet_mode)
        self.assertFalse(self.node.is_in_quiet_or_sleep_state())

    def test_02_sleep_mode_ros_topic_lifecycle(self):
        """Publishing to /astro/sleep_mode transitions robot into and out of sleep lifecycle."""
        # 1. Enter sleep via topic
        msg_sleep = Bool()
        msg_sleep.data = True
        self.node._on_sleep_mode(msg_sleep)
        self.assertTrue(self.node._is_sleeping)
        self.assertTrue(self.node.is_in_quiet_or_sleep_state())
        self.assertEqual(self.node.state_machine.current_state, RobotState.DEEP_IDLE)

        # 2. Wake up via topic
        msg_wake = Bool()
        msg_wake.data = False
        self.node._on_sleep_mode(msg_wake)
        self.assertFalse(self.node._is_sleeping)
        self.assertFalse(self.node.is_in_quiet_or_sleep_state())
        self.assertEqual(self.node.state_machine.current_state, RobotState.LISTENING)

    def test_03_inactivity_triggers_go_to_sleep(self):
        """Inactivity >= 15.0s triggers _go_to_sleep() and sets _is_sleeping."""
        now = time.monotonic()
        self.node._last_interaction_time = now - 20.0
        self.node._check_sleep_mode()
        self.assertTrue(self.node._is_sleeping)
        self.assertEqual(self.node.state_machine.current_state, RobotState.DEEP_IDLE)

    def test_04_system_prompt_consumes_runtime_quiet_state(self):
        """_build_current_system_prompt() feeds authoritative quiet state to SocialBrain."""
        self.node._is_quiet_mode = True
        self.node._last_user_transcript = "Ahmet projeyi tamamladın mı?"

        prompt = self.node._build_current_system_prompt()
        self.assertIsNotNone(self.node._last_social_decision)
        self.assertIsNotNone(self.node._last_social_context)
        # Decision must indicate OBSERVING with should_speak=False for ambient speech overheard during quiet mode
        self.assertFalse(self.node._last_social_decision.should_speak)
        self.assertEqual(self.node._last_social_decision.gate_mode, InteractionGateMode.OBSERVING.value)
        self.assertIn("SESSİZ KAL", self.node._last_social_context.quiet_awareness_directive)

    def test_05_quiet_mode_direct_address_triggers_engage(self):
        """In quiet mode, direct address ('Astro, bakar mısın') produces ENGAGED decision."""
        self.node._is_quiet_mode = True
        self.node._last_user_transcript = "Astro bakar mısın hava nasıl?"

        prompt = self.node._build_current_system_prompt()
        self.assertIsNotNone(self.node._last_social_decision)
        self.assertIsNotNone(self.node._last_social_context)
        self.assertTrue(self.node._last_social_decision.should_speak)
        self.assertEqual(self.node._last_social_decision.gate_mode, InteractionGateMode.ENGAGED.value)
        self.assertTrue(
            "DOĞRUDAN HİTAP" in self.node._last_social_context.quiet_awareness_directive
            or "DAHİL OL" in self.node._last_social_context.quiet_awareness_directive
        )


if __name__ == "__main__":
    unittest.main()
