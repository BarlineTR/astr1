"""ASTRO V1 — Episodic Memory and Conversation Sessions."""

import json
import threading
import time
from typing import Any, Dict, List, Optional

from astro_ai.memory_v2.sqlite_storage import SQLiteMemoryStorage


class EpisodicMemoryV2:
    """Manages sliding window of live dialogue turns and archives past session summaries."""

    def __init__(self, storage: SQLiteMemoryStorage, max_turns: int = 15):
        self.storage = storage
        self.max_turns = max_turns
        self._lock = threading.RLock()
        self._live_turns: List[Dict[str, Any]] = []
        self._current_session_id = str(int(time.time()))
        self._session_start_time = time.time()

    def record_turn(self, role: str, content: str):
        with self._lock:
            self._live_turns.append({
                "role": role,
                "content": content,
                "timestamp": time.time(),
            })
            if len(self._live_turns) > self.max_turns:
                self._live_turns = self._live_turns[-self.max_turns:]

    def get_live_turns(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._live_turns)

    def archive_session(
        self,
        person_id: Optional[str],
        summary: str,
        topics: List[str],
        emotional_arc: str = "neutral",
    ):
        """Saves a completed interaction session into persistent storage."""
        now = time.time()
        with self._lock:
            turn_count = len(self._live_turns)
            self.storage.execute_write(
                """
                INSERT OR REPLACE INTO episodic_sessions (
                    session_id, person_id, start_time, end_time, turn_count,
                    summary, topics_json, emotional_arc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._current_session_id,
                    person_id or "unknown",
                    self._session_start_time,
                    now,
                    turn_count,
                    summary.strip(),
                    json.dumps(topics or [], ensure_ascii=False),
                    emotional_arc,
                ),
            )
            # Reset for next session
            self._current_session_id = str(int(time.time()))
            self._session_start_time = time.time()
            self._live_turns.clear()

    def get_recent_sessions_for_person(self, person_id: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Retrieves past conversation summaries for a specific person."""
        rows = self.storage.execute_read(
            """
            SELECT * FROM episodic_sessions
            WHERE person_id = ?
            ORDER BY end_time DESC LIMIT ?
            """,
            (person_id, limit),
        )
        results = []
        for r in rows:
            results.append({
                "session_id": r["session_id"],
                "summary": r["summary"],
                "topics": json.loads(r["topics_json"] or "[]"),
                "end_time": float(r["end_time"] or 0.0),
            })
        return results

    def clear(self):
        with self._lock:
            self._live_turns.clear()
