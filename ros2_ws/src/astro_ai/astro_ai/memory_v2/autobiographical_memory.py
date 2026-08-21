"""ASTRO V1 — Autobiographical Memory Engine.

Stores and retrieves life experiences and developmental milestones that Astro personally experienced.
"""

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from astro_ai.contracts.memory_models import AutobiographicalEvent
from astro_ai.memory_v2.sqlite_storage import SQLiteMemoryStorage


class AutobiographicalMemory:
    """Manages the robot's personal narrative and lived history."""

    def __init__(self, storage: SQLiteMemoryStorage):
        self.storage = storage

    def record_experience(
        self,
        event_type: str,
        title: str,
        description: str,
        participants: Optional[List[str]] = None,
        location: str = "Ahlat / Bitlis",
        valence: float = 0.0,
        significance: float = 0.5,
    ) -> AutobiographicalEvent:
        event_id = f"auto_{uuid.uuid4().hex[:10]}"
        now = time.time()
        parts = participants or []

        evt = AutobiographicalEvent(
            event_id=event_id,
            event_type=event_type,
            title=title,
            description=description,
            participants=parts,
            location=location,
            timestamp=now,
            emotional_valence=valence,
            significance_score=significance,
        )

        self.storage.execute_write(
            """
            INSERT OR REPLACE INTO autobiographical_events (
                event_id, event_type, title, description, participants_json,
                location, timestamp, emotional_valence, significance_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evt.event_id, evt.event_type, evt.title, evt.description,
                json.dumps(evt.participants, ensure_ascii=False),
                evt.location, evt.timestamp, evt.emotional_valence,
                evt.significance_score,
            ),
        )
        return evt

    def get_memorable_events(self, limit: int = 5) -> List[AutobiographicalEvent]:
        rows = self.storage.execute_read(
            """
            SELECT * FROM autobiographical_events
            ORDER BY significance_score DESC, timestamp DESC LIMIT ?
            """,
            (limit,),
        )
        events = []
        for r in rows:
            events.append(
                AutobiographicalEvent(
                    event_id=r["event_id"],
                    event_type=r["event_type"],
                    title=r["title"],
                    description=r["description"],
                    participants=json.loads(r["participants_json"] or "[]"),
                    location=r["location"] or "",
                    timestamp=float(r["timestamp"]),
                    emotional_valence=float(r["emotional_valence"]),
                    significance_score=float(r["significance_score"]),
                )
            )
        return events
