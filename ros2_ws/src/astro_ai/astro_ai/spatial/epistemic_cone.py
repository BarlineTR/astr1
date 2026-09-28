"""ASTRO V1 — Epistemic Optical Cone & Camera = Eye Grounding.

Enforces physical boundaries on robotic vision:
1. Physical Camera Horizontal Field of View (HFOV ~ 72.0 deg).
2. Epistemic Principle: Audio evidence (DOA) != Visual confirmation.
3. Strict rejection of visual claims for targets outside the optical cone
   or lacking camera verification.
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

CAMERA_HFOV_DEG: float = 72.0
CAMERA_HALF_HFOV_DEG: float = CAMERA_HFOV_DEG / 2.0  # 36.0 deg


class EpistemicGroundingStatus(str, Enum):
    """Epistemic status of a detected entity relative to camera and acoustics."""

    GORUYORUM_VE_DUYUYORUM = "GORUYORUM_VE_DUYUYORUM"
    GORUYORUM = "GORUYORUM"
    DUYUYORUM = "DUYUYORUM"
    RADARDA_HISSEDIYORUM = "RADARDA_HISSEDIYORUM"
    GORUS_ALANI_DISINDA = "GORUS_ALANI_DISINDA"
    BELIRSIZ = "BELIRSIZ"


@dataclass
class EpistemicGrounding:
    """Detailed epistemic sensory assessment for an entity."""

    status: EpistemicGroundingStatus
    in_camera_cone: bool
    can_claim_vision: bool
    is_audible: bool
    azimuth_rel_deg: float
    prompt_instruction: str


def normalize_angle_deg(angle_deg: float) -> float:
    """Normalizes angle to [-180, 180) degrees."""
    return (angle_deg + 180.0) % 360.0 - 180.0


def is_within_optical_cone(
    azimuth_deg: float,
    head_yaw_deg: float = 0.0,
    hfov_deg: float = CAMERA_HFOV_DEG,
) -> bool:
    """Determines whether a spatial angle lies within the camera's optical cone.

    Args:
        azimuth_deg: Target azimuth in robot coordinate frame (-180 to +180 deg, 0=front).
        head_yaw_deg: Current head yaw angle (-180 to +180 deg, 0=centered).
        hfov_deg: Horizontal Field of View of camera in degrees (default 72.0).

    Returns:
        True if the target is within the optical cone, False otherwise.
    """
    rel_angle = normalize_angle_deg(azimuth_deg - head_yaw_deg)
    half_cone = hfov_deg / 2.0
    return abs(rel_angle) <= half_cone


def evaluate_epistemic_grounding(
    has_vision: bool,
    has_audio: bool,
    azimuth_deg: Optional[float] = None,
    head_yaw_deg: float = 0.0,
    has_lidar: bool = False,
) -> EpistemicGrounding:
    """Evaluates epistemic visual & acoustic boundaries for an entity."""
    if azimuth_deg is not None:
        rel_az = normalize_angle_deg(azimuth_deg - head_yaw_deg)
        in_cone = abs(rel_az) <= CAMERA_HALF_HFOV_DEG
    else:
        rel_az = 0.0
        in_cone = True if has_vision else False

    # Epistemic invariant: can_claim_vision is ONLY True if camera actually detected target AND target is within cone.
    can_claim_vision = bool(has_vision and in_cone)

    if can_claim_vision and has_audio:
        status = EpistemicGroundingStatus.GORUYORUM_VE_DUYUYORUM
        prompt_instruction = (
            "GÖRSEL VE İŞİTSEL DOĞRULAMA AKTİF: Kişi kameranın görüş konisi içinde ve doğrudan görülüyor. "
            "Görsel ifadeler ('görüyorum', göz teması, kıyafet/ifade doğrulamaları) serbesttir."
        )
    elif can_claim_vision:
        status = EpistemicGroundingStatus.GORUYORUM
        prompt_instruction = (
            "GÖRSEL DOĞRULAMA AKTİF: Kişi doğrudan kameranın görüş konisi içinde görülüyor ('Görüyorum')."
        )
    elif has_audio:
        status = EpistemicGroundingStatus.DUYUYORUM
        prompt_instruction = (
            "EPISTEMIK KURAL — GÖRSEL KANIT YOK (YALNIZCA SES): Kişi kameranın görüş konisi dışında (yanında/arkanda) "
            "veya kamerada görünmüyor. YALNIZCA SESİ DUYULUYOR. Bu kişi hakkında 'görüyorum', 'kıyafetin mavi', 'gözlerin' "
            "gibi sahte görsel iddialarda KESİNLİKLE BULUNMA. Gerektiğinde 'Sesini duyuyorum ama şu an seni göremiyorum' gerçeğini belirt."
        )
    elif has_lidar:
        status = EpistemicGroundingStatus.RADARDA_HISSEDIYORUM
        prompt_instruction = (
            "EPISTEMIK KURAL — RADAR MESAFE BİLGİSİ: Kişi radarda tespit edildi ancak kamerada görünmüyor ve konuşmuyor. "
            "Görsel iddiada bulunma."
        )
    else:
        status = EpistemicGroundingStatus.BELIRSIZ
        prompt_instruction = "Görsel ve işitsel kanıt yok. Varsayımda bulunma."

    return EpistemicGrounding(
        status=status,
        in_camera_cone=in_cone,
        can_claim_vision=can_claim_vision,
        is_audible=bool(has_audio),
        azimuth_rel_deg=rel_az,
        prompt_instruction=prompt_instruction,
    )
