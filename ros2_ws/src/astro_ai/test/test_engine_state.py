#!/usr/bin/env python3
"""ASTRO V1 — Ses motoru bağlantı durumu birim testleri."""

import os
import sys
import unittest

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))

from astro_ai.realtime.engine_state import EngineState, EngineStateTracker


class TestEngineStateTracker(unittest.TestCase):
    def test_starts_realtime_primary(self):
        self.assertEqual(EngineStateTracker().state, EngineState.REALTIME_PRIMARY)

    def test_all_pairwise_transitions_allowed(self):
        for src in EngineState:
            for dst in EngineState:
                if src == dst:
                    continue
                t = EngineStateTracker()
                t.state = src
                self.assertTrue(t.transition_to(dst), f"{src} -> {dst} reddedildi")
                self.assertEqual(t.state, dst)

    def test_self_transition_is_noop_and_returns_false(self):
        t = EngineStateTracker()
        self.assertFalse(t.transition_to(EngineState.REALTIME_PRIMARY))
        self.assertEqual(t.state, EngineState.REALTIME_PRIMARY)


class TestSeparationFromTurnMachine(unittest.TestCase):
    """İki durum makinesi asla karışmaz — yapısal garanti."""

    def test_engine_state_module_does_not_import_turn_machine(self):
        import astro_ai.realtime.engine_state as mod
        with open(mod.__file__, "r", encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("turn_machine", source)

    def test_turn_machine_module_does_not_import_engine_state(self):
        import astro_ai.realtime.turn_machine as mod
        with open(mod.__file__, "r", encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("engine_state", source)

    def test_state_names_do_not_overlap(self):
        from astro_ai.realtime.turn_machine import TurnState
        self.assertEqual(
            {s.value for s in EngineState} & {s.value for s in TurnState},
            set(),
        )


if __name__ == "__main__":
    unittest.main()
