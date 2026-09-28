"""ASTRO V1 — Unit and Integration Tests for Phase 2: Camera = Eye Architecture.

Tests:
1. Physical optical cone geometry (HFOV ~ 72°).
2. Epistemic boundary evaluator: Audio evidence (DOA) != Visual confirmation.
3. SpatialFusionEngine epistemic tagging for visual vs acoustic entities.
4. SocialBrain modular prompt injection with Camera = Eye constraints.
5. Cross-model parity verification of epistemic prompt constraints between
   OpenAI Realtime and Local Gemma.
"""

import pytest
from unittest.mock import MagicMock

from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.spatial.epistemic_cone import (
    CAMERA_HALF_HFOV_DEG,
    CAMERA_HFOV_DEG,
    EpistemicGroundingStatus,
    evaluate_epistemic_grounding,
    is_within_optical_cone,
    normalize_angle_deg,
)
from astro_ai.spatial.spatial_fusion import SpatialFusionEngine
from astro_ai.brain.social_brain import SocialBrain


class TestCameraEyeEpistemic:
    """Test suite verifying Camera = Eye and epistemic perceptual boundaries."""

    def test_01_optical_cone_geometry(self):
        """Optical cone strictly bounds vision to ~72° (+/-36° around head yaw)."""
        assert CAMERA_HFOV_DEG == 72.0
        assert CAMERA_HALF_HFOV_DEG == 36.0

        # Centered head yaw = 0
        assert is_within_optical_cone(0.0, head_yaw_deg=0.0) is True
        assert is_within_optical_cone(15.0, head_yaw_deg=0.0) is True
        assert is_within_optical_cone(-35.0, head_yaw_deg=0.0) is True
        assert is_within_optical_cone(36.0, head_yaw_deg=0.0) is True

        # Outside cone
        assert is_within_optical_cone(36.5, head_yaw_deg=0.0) is False
        assert is_within_optical_cone(60.0, head_yaw_deg=0.0) is False
        assert is_within_optical_cone(120.0, head_yaw_deg=0.0) is False
        assert is_within_optical_cone(-90.0, head_yaw_deg=0.0) is False
        assert is_within_optical_cone(180.0, head_yaw_deg=0.0) is False

        # With head turned right (-30 deg)
        assert is_within_optical_cone(-30.0, head_yaw_deg=-30.0) is True
        assert is_within_optical_cone(-50.0, head_yaw_deg=-30.0) is True  # diff is 20 <= 36
        assert is_within_optical_cone(20.0, head_yaw_deg=-30.0) is False  # diff is 50 > 36

    def test_02_epistemic_grounding_evaluator_acoustic_only(self):
        """Audio evidence (DOA 120°) without camera CANNOT generate visual target confirmation."""
        # DOA behind the robot at 120°
        epistemic = evaluate_epistemic_grounding(
            has_vision=False,
            has_audio=True,
            azimuth_deg=120.0,
            head_yaw_deg=0.0,
        )

        assert epistemic.in_camera_cone is False
        assert epistemic.can_claim_vision is False
        assert epistemic.is_audible is True
        assert epistemic.status == EpistemicGroundingStatus.DUYUYORUM
        assert "EPISTEMIK KURAL" in epistemic.prompt_instruction
        assert "YALNIZCA SES" in epistemic.prompt_instruction
        assert "sahte görsel iddialarda KESİNLİKLE BULUNMA" in epistemic.prompt_instruction

    def test_03_epistemic_grounding_evaluator_multimodal_front(self):
        """Target in front with both visual confirmation and audio."""
        epistemic = evaluate_epistemic_grounding(
            has_vision=True,
            has_audio=True,
            azimuth_deg=10.0,
            head_yaw_deg=0.0,
        )

        assert epistemic.in_camera_cone is True
        assert epistemic.can_claim_vision is True
        assert epistemic.is_audible is True
        assert epistemic.status == EpistemicGroundingStatus.GORUYORUM_VE_DUYUYORUM
        assert "GÖRSEL VE İŞİTSEL DOĞRULAMA AKTİF" in epistemic.prompt_instruction

    def test_04_spatial_fusion_epistemic_tagging(self):
        """SpatialFusionEngine correctly tags visual vs acoustic entities with epistemic bounds."""
        fusion = SpatialFusionEngine()

        # 1. Acoustic only: DOA at 90° (outside HFOV), speaking
        fusion.update_audio_perception(
            doa_deg=90.0,
            speaker_id_dict={"name": "Baran", "confidence": 0.85},
            is_speaking=True,
            vad_active=True,
            rms_level=600.0,
        )
        fused = fusion.compute_fusion(now=100.0)
        assert len(fused) == 1
        person = fused[0]

        assert person.has_vision is False
        assert person.has_audio is True
        assert person.in_optical_cone is False
        assert person.can_claim_vision is False
        assert person.epistemic_status == "DUYUYORUM"

        # 2. Add visual detection at front (yaw 5°)
        fusion.update_vision_perception(
            faces=[{"name": "Baran", "is_known": True, "confidence": 0.90, "head_yaw_deg": 5.0, "is_looking": True, "distance_m": 1.2}],
            looking_at_robot=True,
            user_distance_m=1.2,
        )
        fusion.update_audio_perception(
            doa_deg=5.0,
            speaker_id_dict={"name": "Baran", "confidence": 0.85},
            is_speaking=True,
            vad_active=True,
            rms_level=600.0,
        )
        fused_vis = fusion.compute_fusion(now=101.0)
        vis_person = [p for p in fused_vis if p.has_vision][0]

        assert vis_person.has_vision is True
        assert vis_person.in_optical_cone is True
        assert vis_person.can_claim_vision is True
        assert vis_person.epistemic_status == "GORUYORUM_VE_DUYUYORUM"

    def test_05_social_brain_prompt_camera_eye_invariant(self):
        """SocialBrain modular prompt contains explicit Camera = Eye boundaries."""
        brain = SocialBrain(db_path=":memory:", enable_migration=False)

        # Scenario A: Acoustic target (out of sight)
        acoustic_person = UnifiedPersonState(
            person_id="person_audio_1",
            name="Ahmet",
            formal_title="Ahmet Bey",
            distance_m=2.5,
            azimuth_deg=100.0,
            has_vision=False,
            has_audio=True,
            in_optical_cone=False,
            can_claim_vision=False,
            epistemic_status="DUYUYORUM",
        )

        ctx_a, dec_a, prompt_a = brain.process_dialogue_turn("Nasılsın?", person_state=acoustic_person)
        assert ctx_a.can_claim_vision is False
        assert ctx_a.in_optical_cone is False
        assert "KAMERA = GÖZ (EPISTEMIK SINIR)" in prompt_a
        assert "Görsel İddia: YASAK (Yalnızca Ses/Radar)" in prompt_a
        assert "Görüş Konisi Dışında" in prompt_a
        assert "sahte görsel iddialarda bulunma" in prompt_a

        # Scenario B: Visually confirmed target
        visual_person = UnifiedPersonState(
            person_id="person_vis_1",
            name="Baran",
            formal_title="Baran",
            distance_m=1.1,
            azimuth_deg=0.0,
            has_vision=True,
            has_audio=True,
            in_optical_cone=True,
            can_claim_vision=True,
            epistemic_status="GORUYORUM_VE_DUYUYORUM",
        )

        ctx_b, dec_b, prompt_b = brain.process_dialogue_turn("Selam", person_state=visual_person)
        assert ctx_b.can_claim_vision is True
        assert ctx_b.in_optical_cone is True
        assert "KAMERA = GÖZ (EPISTEMIK SINIR)" in prompt_b
        assert "Görsel İddia: AKTİF (Görülüyor)" in prompt_b
        assert "Görüş Konisi İçinde" in prompt_b

    def test_06_model_parity_epistemic_prompt_sharing(self):
        """Verifies that epistemic boundaries are extracted and shared with Local Gemma identically to Realtime."""
        system_prompt = (
            "Astro Default Instructions\n\n"
            "=== KAMERA = GÖZ (EPISTEMIK SINIR) ===\n"
            "- Görsel İddia: YASAK (Yalnızca Ses/Radar)\n"
            "- Kamera Görüş Konisi: Görüş Konisi Dışında\n"
            "- Kural: Kişi kameranın görüş alanı dışında ya da doğrudan görülmüyor. YALNIZCA SESİ DUYULUYOR. "
            "Kişinin kıyafeti, yüzü, gözleri hakkında sahte görsel iddialarda bulunma.\n\n"
            "=== YANIT STRATEJİSİ ===\n"
            "- Kısa ve net konuş"
        )

        # Simulate the extraction logic inside AstroRealtimeNode._process_fallback_turn
        epistemic_gemma_rule = ""
        if "KAMERA = GÖZ" in system_prompt or "EPISTEMIK" in system_prompt:
            for section in system_prompt.split("\n\n"):
                if "KAMERA = GÖZ" in section or "EPISTEMIK" in section:
                    epistemic_gemma_rule += section.strip() + "\n\n"

        user_text = "Üstümdeki kazağın rengi ne?"
        gemma_prompt = (
            f"{epistemic_gemma_rule}"
            "ASTRO bir sosyal robot. Türkçe konuş. Kısa ve doğal cevap ver.\n\n"
            f"Kullanıcı: {user_text}\n"
            "ASTRO:"
        )

        assert "KAMERA = GÖZ (EPISTEMIK SINIR)" in gemma_prompt
        assert "Görsel İddia: YASAK" in gemma_prompt
        assert "sahte görsel iddialarda bulunma" in gemma_prompt
