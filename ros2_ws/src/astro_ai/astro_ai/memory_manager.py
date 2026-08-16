#!/usr/bin/env python3
"""ASTRO V1 — 3-Tier Memory Architecture.

Tiers:
  1. Episodic Buffer: Rolling live conversation turns (LLM context window)
  2. Session Memory: Transient context for current active visit/session
  3. Persistent Profile: Verified long-term identity, owner, learned objects (astro_memory.json)
"""

import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional


class EpisodicBuffer:
    """Tier 1: Sliding window of recent dialogue messages."""

    def __init__(self, max_turns: int = 15):
        self.max_turns = max_turns
        self.messages: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def add_message(self, role: str, content: str):
        with self._lock:
            self.messages.append({"role": role, "content": content})
            if len(self.messages) > self.max_turns:
                self.messages = self.messages[-self.max_turns:]

    def get_messages(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.messages)

    def clear(self):
        with self._lock:
            self.messages.clear()


class SessionMemory:
    """Tier 2: Ephemeral session context (reset when session ends)."""

    def __init__(self):
        self.session_id: str = str(int(time.time()))
        self.start_time: float = time.monotonic()
        self.active_topics: List[str] = []
        self.session_entities: Dict[str, str] = {}
        self.turn_count: int = 0
        self._lock = threading.Lock()

    def record_turn(self, user_text: str, robot_text: str):
        with self._lock:
            self.turn_count += 1

    def add_topic(self, topic: str):
        with self._lock:
            if topic and topic not in self.active_topics:
                self.active_topics.append(topic)
                if len(self.active_topics) > 5:
                    self.active_topics = self.active_topics[-5:]

    def reset(self):
        with self._lock:
            self.session_id = str(int(time.time()))
            self.start_time = time.monotonic()
            self.active_topics.clear()
            self.session_entities.clear()
            self.turn_count = 0

    def get_summary(self) -> str:
        with self._lock:
            if not self.active_topics:
                return ""
            return f"Oturumda konuşulan konular: {', '.join(self.active_topics)}"


class PersistentProfile:
    """Tier 3: Strictly validated long-term profile storage (astro_memory.json)."""

    # Blocked keywords to prevent eavesdropped gossip from becoming facts
    GOSSIP_BLOCKLIST = [
        r"\bsezer\b", r"\bihsan\b", r"\bonur\b", r"\bhilal\b", r"\bsara\b",
        r"\breddicim\b", r"\baldatıyor\b", r"\bposta\b", r"\bkumar\b"
    ]

    def __init__(self, filepath: Optional[str] = None):
        if filepath is None:
            self.filepath = os.path.expanduser("~/Desktop/astr1/ros2_ws/astro_memory.json")
        else:
            self.filepath = filepath

        self._lock = threading.Lock()
        self.data: Dict[str, Any] = {
            "robot_name": "Astro",
            "owner_name": "Baran",
            "current_persona": "playful",
            "user_style_notes": "Samimi ve doğal Türkçe konuşur",
            "verified_facts": [
                "Senin adın Astro, sen akıllı, bağımsız ve interaktif bir sosyal robot asistansın.",
                "Robotun geliştiricisinin ve üreticisinin adı Baran.",
                "Robotik ve yazılımla ilgileniyor."
            ],
            "learned_objects": {},
            "environmental_observations": [],
            "last_interaction": None,
        }
        self.load()

    def load(self):
        with self._lock:
            if os.path.exists(self.filepath):
                try:
                    with open(self.filepath, "r", encoding="utf-8") as f:
                        saved = json.load(f)
                        self.data.update(saved)
                except Exception:
                    pass

            # Sanitize any polluted data
            self._sanitize()

    def _sanitize(self):
        # Guarantee core identity
        self.data["robot_name"] = "Astro"
        self.data["owner_name"] = "Baran"

        # Filter unverified gossip from verified_facts
        clean_facts = []
        for fact in self.data.get("verified_facts", []):
            fact_lower = str(fact).lower()
            if any(re.search(p, fact_lower) for p in self.GOSSIP_BLOCKLIST):
                continue
            clean_facts.append(fact)

        if not clean_facts:
            clean_facts = [
                "Senin adın Astro, sen akıllı, bağımsız ve interaktif bir sosyal robot asistansın.",
                "Robotun geliştiricisinin ve üreticisinin adı Baran."
            ]
        self.data["verified_facts"] = clean_facts
        self.save()

    def save(self):
        """Atomically persist data to disk using write-then-rename to prevent corruption."""
        tmp_path = self.filepath + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.filepath)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    def add_verified_fact(self, fact: str) -> bool:
        """Adds a fact only if it passes strict validation against hallucinations."""
        if not fact or len(fact) < 6:
            return False

        fact_lower = fact.lower()
        # Reject gossip / eavesdropping phrases
        if any(re.search(p, fact_lower) for p in self.GOSSIP_BLOCKLIST):
            return False

        with self._lock:
            if fact not in self.data["verified_facts"]:
                self.data["verified_facts"].append(fact)
                if len(self.data["verified_facts"]) > 25:
                    self.data["verified_facts"] = self.data["verified_facts"][-25:]
                self.save()
            return True

    def remove_facts_containing(self, keyword: str):
        """Removes facts matching a specific keyword (e.g. user says 'hafızandan sil')."""
        with self._lock:
            k = keyword.lower().strip()
            self.data["verified_facts"] = [
                f for f in self.data["verified_facts"] if k not in f.lower()
            ]
            self.save()

    def add_learned_object(self, obj_name: str, visual_desc: str):
        with self._lock:
            self.data.setdefault("learned_objects", {})[obj_name] = visual_desc
            self.save()

    def add_observation(self, observation: str):
        with self._lock:
            if observation:
                self.data.setdefault("environmental_observations", []).append(observation)
                if len(self.data["environmental_observations"]) > 3:
                    self.data["environmental_observations"] = self.data["environmental_observations"][-3:]
                self.save()

    def set_persona(self, persona_name: str):
        with self._lock:
            self.data["current_persona"] = persona_name
            self.save()

    def update_user_style(self, style_note: str):
        with self._lock:
            if style_note:
                self.data["user_style_notes"] = style_note
                self.save()


class MemoryManager:
    """Unified coordinator for 3-tier memory."""

    def __init__(self, storage_path: Optional[str] = None):
        self.episodic = EpisodicBuffer(max_turns=15)
        self.session = SessionMemory()
        self.profile = PersistentProfile(filepath=storage_path)

    def get_prompt_context(self) -> str:
        """Builds clean, structured context to inject into LLM system prompt."""
        ctx_parts = []

        # Tier 3: Verified Long-Term Profile
        owner = self.profile.data.get("owner_name", "Baran")
        ctx_parts.append(f"Geliştiricin ve Sahibin: {owner}")

        facts = self.profile.data.get("verified_facts", [])
        if facts:
            facts_str = "; ".join(facts[-5:])
            ctx_parts.append(f"Kalıcı Bilgilerin: {facts_str}")

        learned_objs = self.profile.data.get("learned_objects", {})
        if learned_objs:
            objs_str = "; ".join([f"{k}: {v}" for k, v in list(learned_objs.items())[-3:]])
            ctx_parts.append(f"Öğrendiğin Özel Eşyalar: {objs_str}")

        observations = self.profile.data.get("environmental_observations", [])
        if observations:
            obs_str = "; ".join(observations)
            ctx_parts.append(f"Çevresel Gözlemlerin: {obs_str}")

        # Tier 2: Active Session Context
        session_summary = self.session.get_summary()
        if session_summary:
            ctx_parts.append(session_summary)

        return "\n".join(ctx_parts)
