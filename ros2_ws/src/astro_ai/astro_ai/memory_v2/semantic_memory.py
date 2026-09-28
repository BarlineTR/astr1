"""ASTRO V1 — Semantic Memory and Verified Knowledge Base."""

import re
import time
import uuid
from typing import Any, Dict, List, Optional

from astro_ai.contracts.intent_emotion_types import MemorySourceType
from astro_ai.contracts.memory_models import MemoryRecord, MemoryType
from astro_ai.memory_v2.confidence_engine import ConfidenceEngine
from astro_ai.memory_v2.contradiction_engine import ContradictionEngine
from astro_ai.memory_v2.sqlite_storage import SQLiteMemoryStorage


class SemanticMemory:
    """Manages verified facts, user preferences, and semantic world knowledge."""

    GOSSIP_PATTERNS = [
        r"\bsezer\b", r"\bihsan\b", r"\bonur\b", r"\bhilal\b", r"\bsara\b",
        r"\breddicim\b", r"\baldatıyor\b", r"\bposta\b", r"\bkumar\b"
    ]

    def __init__(self, storage: SQLiteMemoryStorage):
        self.storage = storage
        self.contradiction_engine = ContradictionEngine(storage)

    def is_gossip(self, text: str) -> bool:
        t_low = text.lower()
        return any(re.search(p, t_low) for p in self.GOSSIP_PATTERNS)

    def store_fact(
        self,
        subject: str,
        predicate: str,
        value: str,
        memory_type: MemoryType = MemoryType.FACT,
        source_type: MemorySourceType = MemorySourceType.EXPLICIT_USER_STATEMENT,
        evidence: str = "",
        created_by_person: str = "system",
    ) -> Optional[MemoryRecord]:
        """Stores a structured semantic fact, evaluating confidence and resolving contradictions."""
        if self.is_gossip(f"{subject} {predicate} {value} {evidence}"):
            return None

        conf, _ = ConfidenceEngine.evaluate_confidence(memory_type, source_type)
        mem_id = f"fact_{uuid.uuid4().hex[:12]}"
        now = time.time()

        # Resolve existing contradictions
        self.contradiction_engine.resolve_contradictions(subject, predicate, value, mem_id)

        record = MemoryRecord(
            memory_id=mem_id,
            subject=subject.strip(),
            predicate=predicate.strip(),
            value=value.strip(),
            memory_type=memory_type,
            source_type=source_type,
            confidence=conf,
            created_at=now,
            last_confirmed_at=now,
            evidence=evidence.strip(),
            created_by_person=created_by_person,
        )

        self.storage.execute_write(
            """
            INSERT OR REPLACE INTO semantic_facts (
                memory_id, subject, predicate, value, memory_type, source_type,
                confidence, created_at, last_confirmed_at, last_used_at, use_count,
                evidence, visibility, importance, expires_at, contradiction_status,
                superseded_by_id, created_by_person
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.memory_id, record.subject, record.predicate, record.value,
                record.memory_type.value, record.source_type.value, record.confidence,
                record.created_at, record.last_confirmed_at, record.last_used_at,
                record.use_count, record.evidence, record.visibility, record.importance,
                record.expires_at, record.contradiction_status, record.superseded_by_id,
                record.created_by_person,
            ),
        )
        return record

    def query_active_facts_for_subject(self, subject: str) -> List[MemoryRecord]:
        """Retrieves all active, non-superseded facts for a specific subject."""
        rows = self.storage.execute_read(
            """
            SELECT * FROM semantic_facts
            WHERE lower(subject) = ? AND contradiction_status = 'active'
            ORDER BY confidence DESC, last_confirmed_at DESC
            """,
            (subject.strip().lower(),),
        )
        return [self._row_to_record(r) for r in rows]

    def delete_facts_for_person(self, person_name: str) -> int:
        """Deletes all facts and preferences associated with a person (Privacy Right to be Forgotten)."""
        return self.storage.execute_write(
            "DELETE FROM semantic_facts WHERE lower(subject) = ?",
            (person_name.strip().lower(),),
        )

    def _row_to_record(self, row: Any) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row["memory_id"],
            subject=row["subject"],
            predicate=row["predicate"],
            value=row["value"],
            memory_type=MemoryType(row["memory_type"]),
            source_type=MemorySourceType(row["source_type"]),
            confidence=float(row["confidence"]),
            created_at=float(row["created_at"]),
            last_confirmed_at=float(row["last_confirmed_at"]),
            last_used_at=float(row["last_used_at"]),
            use_count=int(row["use_count"]),
            evidence=row["evidence"] or "",
            visibility=row["visibility"] or "public",
            importance=float(row["importance"]),
            expires_at=row["expires_at"],
            contradiction_status=row["contradiction_status"],
            superseded_by_id=row["superseded_by_id"],
            created_by_person=row["created_by_person"] or "system",
        )
