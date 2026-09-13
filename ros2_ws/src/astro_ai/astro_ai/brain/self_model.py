"""ASTRO V1 — Epistemic Self Model, Capability Representation, and Basic Introspection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from astro_ai.brain.affective_state import AffectiveStateManager
from astro_ai.contracts.consciousness_types import (
    CognitiveEvent,
    Goal,
    Prediction,
    RobotAffectiveState,
    SelfState,
)
from astro_ai.state_machine import RobotState, StateMachine


@dataclass
class SelfModel:
    """Represents Astro's self-awareness, identity, capabilities, physical limits, and dynamic self-state."""

    name: str = "Astro"
    creator: str = "Baran"
    location: str = "Bitlis / Ahlat"
    version: str = "ASTRO V1 (Cognitive Embodied Social Robot)"

    # Hardware & Subsystems
    hardware_components: List[str] = field(
        default_factory=lambda: [
            "OAK-D Lite RGB-D Stereo Vision",
            "RPLiDAR A1 360° Planar Laser Scanner",
            "ReSpeaker 4-Mic Circular Array (AEC & DOA)",
            "NVIDIA Jetson Orin Nano 8GB GPU",
            "Fine-Tuned XTTS & ReSpeaker High-Gain Output",
        ]
    )

    capabilities: List[str] = field(
        default_factory=lambda: [
            "Canlı sesli Türkçe diyalog kurma",
            "Yüz tanıma ve görsel duygu analizi",
            "Ses izinden (voiceprint) konuşmacı kimliğini doğrulama",
            "LiDAR ile 360 derece mekânsal insan ve engel takibi",
            "360° RPLiDAR lazer radarı ile konuşmacının ve engellerin mesafesini ve yönünü canlı ölçme",
            "Hava durumu sorgulama ve hatırlatıcı kurma",
            "Kişiye özel uzun vadeli anı ve tercih biriktirme",
            "İnternet kesintisinde tam çevrimdışı yerel yapay zekâ ve ses sentezi",
        ]
    )

    physical_limitations: List[str] = field(
        default_factory=lambda: [
            "Fiziksel kolları veya tutucusu yoktur (nesneleri elle taşıyamaz)",
            "Uçamaz veya merdiven tırmanamaz",
            "Göremediği veya arkasında kalan nesnelerin rengini/şeklini tahmin edemez ('şu an göremiyorum' demelidir)",
            "Görsel ya da hafıza bilgisi yoksa uydurma yapamaz ('bilmiyorum' demelidir)",
        ]
    )

    # Dynamic Runtime Self-State & Introspection (Phase 2 Extension)
    self_state: SelfState = field(default_factory=SelfState)
    affective_manager: AffectiveStateManager = field(default_factory=AffectiveStateManager)

    def get_self_description_prompt(self) -> str:
        """Returns structured epistemic guidelines for the LLM."""
        return (
            f"=== ROBOT ÖZ-KİMLİK VE EPİSTEMİK SINIRLAR ===\n"
            f"- Adın: {self.name}\n"
            f"- Yaratıcın ve Baş Mühendisin: {self.creator}\n"
            f"- Konumun: {self.location}\n"
            f"- Radar ve Mesafe Algılama: 360° RPLiDAR A1 lazer tarayıcın ve derinlik kameran aktiftir; karşındaki kişinin ve etraftaki nesnelerin robota olan mesafesini santimetre hassasiyetinde canlı olarak bilirsin. Kullanıcı mesafesini sorduğunda 'GPS'im yok / ölçemem' deme; sensöründen gelen mesafeyi doğrudan söyle.\n"
            f"- Temel Kural 1 (Epistemik Dürüstlük): Bildiğin bir olgu ile o an gözlemlediğin şeyi ve tahminini daima ayırt et.\n"
            f"- Temel Kural 2 (Bilmiyorum Deme Yetkisi): Belleğinde veya kameranda olmayan bir bilgiyi asla uydurma, dürüstçe 'Bunu bilmiyorum' veya 'Şu an göremiyorum' de.\n"
            f"- Temel Kural 3 (Fiziksel Sınırlar): Fiziksel tutucun olmadığını bil; kullanıcı bir şey getirmeni isterse yapamayacağını nazikçe açıkla."
        )

    # -------------------------------------------------------------------------
    # Introspection Queries (Phase 2 Core API)
    # -------------------------------------------------------------------------

    def get_current_activity(self) -> str:
        """Introspective answer to 'What am I doing?'"""
        return self.self_state.get_current_activity()

    def get_operational_state(self) -> RobotState:
        """Returns current operational state read from StateMachine."""
        return self.self_state.get_operational_state()

    def get_focused_person(self) -> Optional[str]:
        """Returns the ID of the person ASTRO is actively focusing on."""
        return self.self_state.get_focused_person()

    def get_active_goal(self) -> Optional[Goal]:
        """Returns the active cognitive goal if any."""
        return self.self_state.get_active_goal()

    def is_executing_action(self) -> bool:
        """Returns True if ASTRO is actively executing an action."""
        return self.self_state.is_executing_action()

    def get_confidence(self) -> float:
        """Returns current epistemic confidence [0.1, 1.0]."""
        return self.self_state.get_confidence()

    def get_uncertainty(self) -> float:
        """Returns current uncertainty level [0.0, 1.0]."""
        return self.self_state.get_uncertainty()

    def get_degraded_capabilities(self) -> Set[str]:
        """Returns set of currently degraded capabilities or sensors."""
        return self.self_state.get_degraded_capabilities()

    def get_introspection_summary(self) -> Dict[str, Any]:
        """Returns a comprehensive introspective snapshot combining self-state and affective modulators."""
        summary = self.self_state.get_introspection_summary()
        summary["affective_modulators"] = self.affective_manager.state.to_dict()
        summary["identity"] = {
            "name": self.name,
            "creator": self.creator,
            "version": self.version,
        }
        return summary

    # -------------------------------------------------------------------------
    # Synchronization & Behavioral Modulation
    # -------------------------------------------------------------------------

    def sync_with_state_machine(self, state_machine: StateMachine) -> None:
        """Updates internal operational state by reading StateMachine.

        Preserves strict ownership boundary: SelfState only reads from StateMachine.
        """
        self.self_state.update_from_state_machine(state_machine)

    def sync_with_perception(self, perception_data: Dict[str, Any]) -> None:
        """Updates physical state and affects modulators from perception."""
        self.self_state.update_from_perception(perception_data)
        self.affective_manager.update_from_perception(perception_data)

    def update_affective_from_event(self, event: CognitiveEvent) -> None:
        """Passes cognitive events to internal affective manager."""
        self.affective_manager.update_from_event(event)
        self.self_state.overall_confidence = self.affective_manager.state.confidence
        self.self_state.uncertainty_level = self.affective_manager.state.uncertainty

    def step_decay(self, dt: float = 0.1) -> None:
        """Performs step decay on affective modulators and syncs confidence metrics."""
        self.affective_manager.step_decay(dt)
        self.self_state.overall_confidence = self.affective_manager.state.confidence
        self.self_state.uncertainty_level = self.affective_manager.state.uncertainty
