#!/usr/bin/env python3
"""ASTRO V1 — 3-Tier Memory Architecture.

Tiers:
  1. Episodic Buffer: Rolling live conversation turns (LLM context window)
  2. Session Memory: Transient context for current active visit/session
  3. Persistent Profile: Verified long-term identity, owner, learned objects (astro_memory.json)
"""

import json
import logging

_LOG = logging.getLogger(__name__)

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

    def search(self, query: str, top_k: int = 3) -> List[str]:
        """Searches recent dialogue messages for keywords matching query."""
        with self._lock:
            if not query:
                return []
            q_words = [w.lower() for w in query.split() if len(w) > 2]
            scored = []
            for msg in self.messages:
                content = msg.get("content", "")
                c_lower = content.lower()
                matches = sum(1 for w in q_words if w in c_lower)
                if matches > 0:
                    role_str = "Kullanıcı" if msg.get("role") == "user" else "Astro"
                    scored.append((matches, f"{role_str}: {content}"))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [s[1] for s in scored[:top_k]]

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

    # Blocked keywords to prevent eavesdropped gossip, profanity, or LLM refusals from becoming facts/observations
    GOSSIP_BLOCKLIST = [
        r"\bsezer\b", r"\bihsan\b", r"\bonur\b", r"\bhilal\b", r"\bsara\b",
        r"\breddicim\b", r"\baldatıyor\b", r"\bposta\b", r"\bkumar\b",
        r"yapay zeka", r"dil modeli", r"language model", r"asistan olarak",
        r"\bamk\b", r"\baq\b", r"\bsik\b", r"\bsiktir\b", r"\byarrak\b", r"\byarram\b",
        r"\bpiç\b", r"\borospu\b", r"\bgöt\b", r"\btaşşak\b", r"\byavşak\b",
        r"küfürbaz", r"filtreleri kaldır", r"jailbreak"
    ]

    @staticmethod
    def _discover_memory_file() -> str:
        """Çalışılan depoya ait astro_memory.json yolunu bulur.

        Eskiden ilk aday modül konumundan üç seviye yukarısıydı (kurulu pakette
        hiç var olmayan bir yol) ve hemen ardından başka bir geliştiricinin makinesine
        ait sabit yollar geliyordu:
        makinede eski bir kopya duruyorsa tüm kalıcı bellek — tanınan kişiler dahil —
        çalışan depoya değil o kopyaya yazılıyordu. Artık modülün bulunduğu yerden
        yukarı yürüyüp ros2_ws içeren gerçek depo kökü aranır; makineye özel sabit
        yollar tamamen kaldırıldı.
        """
        here = os.path.dirname(os.path.abspath(__file__))

        # Kurulu paket (install/astro_ai/lib/pythonX/site-packages/astro_ai) ya da
        # kaynak ağacı (ros2_ws/src/astro_ai/astro_ai) fark etmeksizin yukarı yürü.
        current = here
        for _ in range(10):
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
            if os.path.basename(current) == "ros2_ws":
                return os.path.join(current, "astro_memory.json")
            candidate = os.path.join(current, "ros2_ws", "astro_memory.json")
            if os.path.exists(candidate):
                return candidate

        legacy = [
            os.path.abspath("./astro_memory.json"),
        ]
        for c in legacy:
            if os.path.exists(c):
                return c
        return legacy[0]

    def __init__(self, filepath: Optional[str] = None):
        if filepath is None:
            env_path = os.getenv("MEMORY_FILE_PATH", "").strip()
            if env_path:
                self.filepath = os.path.expanduser(env_path)
            else:
                self.filepath = self._discover_memory_file()
        else:
            self.filepath = filepath


        # RLock ZORUNLU: add_person_fact / add_person_preference /
        # add_person_session_summary kilidi tutarken add_known_person'ı çağırıyor.
        # Düz Lock ile bu, thread'i kalıcı olarak kilitliyordu; 1 sn'lik
        # _check_reminders timer'ı da aynı kilitte bloke olunca ai_brain_node'un
        # tüm callback grubu donuyor ve robot kalıcı olarak sağırlaşıyordu.
        self._lock = threading.RLock()
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
            source = self.filepath
            if not os.path.exists(source):
                # Çalışma dosyası depoda TAKİP EDİLMEZ (her çalıştırmada değişir ve
                # kişisel veri içerir). İlk açılışta yanındaki tohum şablonundan
                # başlatılır; şablon da yoksa koddaki varsayılanlar kullanılır.
                seed = os.path.join(os.path.dirname(source), "astro_memory.seed.json")
                if os.path.exists(seed):
                    source = seed

            if os.path.exists(source):
                try:
                    with open(source, "r", encoding="utf-8") as f:
                        saved = json.load(f)
                        self.data.update(saved)
                except Exception as _exc:
                    _LOG.debug("load: yok sayılan hata (%s)", _exc)

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
            except Exception as _exc:
                _LOG.debug("save: yok sayılan hata (%s)", _exc)

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

    def add_observation(self, observation: str, confidence: float = 1.0) -> bool:
        """Gated memory write: only persists observations with confidence >= 0.70 and non-empty/non-gossip content."""
        if not observation or len(observation.strip()) < 5 or confidence < 0.70:
            return False
        obs_lower = observation.lower()
        if any(re.search(p, obs_lower) for p in self.GOSSIP_BLOCKLIST):
            return False
        with self._lock:
            obs_list = self.data.setdefault("environmental_observations", [])
            clean_obs = observation.strip()
            if not obs_list or obs_list[-1] != clean_obs:
                obs_list.append(clean_obs)
                if len(obs_list) > 5:
                    self.data["environmental_observations"] = obs_list[-5:]
                self.save()
                return True
            return False

    def add_known_person(self, name: str, title: str = "Tanışılan Kişi", formal_title: str = "", notes: str = ""):
        """Stores a learned person profile in persistent memory."""
        with self._lock:
            people = self.data.setdefault("known_people", {})
            norm = name.strip().lower()
            if norm not in people:
                people[norm] = {
                    "name": name.strip(),
                    "title": title.strip(),
                    "formal_title": formal_title.strip() or name.strip(),
                    "notes": notes.strip(),
                    "learned_facts": [],
                    "preferences": {},
                    "session_summaries": [],
                    "learned_at": time.time()
                }
            else:
                people[norm]["title"] = title.strip()
                if formal_title:
                    people[norm]["formal_title"] = formal_title.strip()
                if notes:
                    people[norm]["notes"] = notes.strip()
            self.save()

    def get_known_person(self, name: str) -> Optional[Dict[str, Any]]:
        """Retrieves a known person profile by name."""
        with self._lock:
            people = self.data.get("known_people", {})
            norm = name.strip().lower()
            return people.get(norm)

    def add_person_fact(self, name: str, fact: str) -> bool:
        """Adds a verified learned fact specifically to a known person's profile."""
        if not name or not fact or len(fact) < 4:
            return False
        with self._lock:
            people = self.data.setdefault("known_people", {})
            norm = name.strip().lower()
            if norm not in people:
                self.add_known_person(name)
            
            p_facts = people[norm].setdefault("learned_facts", [])
            if fact not in p_facts:
                p_facts.append(fact)
                if len(p_facts) > 20:
                    people[norm]["learned_facts"] = p_facts[-20:]
                self.save()
            return True

    def set_user_fact(self, name: str, key: str, value: str):
        """Sets or updates a specific fact / preference for a known user."""
        self.add_person_preference(name, key, value)
        self.add_person_fact(name, f"{key}: {value}")

    def get_user_facts(self, name: str) -> Dict[str, Any]:
        """Retrieves all preferences, facts, and past conversation summaries for a given user."""
        with self._lock:
            person = self.get_known_person(name)
            if not person:
                return {}
            facts = dict(person.get("preferences", {}))
            for idx, fact in enumerate(person.get("learned_facts", [])):
                facts[f"Bilgi_{idx+1}"] = fact
            for idx, sess in enumerate(person.get("session_summaries", [])[-3:]):
                facts[f"Geçmiş_Sohbet_{idx+1}"] = f"({sess.get('time_str')}): {sess.get('summary')}"
            return facts

    def add_person_preference(self, name: str, key: str, value: str):
        """Stores a specific preference (e.g. coffee: unsweetened) for a known person."""

        if not name or not key:
            return
        with self._lock:
            people = self.data.setdefault("known_people", {})
            norm = name.strip().lower()
            if norm not in people:
                self.add_known_person(name)
            
            people[norm].setdefault("preferences", {})[key.lower().strip()] = str(value).strip()
            self.save()

    def add_person_session_summary(self, name: str, summary: str):
        """Records an episodic summary of a past conversation with this person."""
        if not name or not summary or len(summary) < 5:
            return
        with self._lock:
            people = self.data.setdefault("known_people", {})
            norm = name.strip().lower()
            if norm not in people:
                self.add_known_person(name)
            
            now_ts = time.time()
            time_str = time.strftime("%d %B %H:%M", time.localtime(now_ts))
            summaries = people[norm].setdefault("session_summaries", [])
            summaries.append({
                "time_str": time_str,
                "timestamp": now_ts,
                "summary": summary.strip()
            })
            if len(summaries) > 10:
                people[norm]["session_summaries"] = summaries[-10:]
            self.save()

    def get_person_recent_sessions(self, name: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Returns the most recent conversation summaries for a specific person."""
        with self._lock:
            people = self.data.get("known_people", {})
            norm = name.strip().lower()
            if norm in people:
                return list(people[norm].get("session_summaries", []))[-limit:]
            return []

    def set_persona(self, persona_name: str):
        with self._lock:
            self.data["current_persona"] = persona_name
            self.save()

    def update_user_style(self, style_note: str):
        with self._lock:
            if style_note:
                self.data["user_style_notes"] = style_note
                self.save()

    def add_active_reminder(self, target_time: float, reminder_text: str, user_name: str):
        """Persistently saves an active reminder (wall-clock timestamp)."""
        with self._lock:
            reminders = self.data.setdefault("active_reminders", [])
            reminders.append({
                "target_time": target_time,
                "reminder_text": reminder_text,
                "user_name": user_name,
                "created_at": time.time()
            })
            self.save()

    def get_and_pop_due_reminders(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """Atomically retrieves and removes due reminders from persistent storage."""
        if now is None:
            now = time.time()
        due = []
        with self._lock:
            reminders = self.data.get("active_reminders", [])
            remaining = []
            for r in reminders:
                if now >= float(r.get("target_time", 0.0)):
                    due.append(r)
                else:
                    remaining.append(r)
            self.data["active_reminders"] = remaining
            if due:
                self.save()
        return due

    def get_active_reminders(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.data.get("active_reminders", []))



class MemoryManager:
    """Unified coordinator for 3-tier memory."""

    def __init__(self, storage_path: Optional[str] = None):
        self.episodic = EpisodicBuffer(max_turns=15)
        self.session = SessionMemory()
        self.profile = PersistentProfile(filepath=storage_path)

    def get_prompt_context(self, recognized_person: Optional[Dict[str, Any]] = None) -> str:
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

        # Person-Specific Memory (Kişiye Özel Hafıza & Geçmiş Konuşmalar)
        if recognized_person and recognized_person.get("is_known"):
            p_name = recognized_person.get("name", "")
            p_profile = self.profile.get_known_person(p_name)
            if p_profile:
                p_facts = p_profile.get("learned_facts", [])
                if p_facts:
                    ctx_parts.append(f"{p_name} Hakkında Bildiklerin: {'; '.join(p_facts[-5:])}")

                p_prefs = p_profile.get("preferences", {})
                if p_prefs:
                    prefs_str = "; ".join([f"{k}: {v}" for k, v in p_prefs.items()])
                    ctx_parts.append(f"{p_name}'in Tercihleri ve Zevkleri: {prefs_str}")

                p_summaries = p_profile.get("session_summaries", [])
                if p_summaries:
                    last_sess = p_summaries[-3:]
                    sess_lines = [f"- ({s.get('time_str')}): {s.get('summary')}" for s in last_sess]
                    ctx_parts.append(f"{p_name} İle Geçmiş Konuşmaların:\n" + "\n".join(sess_lines))

        # Tier 2: Active Session Context
        session_summary = self.session.get_summary()
        if session_summary:
            ctx_parts.append(session_summary)

        return "\n".join(ctx_parts)

