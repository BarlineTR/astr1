#!/usr/bin/env python3
"""ASTRO V1 — TurnMachine birim testleri (ROS'suz, donanımsız)."""

import os
import sys
import unittest

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))

from astro_ai.realtime.turn_machine import Action, TurnMachine, TurnState


class TestHappyPath(unittest.TestCase):
    def setUp(self):
        self.m = TurnMachine()

    def test_starts_idle(self):
        self.assertEqual(self.m.state, TurnState.IDLE)
        self.assertIsNone(self.m.active_response_id)
        self.assertEqual(self.m.generation_id, 0)

    def test_full_turn_cycle(self):
        self.assertEqual(self.m.on_event("input_audio_buffer.speech_started"), [])
        self.assertEqual(self.m.state, TurnState.USER_SPEAKING)

        self.assertEqual(self.m.on_event("input_audio_buffer.speech_stopped"), [])
        self.assertEqual(self.m.state, TurnState.RESPONSE_PENDING)

        self.assertEqual(self.m.on_event("response.created", "resp_1"), [])
        self.assertEqual(self.m.state, TurnState.RESPONSE_STREAMING)
        self.assertEqual(self.m.active_response_id, "resp_1")
        self.assertEqual(self.m.generation_id, 1)

        self.assertEqual(
            self.m.on_event("response.output_audio.delta", "resp_1"),
            [Action.PUBLISH_AUDIO],
        )

        self.assertEqual(self.m.on_event("response.done", "resp_1"), [])
        self.assertEqual(self.m.state, TurnState.IDLE)
        self.assertIsNone(self.m.active_response_id)

    def test_generation_id_increments_per_response(self):
        for expected in (1, 2, 3):
            self.m.on_event("input_audio_buffer.speech_started")
            self.m.on_event("input_audio_buffer.speech_stopped")
            self.m.on_event("response.created", f"resp_{expected}")
            self.assertEqual(self.m.generation_id, expected)
            self.m.on_event("response.done")


class TestGenerationIsolation(unittest.TestCase):
    def setUp(self):
        self.m = TurnMachine()
        self.m.on_event("input_audio_buffer.speech_started")
        self.m.on_event("input_audio_buffer.speech_stopped")
        self.m.on_event("response.created", "resp_new")

    def test_stale_generation_audio_is_dropped(self):
        self.assertEqual(
            self.m.on_event("response.output_audio.delta", "resp_old"),
            [Action.DROP_AUDIO],
        )

    def test_audio_after_done_is_dropped(self):
        self.m.on_event("response.done")
        self.assertEqual(
            self.m.on_event("response.output_audio.delta", "resp_new"),
            [Action.DROP_AUDIO],
        )

    def test_should_publish_audio_false_without_active_response(self):
        self.m.on_event("response.done")
        self.assertFalse(self.m.should_publish_audio("resp_new"))


class TestCancelGuard(unittest.TestCase):
    """response_cancel_not_active = 0 kriterinin kanıtı."""

    def test_cancel_forbidden_when_idle(self):
        m = TurnMachine()
        self.assertFalse(m.may_send_cancel())

    def test_cancel_forbidden_while_user_speaking(self):
        m = TurnMachine()
        m.on_event("input_audio_buffer.speech_started")
        self.assertFalse(m.may_send_cancel())

    def test_cancel_forbidden_in_response_pending(self):
        """Sunucu henüz response.created göndermedi — iptal edilecek response yok."""
        m = TurnMachine()
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        self.assertEqual(m.state, TurnState.RESPONSE_PENDING)
        self.assertIsNone(m.active_response_id)
        self.assertFalse(m.may_send_cancel())

    def test_cancel_allowed_while_streaming(self):
        m = TurnMachine()
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        m.on_event("response.created", "resp_1")
        self.assertTrue(m.may_send_cancel())

    def test_cancel_forbidden_after_done(self):
        m = TurnMachine()
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        m.on_event("response.created", "resp_1")
        m.on_event("response.done")
        self.assertFalse(m.may_send_cancel())


class TestBargeIn(unittest.TestCase):
    def test_server_side_barge_in_stops_playback_without_cancel(self):
        """interrupt_response=true varsayılanı: sunucu keser, istemci yalnızca çalmayı durdurur."""
        m = TurnMachine(client_side_cancel=False)
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        m.on_event("response.created", "resp_1")

        actions = m.on_event("input_audio_buffer.speech_started")
        self.assertEqual(actions, [Action.STOP_PLAYBACK])
        self.assertEqual(m.state, TurnState.RESPONSE_CANCELLING)

    def test_client_side_barge_in_also_sends_cancel(self):
        """REALTIME_INTERRUPT_RESPONSE=false yedek yolu."""
        m = TurnMachine(client_side_cancel=True)
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        m.on_event("response.created", "resp_1")

        actions = m.on_event("input_audio_buffer.speech_started")
        self.assertEqual(actions, [Action.STOP_PLAYBACK, Action.SEND_CANCEL])

    def test_barge_in_during_response_pending_sends_no_cancel(self):
        """RESPONSE_PENDING'de active_response_id None — SEND_CANCEL üretilmemeli."""
        m = TurnMachine(client_side_cancel=True)
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")

        actions = m.on_event("input_audio_buffer.speech_started")
        self.assertEqual(actions, [Action.STOP_PLAYBACK])
        self.assertNotIn(Action.SEND_CANCEL, actions)
        self.assertEqual(m.state, TurnState.RESPONSE_CANCELLING)

    def test_response_created_while_cancelling_binds_id_and_may_cancel(self):
        m = TurnMachine(client_side_cancel=True)
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        m.on_event("input_audio_buffer.speech_started")

        actions = m.on_event("response.created", "resp_late")
        self.assertEqual(m.state, TurnState.RESPONSE_CANCELLING)
        self.assertEqual(m.active_response_id, "resp_late")
        self.assertEqual(actions, [Action.SEND_CANCEL])

    def test_audio_during_cancelling_is_dropped(self):
        m = TurnMachine()
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        m.on_event("response.created", "resp_1")
        m.on_event("input_audio_buffer.speech_started")

        self.assertEqual(
            m.on_event("response.output_audio.delta", "resp_1"),
            [Action.DROP_AUDIO],
        )

    def test_cancelling_returns_to_idle_on_done(self):
        m = TurnMachine()
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        m.on_event("response.created", "resp_1")
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("response.done")
        self.assertEqual(m.state, TurnState.IDLE)
        self.assertIsNone(m.active_response_id)


class TestToolFlow(unittest.TestCase):
    def test_tool_call_cycle(self):
        m = TurnMachine()
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        m.on_event("response.created", "resp_1")

        m.on_event("response.function_call_arguments.done")
        self.assertEqual(m.state, TurnState.TOOL_EXECUTING)

        m.on_event("response.done")
        self.assertEqual(m.state, TurnState.TOOL_EXECUTING)
        self.assertIsNone(m.active_response_id)

        m.on_event("tool_result_sent")
        self.assertEqual(m.state, TurnState.RESPONSE_PENDING)

        m.on_event("response.created", "resp_2")
        self.assertEqual(m.state, TurnState.RESPONSE_STREAMING)
        self.assertEqual(m.generation_id, 2)


class TestInvalidTransitions(unittest.TestCase):
    """Tabloda olmayan her (durum, olay) çifti IGNORE döndürür, durum değişmez."""

    def test_speech_stopped_while_idle_ignored(self):
        m = TurnMachine()
        self.assertEqual(m.on_event("input_audio_buffer.speech_stopped"), [Action.IGNORE])
        self.assertEqual(m.state, TurnState.IDLE)

    def test_response_created_while_idle_ignored(self):
        m = TurnMachine()
        self.assertEqual(m.on_event("response.created", "resp_x"), [Action.IGNORE])
        self.assertEqual(m.state, TurnState.IDLE)
        self.assertIsNone(m.active_response_id)

    def test_unknown_event_ignored(self):
        m = TurnMachine()
        self.assertEqual(m.on_event("some.unknown.event"), [Action.IGNORE])
        self.assertEqual(m.state, TurnState.IDLE)

    def test_tool_result_while_idle_ignored(self):
        m = TurnMachine()
        self.assertEqual(m.on_event("tool_result_sent"), [Action.IGNORE])
        self.assertEqual(m.state, TurnState.IDLE)


class TestNeverCreatesResponse(unittest.TestCase):
    """conversation_already_has_active_response = 0 kriterinin kanıtı."""

    def test_no_action_ever_means_create_response(self):
        valid = {
            Action.PUBLISH_AUDIO,
            Action.DROP_AUDIO,
            Action.STOP_PLAYBACK,
            Action.SEND_CANCEL,
            Action.IGNORE,
        }
        self.assertEqual(set(Action), valid)

    def test_full_cycle_emits_no_creation_action(self):
        m = TurnMachine(client_side_cancel=True)
        seen = []
        for ev, rid in [
            ("input_audio_buffer.speech_started", None),
            ("input_audio_buffer.speech_stopped", None),
            ("response.created", "r1"),
            ("response.output_audio.delta", "r1"),
            ("input_audio_buffer.speech_started", None),
            ("response.done", None),
        ]:
            seen.extend(m.on_event(ev, rid))
        self.assertTrue(all(a in set(Action) for a in seen))


if __name__ == "__main__":
    unittest.main()
