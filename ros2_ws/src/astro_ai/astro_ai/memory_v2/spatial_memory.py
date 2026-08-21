"""ASTRO V1 — Long-Term Spatial Memory Engine."""

import time
import uuid
from typing import Any, Dict, List, Optional

from astro_ai.contracts.memory_models import SpatialMemoryItem
from astro_ai.memory_v2.sqlite_storage import SQLiteMemoryStorage


class SpatialMemory:
    """Stores and recalls persistent physical landmarks and objects in Astro's environment."""

    def __init__(self, storage: SQLiteMemoryStorage):
        self.storage = storage

    def store_landmark(
        self,
        name: str,
        category: str,
        x_m: float,
        y_m: float,
        orientation_deg: float = 0.0,
        description: str = "",
        confidence: float = 1.0,
    ) -> SpatialMemoryItem:
        item_id = f"spat_{name.lower().replace(' ', '_')}"
        now = time.time()

        item = SpatialMemoryItem(
            item_id=item_id,
            name=name.strip(),
            category=category.strip(),
            relative_x_m=round(x_m, 2),
            relative_y_m=round(y_m, 2),
            orientation_deg=round(orientation_deg, 1),
            description=description.strip(),
            confidence=confidence,
            last_verified_ts=now,
        )

        self.storage.execute_write(
            """
            INSERT OR REPLACE INTO spatial_landmarks (
                item_id, name, category, relative_x_m, relative_y_m,
                orientation_deg, description, confidence, last_verified_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.item_id, item.name, item.category, item.relative_x_m,
                item.relative_y_m, item.orientation_deg, item.description,
                item.confidence, item.last_verified_ts,
            ),
        )
        return item

    def get_landmark(self, name: str) -> Optional[SpatialMemoryItem]:
        rows = self.storage.execute_read(
            "SELECT * FROM spatial_landmarks WHERE lower(name) = ?",
            (name.strip().lower(),),
        )
        if not rows:
            return None
        r = rows[0]
        return SpatialMemoryItem(
            item_id=r["item_id"],
            name=r["name"],
            category=r["category"],
            relative_x_m=float(r["relative_x_m"]),
            relative_y_m=float(r["relative_y_m"]),
            orientation_deg=float(r["orientation_deg"]),
            description=r["description"] or "",
            confidence=float(r["confidence"]),
            last_verified_ts=float(r["last_verified_ts"]),
        )

    def get_all_landmarks(self) -> List[SpatialMemoryItem]:
        rows = self.storage.execute_read("SELECT * FROM spatial_landmarks ORDER BY name ASC")
        return [
            SpatialMemoryItem(
                item_id=r["item_id"],
                name=r["name"],
                category=r["category"],
                relative_x_m=float(r["relative_x_m"]),
                relative_y_m=float(r["relative_y_m"]),
                orientation_deg=float(r["orientation_deg"]),
                description=r["description"] or "",
                confidence=float(r["confidence"]),
                last_verified_ts=float(r["last_verified_ts"]),
            )
            for r in rows
        ]
