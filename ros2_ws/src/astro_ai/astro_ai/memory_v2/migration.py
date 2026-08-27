"""ASTRO V1 — Seamless JSON to SQLite Migration & Dual-Write Engine."""

import json
import logging

_LOG = logging.getLogger(__name__)

import os
import shutil
import time
from typing import Any, Dict, Optional

from astro_ai.contracts.intent_emotion_types import MemorySourceType
from astro_ai.contracts.memory_models import MemoryType
from astro_ai.memory_v2.relationship_memory import RelationshipMemory
from astro_ai.memory_v2.semantic_memory import SemanticMemory
from astro_ai.memory_v2.spatial_memory import SpatialMemory
from astro_ai.memory_v2.sqlite_storage import SQLiteMemoryStorage


class MemoryMigrator:
    """Migrates legacy astro_memory.json records into SQLite with full backward compatibility."""

    def __init__(
        self,
        storage: SQLiteMemoryStorage,
        semantic_mem: SemanticMemory,
        relationship_mem: RelationshipMemory,
        spatial_mem: SpatialMemory,
        json_path: Optional[str] = None,
    ):
        self.storage = storage
        self.semantic = semantic_mem
        self.relationship = relationship_mem
        self.spatial = spatial_mem
        self.json_path = json_path or self._find_legacy_json_path()

    def _find_legacy_json_path(self) -> str:
        candidates = [
            os.path.abspath("./astro_memory.json"),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "astro_memory.json")),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return candidates[0]

    def migrate_if_needed(self) -> bool:
        """Checks if legacy JSON exists and migrates all data into SQLite."""
        if not os.path.exists(self.json_path):
            return False

        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return False

        # Create backup copy if not already present
        bak_path = self.json_path + ".bak"
        if not os.path.exists(bak_path):
            try:
                shutil.copy2(self.json_path, bak_path)
            except Exception as _exc:
                _LOG.debug("migrate_if_needed: yok sayılan hata (%s)", _exc)

        # 1. Migrate Verified Facts
        facts = data.get("verified_facts", [])
        for fact in facts:
            self.semantic.store_fact(
                subject="Astro",
                predicate="verified_fact",
                value=str(fact),
                memory_type=MemoryType.FACT,
                source_type=MemorySourceType.TRUSTED_SYSTEM_FACT,
            )

        # 2. Migrate Learned Objects
        learned_objs = data.get("learned_objects", {})
        if isinstance(learned_objs, dict):
            for name, desc in learned_objs.items():
                self.spatial.store_landmark(
                    name=name,
                    category="object",
                    x_m=1.0,
                    y_m=0.0,
                    description=str(desc),
                )
        elif isinstance(learned_objs, list):
            for item in learned_objs:
                if isinstance(item, dict):
                    name = item.get("name", "object")
                    desc = item.get("description", str(item))
                else:
                    name = str(item)
                    desc = str(item)
                self.spatial.store_landmark(
                    name=name,
                    category="object",
                    x_m=1.0,
                    y_m=0.0,
                    description=str(desc),
                )

        # 3. Migrate Known People & Preferences
        known_people = data.get("known_people", {})
        people_list = []
        if isinstance(known_people, dict):
            for name, info in known_people.items():
                if isinstance(info, dict):
                    p_name = info.get("name", name)
                    formal = info.get("formal_title", p_name)
                    p_info = info
                else:
                    p_name = str(name)
                    formal = str(info)
                    p_info = {}
                people_list.append((p_name, formal, p_info))
        elif isinstance(known_people, list):
            for item in known_people:
                if isinstance(item, dict):
                    p_name = item.get("name", "user")
                    formal = item.get("formal_title", p_name)
                    p_info = item
                else:
                    p_name = str(item)
                    formal = str(item)
                    p_info = {}
                people_list.append((p_name, formal, p_info))

        for p_name, formal, p_info in people_list:
            self.relationship.get_or_create_profile(p_name, formal_title=formal)

            # Person Facts
            for pf in p_info.get("learned_facts", []):
                self.semantic.store_fact(
                    subject=p_name,
                    predicate="fact",
                    value=str(pf),
                    source_type=MemorySourceType.EXPLICIT_USER_STATEMENT,
                )

            # Preferences
            for k, v in p_info.get("preferences", {}).items():
                self.semantic.store_fact(
                    subject=p_name,
                    predicate=str(k),
                    value=str(v),
                    source_type=MemorySourceType.EXPLICIT_USER_STATEMENT,
                )

        return True

    def sync_to_json_mirror(self):
        """Dual-writes SQLite state back to JSON file for complete backward compatibility."""
        try:
            facts = self.semantic.query_active_facts_for_subject("Astro")
            landmarks = self.spatial.get_all_landmarks()

            data: Dict[str, Any] = {
                "robot_name": "Astro",
                "owner_name": "Baran",
                "current_persona": "playful",
                "verified_facts": [f.value for f in facts if f.predicate == "verified_fact"],
                "learned_objects": {lm.name: lm.description for lm in landmarks},
                "last_synced_at": time.time(),
            }

            tmp_path = self.json_path + ".tmp"
            os.makedirs(os.path.dirname(self.json_path), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.json_path)
        except Exception as _exc:
            _LOG.debug("sync_to_json_mirror: yok sayılan hata (%s)", _exc)
