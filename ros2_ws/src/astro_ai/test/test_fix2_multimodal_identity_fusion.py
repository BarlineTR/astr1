"""Unit tests for FIX 2: Multimodal Identity Fusion and Cross-Modal Conflict Resolution.

Verifies that AstroRealtimeNode.resolve_identities():
1. Uses AttentionManager.evaluate_identity_certainty rather than sequential speaker-first cascade.
2. Resolves voice-only verified evidence to KNOWN with bio_source="voice".
3. Resolves face-only verified evidence to KNOWN with bio_source="face".
4. Resolves multimodal agreement (face == voice) to KNOWN with bio_source="fused_multimodal".
5. Detects cross-modal conflict (face != voice) as AMBIGUOUS, strictly setting user_name="Misafir" and is_known=False.
6. Suppresses stale visual evidence beyond TTL so expired faces do not create spurious conflicts.
7. Gracefully falls back to session hold or persistent memory when biometrics are UNKNOWN.
"""

import time
import unittest
from unittest.mock import MagicMock, patch

from astro_ai.astro_realtime_node import AstroRealtimeNode
from astro_ai.contracts.interaction_gate_types import IdentityCertainty


class TestMultimodalIdentityFusion(unittest.TestCase):
    """Test suite for FIX 2: Multimodal Identity Fusion in AstroRealtimeNode."""

    def setUp(self):
        with patch.dict("os.environ", {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-test1234"}):
            self.node = AstroRealtimeNode(connect_realtime=False)
            self.node.memory = MagicMock()
            self.node.memory.profile.data = {"owner_name": "Baran"}

    def test_voice_only_verified_identity(self):
        """High-confidence voice recognition alone resolves to KNOWN identity."""
        now = time.monotonic()
        self.node._recognized_speaker = {
            "name": "Baran",
            "confidence": 0.75,
            "is_known": True,
        }
        self.node._recognized_person = {}

        ident = self.node.resolve_identities()
        self.assertEqual(ident["biometric_identity"], "Baran")
        self.assertEqual(ident["biometric_status"], "verified")
        self.assertEqual(ident["biometric_source"], "voice")
        self.assertEqual(ident["session_identity"], "Baran")
        self.assertTrue(ident["is_known"])
        self.assertEqual(ident["identity_certainty"], IdentityCertainty.KNOWN.value)

    def test_face_only_verified_identity(self):
        """Fresh high-confidence face recognition alone resolves to KNOWN identity."""
        now = time.monotonic()
        self.node._last_vision_faces_time = now
        self.node._recognized_person = {
            "name": "Baran",
            "confidence": 0.85,
            "is_known": True,
        }
        self.node._recognized_speaker = {}

        ident = self.node.resolve_identities()
        self.assertEqual(ident["biometric_identity"], "Baran")
        self.assertEqual(ident["biometric_status"], "verified")
        self.assertEqual(ident["biometric_source"], "face")
        self.assertEqual(ident["session_identity"], "Baran")
        self.assertTrue(ident["is_known"])
        self.assertEqual(ident["identity_certainty"], IdentityCertainty.KNOWN.value)

    def test_multimodal_agreement_fused(self):
        """When face and voice agree on identity, bio_source becomes fused_multimodal."""
        now = time.monotonic()
        self.node._last_vision_faces_time = now
        self.node._recognized_person = {
            "name": "Baran",
            "confidence": 0.80,
            "is_known": True,
        }
        self.node._recognized_speaker = {
            "name": "Baran",
            "confidence": 0.75,
            "is_known": True,
        }

        ident = self.node.resolve_identities()
        self.assertEqual(ident["biometric_identity"], "Baran")
        self.assertEqual(ident["biometric_status"], "verified")
        self.assertEqual(ident["biometric_source"], "fused_multimodal")
        self.assertEqual(ident["session_identity"], "Baran")
        self.assertTrue(ident["is_known"])
        self.assertEqual(ident["identity_certainty"], IdentityCertainty.KNOWN.value)

    def test_cross_modal_conflict_forces_ambiguous_and_guest(self):
        """When fresh face and voice disagree, resolution must be AMBIGUOUS and force guest fallback."""
        now = time.monotonic()
        self.node._last_vision_faces_time = now
        self.node._recognized_person = {
            "name": "Baran",
            "confidence": 0.85,
            "is_known": True,
        }
        self.node._recognized_speaker = {
            "name": "Can",
            "confidence": 0.80,
            "is_known": True,
        }
        # Even if there was an active hold on Baran, conflict MUST strictly override
        self.node._active_person_name = "Baran"
        self.node._person_hold_until = now + 30.0

        ident = self.node.resolve_identities()
        self.assertEqual(ident["biometric_identity"], "ambiguous_conflict")
        self.assertEqual(ident["biometric_status"], "ambiguous")
        self.assertEqual(ident["biometric_source"], "conflict")
        self.assertEqual(ident["session_identity"], "Misafir")
        self.assertFalse(ident["is_known"])
        self.assertEqual(ident["identity_source"], "biometric_conflict_guest")
        self.assertEqual(ident["identity_certainty"], IdentityCertainty.AMBIGUOUS.value)

    def test_stale_face_does_not_conflict_with_voice(self):
        """Expired face observation (>2.5s) is disregarded; fresh voice alone resolves cleanly."""
        now = time.monotonic()
        # Face is 5.0 seconds old (expired beyond 2.5s TTL)
        self.node._last_vision_faces_time = now - 5.0
        self.node._recognized_person = {
            "name": "Baran",
            "confidence": 0.90,
            "is_known": True,
        }
        # Voice is current
        self.node._recognized_speaker = {
            "name": "Can",
            "confidence": 0.85,
            "is_known": True,
        }

        ident = self.node.resolve_identities()
        self.assertEqual(ident["biometric_identity"], "Can")
        self.assertEqual(ident["biometric_status"], "verified")
        self.assertEqual(ident["biometric_source"], "voice")
        self.assertEqual(ident["session_identity"], "Can")
        self.assertTrue(ident["is_known"])
        self.assertEqual(ident["identity_certainty"], IdentityCertainty.KNOWN.value)

    def test_unknown_biometrics_falls_back_to_hold_or_persistent_owner(self):
        """Low confidence biometrics produce UNKNOWN and rely on active hold or memory."""
        now = time.monotonic()
        self.node._last_vision_faces_time = now
        self.node._recognized_person = {
            "name": "Baran",
            "confidence": 0.20,
            "is_known": False,
        }
        self.node._recognized_speaker = {
            "name": "Baran",
            "confidence": 0.25,
            "is_known": False,
        }

        # Subcase A: Active hold present
        self.node._active_person_name = "Oktay"
        self.node._person_hold_until = now + 15.0

        ident = self.node.resolve_identities()
        self.assertEqual(ident["biometric_identity"], "unknown")
        self.assertEqual(ident["biometric_status"], "session_active")
        self.assertEqual(ident["session_identity"], "Oktay")
        self.assertTrue(ident["is_known"])
        self.assertEqual(ident["identity_source"], "session_hold")

        # Subcase B: No active hold -> falls back to persistent owner
        self.node._active_person_name = ""
        self.node._person_hold_until = 0.0

        ident2 = self.node.resolve_identities()
        self.assertEqual(ident2["biometric_identity"], "unknown")
        self.assertEqual(ident2["biometric_status"], "unknown")
        self.assertEqual(ident2["session_identity"], "Baran")
        self.assertTrue(ident2["is_known"])
        self.assertEqual(ident2["identity_source"], "persistent_memory")


if __name__ == "__main__":
    unittest.main()
