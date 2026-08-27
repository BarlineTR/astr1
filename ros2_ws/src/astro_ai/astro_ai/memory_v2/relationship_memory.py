"""ASTRO V1 — Relationship Memory and Social Tie Evolution Engine."""

import json
import time
from typing import Any, Dict, List, Optional

from astro_ai.contracts.intent_emotion_types import RelationshipRole
from astro_ai.memory_v2.sqlite_storage import SQLiteMemoryStorage


class RelationshipMemory:
    """Tracks evolving social bonds, familiarity, trust, and shared history per person."""

    def __init__(self, storage: SQLiteMemoryStorage):
        self.storage = storage

    def get_or_create_profile(self, name: str, formal_title: str = "") -> Dict[str, Any]:
        norm = name.strip().lower()
        rows = self.storage.execute_read(
            "SELECT * FROM relationship_profiles WHERE lower(name) = ?",
            (norm,),
        )
        now = time.time()
        if rows:
            r = rows[0]
            return {
                "person_id": r["person_id"],
                "name": r["name"],
                "formal_title": r["formal_title"] or r["name"],
                "role": RelationshipRole(r["role"]),
                "familiarity": float(r["familiarity"]),
                "trust": float(r["trust"]),
                "interaction_count": int(r["interaction_count"]),
                "first_seen": float(r["first_seen"]),
                "last_seen": float(r["last_seen"]),
                "preferred_tone": r["preferred_tone"] or "warm",
                "shared_topics": json.loads(r["shared_topics_json"] or "[]"),
                "notes": r["notes"] or "",
            }

        # Create new profile
        pid = f"rel_{norm.replace(' ', '_')}"
        role = RelationshipRole.CREATOR if norm == "baran" else RelationshipRole.NEW_USER
        fam = 1.0 if norm == "baran" else 0.10
        trust = 1.0 if norm == "baran" else 0.50

        self.storage.execute_write(
            """
            INSERT INTO relationship_profiles (
                person_id, name, formal_title, role, familiarity, trust,
                interaction_count, first_seen, last_seen, preferred_tone,
                shared_topics_json, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pid, name.strip(), formal_title.strip() or name.strip(),
                role.value, fam, trust, 1, now, now, "warm", "[]", "",
            ),
        )
        return {
            "person_id": pid,
            "name": name.strip(),
            "formal_title": formal_title.strip() or name.strip(),
            "role": role,
            "familiarity": fam,
            "trust": trust,
            "interaction_count": 1,
            "first_seen": now,
            "last_seen": now,
            "preferred_tone": "warm",
            "shared_topics": [],
            "notes": "",
        }

    def increment_interaction(self, name: str, topics: Optional[List[str]] = None):
        """Evolves familiarity and interaction frequency for a known person."""
        prof = self.get_or_create_profile(name)
        new_count = prof["interaction_count"] + 1
        now = time.time()

        # Evolve familiarity asymptotically towards 1.0
        new_fam = min(0.95, prof["familiarity"] + 0.05) if prof["name"].lower() != "baran" else 1.0

        # Evolve role
        role = prof["role"]
        if role == RelationshipRole.NEW_USER and new_count >= 3:
            role = RelationshipRole.REGULAR_GUEST
        if role == RelationshipRole.REGULAR_GUEST and new_count >= 8:
            role = RelationshipRole.FRIEND

        existing_topics = set(prof["shared_topics"])
        if topics:
            existing_topics.update(topics)

        self.storage.execute_write(
            """
            UPDATE relationship_profiles
            SET interaction_count = ?, familiarity = ?, role = ?, last_seen = ?, shared_topics_json = ?
            WHERE person_id = ?
            """,
            (
                new_count, new_fam, role.value, now,
                json.dumps(list(existing_topics), ensure_ascii=False),
                prof["person_id"],
            ),
        )

    def delete_profile(self, name: str) -> int:
        """Deletes relationship profile for right-to-be-forgotten requests."""
        return self.storage.execute_write(
            "DELETE FROM relationship_profiles WHERE lower(name) = ?",
            (name.strip().lower(),),
        )
