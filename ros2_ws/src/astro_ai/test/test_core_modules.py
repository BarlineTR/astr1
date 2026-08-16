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
        engine_flirt = PersonaEngine("flirt")
        flirt_prompt = engine_flirt.build_system_prompt("Hafıza Bilgileri")
        self.assertIn("Astro", flirt_prompt)
        self.assertIn("çapkın", flirt_prompt)

        # Ensure playful mode does NOT contain generic flirt rule
        engine_playful = PersonaEngine("playful")
        playful_prompt = engine_playful.build_system_prompt()
        self.assertIn("sempatik", playful_prompt)
        self.assertNotIn("flörtöz", playful_prompt)
        self.assertNotIn("çapkın", playful_prompt)

        # TTS Cleaning
        cleaned = clean_tts_text("<think>reasoning</think> Merhaba dostum! 😄")
        self.assertEqual(cleaned, "Merhaba dostum!")

    def test_session_lifecycle_and_fuzzy_wake(self):
        session = ConversationSession(base_timeout_s=0.1)
        session.activate_session()
        self.assertTrue(session.is_active)

        # Exact wake word
        has_wake, clean = session.is_wake_word("Hey Astro nasılsın?")
        self.assertTrue(has_wake)
        self.assertEqual(clean, "nasılsın")

        # Fuzzy Turkish phonetic variations
        has_wake2, clean2 = session.is_wake_word("Hey astıro naber?")
        self.assertTrue(has_wake2)
        self.assertEqual(clean2, "naber")

        has_wake3, clean3 = session.is_wake_word("heyastro saat kaç?")
        self.assertTrue(has_wake3)
        self.assertEqual(clean3, "saat kaç")


class TestCircuitBreaker(unittest.TestCase):
    def test_circuit_transitions(self):
        from inference_engine import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout_s=0.1, name="TestCircuit")
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertTrue(cb.should_use_cloud())

        # 1st failure
        cb.record_failure("error 1")
        self.assertEqual(cb.state, CircuitState.CLOSED)

        # 2nd failure -> Trips to OPEN
        cb.record_failure("error 2")
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertFalse(cb.should_use_cloud())

        # Wait for recovery timeout
        import time
        time.sleep(0.15)
        # Next probe triggers HALF_OPEN
        self.assertTrue(cb.should_use_cloud())
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)

        # Successful probe recovers to CLOSED
        cb.record_success()
        self.assertEqual(cb.state, CircuitState.CLOSED)


if __name__ == "__main__":
    unittest.main()

