#!/usr/bin/env python3
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "astro_ai")))

from state_machine import StateMachine, RobotState
from memory_manager import MemoryManager, PersistentProfile
from persona_engine import PersonaEngine, clean_tts_text, extract_spoken_turkish_sentence
from conversation_session import ConversationSession, LatencyTracker


class TestStateMachine(unittest.TestCase):
    def test_transitions(self):
        fsm = StateMachine(RobotState.IDLE)
        self.assertTrue(fsm.is_idle())

        transitions = []
        fsm.add_listener(lambda old, new: transitions.append((old, new)))

        self.assertTrue(fsm.transition_to(RobotState.LISTENING))
        self.assertTrue(fsm.is_listening())
        self.assertFalse(fsm.transition_to(RobotState.LISTENING))  # No-op

        self.assertTrue(fsm.transition_to(RobotState.THINKING))
        self.assertTrue(fsm.is_thinking())

        self.assertTrue(fsm.transition_to(RobotState.SPEAKING))
        self.assertTrue(fsm.is_speaking())

        self.assertTrue(fsm.transition_to(RobotState.INTERRUPTED))
        self.assertTrue(fsm.is_interrupted())

        self.assertEqual(len(transitions), 4)


class TestMemoryManager(unittest.TestCase):
    def test_3tier_memory(self):
        mem = MemoryManager(storage_path="/tmp/test_astro_memory.json")

        # Tier 1
        mem.episodic.add_message("user", "Merhaba")
        mem.episodic.add_message("assistant", "Selam!")
        self.assertEqual(len(mem.episodic.get_messages()), 2)

        # Tier 2
        mem.session.add_topic("Robotik Projeleri")
        self.assertIn("Robotik Projeleri", mem.session.get_summary())

        # Tier 3 - Gossip rejection
        self.assertFalse(mem.profile.add_verified_fact("İhsan Sezer seni aradı"))
        self.assertFalse(mem.profile.add_verified_fact("Reddicim onurdur"))
        self.assertTrue(mem.profile.add_verified_fact("Kullanıcı çay içmeyi seviyor."))

        # Context prompt
        prompt_ctx = mem.get_prompt_context()
        self.assertIn("Astro", prompt_ctx)
        self.assertIn("Baran", prompt_ctx)


class TestPersonaAndSession(unittest.TestCase):
    def test_persona_engine(self):
        engine = PersonaEngine("flirt")
        prompt = engine.build_system_prompt("Hafıza Bilgileri")
        self.assertIn("Astro", prompt)
        self.assertIn("çapkın", prompt)

        # TTS Cleaning
        cleaned = clean_tts_text("<think>reasoning</think> Merhaba dostum! 😄")
        self.assertEqual(cleaned, "Merhaba dostum!")

    def test_session_lifecycle(self):
        session = ConversationSession(base_timeout_s=0.1)
        session.activate_session()
        self.assertTrue(session.is_active)

        has_wake, clean = session.is_wake_word("Hey Astro nasılsın?")
        self.assertTrue(has_wake)
        self.assertEqual(clean, "nasılsın")


if __name__ == "__main__":
    unittest.main()
