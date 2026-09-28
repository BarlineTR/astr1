"""ASTRO V1 — Weighted Contextual Memory Retrieval Engine.

Ranks and retrieves top-K memories using confidence, recency, query overlap,
and relationship relevance instead of dumping raw memory dumps into system prompts.
"""

import math
import time
from typing import Any, Dict, List, Optional

from astro_ai.contracts.memory_models import MemoryRecord
from astro_ai.memory_v2.semantic_memory import SemanticMemory
from astro_ai.memory_v2.sqlite_storage import SQLiteMemoryStorage


class MemoryRetrievalEngine:
    """Retrieves relevant facts and context for a specific speaker and dialogue turn."""

    def __init__(self, storage: SQLiteMemoryStorage, semantic_mem: SemanticMemory):
        self.storage = storage
        self.semantic = semantic_mem

    def retrieve_relevant_memories(
        self,
        person_name: str,
        user_query: str = "",
        top_k: int = 5,
    ) -> List[MemoryRecord]:
        """Retrieves and ranks memories for a person and ongoing topic."""
        # 1. Fetch active facts for person + global robot facts
        person_facts = self.semantic.query_active_facts_for_subject(person_name) if person_name else []
        robot_facts = self.semantic.query_active_facts_for_subject("Astro")
        creator_facts = self.semantic.query_active_facts_for_subject("Baran")

        candidates: Dict[str, MemoryRecord] = {}
        for f in person_facts + robot_facts + creator_facts:
            candidates[f.memory_id] = f

        if not candidates:
            return []

        now = time.time()
        query_words = set(user_query.lower().split()) if user_query else set()

        scored_memories = []
        for mem_id, rec in candidates.items():
            # 1. Recency score (decay over 30 days)
            age_days = (now - rec.last_confirmed_at) / 86400.0
            recency_score = math.exp(-age_days / 30.0)

            # 2. Confidence score (0.0 to 1.0)
            conf_score = rec.confidence

            # 3. Topic Overlap / Context Relevance
            fact_words = set(f"{rec.predicate} {rec.value} {rec.evidence}".lower().split())
            synonym_map = {
                "yemek": ["food", "yemek", "mantı", "kebap"],
                "takım": ["team", "takım", "futbol", "fenerbahçe", "galatasaray", "beşiktaş", "bayern"],
                "kahve": ["coffee", "kahve", "latte", "espresso", "çay"],
                "şehir": ["city", "şehir", "memleket", "ankara", "istanbul", "bitlis", "ahlat"],
            }
            overlap = len(query_words.intersection(fact_words))
            for qw in query_words:
                for syn_key, syn_list in synonym_map.items():
                    if qw in syn_list:
                        for sw in syn_list:
                            if any(sw in fw for fw in fact_words):
                                overlap += 1
            context_relevance = min(1.0, overlap * 0.40)

            # 4. Importance score
            imp_score = rec.importance

            # Weighted Total
            total_score = (
                0.35 * conf_score
                + 0.25 * recency_score
                + 0.25 * context_relevance
                + 0.15 * imp_score
            )
            scored_memories.append((total_score, rec))

        # Sort descending by score
        scored_memories.sort(key=lambda x: x[0], reverse=True)
        top_records = [rec for _, rec in scored_memories[:top_k]]

        # Update last_used_at on retrieved records
        for rec in top_records:
            self.storage.execute_write(
                "UPDATE semantic_facts SET last_used_at = ?, use_count = use_count + 1 WHERE memory_id = ?",
                (now, rec.memory_id),
            )

        return top_records
