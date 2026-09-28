"""ASTRO V1 — Memory Contradiction and Conflict Resolution Engine."""

from typing import List, Optional, Tuple

from astro_ai.contracts.memory_models import MemoryRecord
from astro_ai.memory_v2.sqlite_storage import SQLiteMemoryStorage


class ContradictionEngine:
    """Detects and resolves conflicts between previous memories and newly learned facts."""

    def __init__(self, storage: SQLiteMemoryStorage):
        self.storage = storage

    def resolve_contradictions(
        self,
        subject: str,
        predicate: str,
        new_value: str,
        new_memory_id: str,
    ) -> List[str]:
        """Finds any active existing memories for the same subject/predicate that differ,

        and marks them as 'superseded' by new_memory_id. Returns superseded memory IDs.
        """
        norm_subj = subject.strip().lower()
        norm_pred = predicate.strip().lower()
        norm_val = new_value.strip().lower()

        # Query existing active records
        rows = self.storage.execute_read(
            """
            SELECT memory_id, value FROM semantic_facts
            WHERE lower(subject) = ? AND lower(predicate) = ? AND contradiction_status = 'active'
            """,
            (norm_subj, norm_pred),
        )

        superseded_ids = []
        for row in rows:
            old_id = row["memory_id"]
            old_val = str(row["value"]).strip().lower()

            if old_val != norm_val:
                # Value has changed -> supersede old memory
                self.storage.execute_write(
                    """
                    UPDATE semantic_facts
                    SET contradiction_status = 'superseded', superseded_by_id = ?
                    WHERE memory_id = ?
                    """,
                    (new_memory_id, old_id),
                )
                superseded_ids.append(old_id)

        return superseded_ids
