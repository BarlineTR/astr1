"""ASTRO V1 — Local Architecture Analysis Cache.

Provides fast, persistent, and thread-safe caching for architecture support responses.
Identical requests against unchanged architecture contexts avoid external API calls.

SECURITY & INTEGRITY INVARIANTS:
  1. API keys and credentials are NEVER written to the cache.
  2. Cache keys incorporate context hash and prompt hash to prevent stale responses.
  3. Configurable TTL ensures automatic expiration.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from typing import Any, Dict, Optional

from astro_ai.brain.support.contracts import (
    ArchitectureSupportResponse,
    ProposedChange,
    SupportControlMode,
    SupportStatus,
)


class ArchitectureSupportCache:
    """Thread-safe SQLite/in-memory cache for architecture support queries."""

    def __init__(self, db_path: str = ":memory:", default_ttl_seconds: int = 86400):
        self.db_path = db_path
        self.default_ttl = default_ttl_seconds
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS support_cache (
                    cache_key TEXT PRIMARY KEY,
                    created_at REAL,
                    expires_at REAL,
                    response_json TEXT
                )
                """
            )
            self._conn.commit()

    @staticmethod
    def compute_cache_key(topic: str, context_hash: str, prompt: str, provider: str = "") -> str:
        """Computes a deterministic SHA256 cache key."""
        prompt_hash = hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()[:16]
        raw_key = f"{topic.lower()}::{provider.lower()}::{context_hash}::{prompt_hash}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def get(self, cache_key: str, now: Optional[float] = None) -> Optional[ArchitectureSupportResponse]:
        """Retrieves an active cached response if not expired."""
        current_time = now if now is not None else time.time()
        with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute(
                    "SELECT expires_at, response_json FROM support_cache WHERE cache_key = ?",
                    (cache_key,),
                )
                row = cursor.fetchone()
                if not row:
                    return None

                expires_at, response_json = row
                if current_time >= expires_at:
                    # Expired entry: purge
                    cursor.execute("DELETE FROM support_cache WHERE cache_key = ?", (cache_key,))
                    self._conn.commit()
                    return None

                data = json.loads(response_json)
                changes = [
                    ProposedChange(**c) for c in data.get("proposed_changes", [])
                ]
                return ArchitectureSupportResponse(
                    request_id=data.get("request_id", ""),
                    provider=data.get("provider", ""),
                    model=data.get("model", ""),
                    mode=SupportControlMode(data.get("mode", SupportControlMode.PROPOSE.value)),
                    status=SupportStatus.CACHED,
                    summary=data.get("summary", ""),
                    observations=data.get("observations", []),
                    architectural_concerns=data.get("architectural_concerns", []),
                    proposed_changes=changes,
                    affected_files=data.get("affected_files", []),
                    invariant_checks=data.get("invariant_checks", {}),
                    test_plan=data.get("test_plan", []),
                    confidence=data.get("confidence", 0.8),
                    requires_human_approval=data.get("requires_human_approval", True),
                    cache_hit=True,
                    reasoning_level=data.get("reasoning_level"),
                )
            except Exception:
                return None

    def put(
        self,
        cache_key: str,
        response: ArchitectureSupportResponse,
        ttl_seconds: Optional[int] = None,
        now: Optional[float] = None,
    ) -> None:
        """Stores a serialized response in the cache."""
        current_time = now if now is not None else time.time()
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        expires_at = current_time + ttl

        # Strip any secrets before saving
        safe_dict = response.to_dict()
        safe_json = json.dumps(safe_dict, ensure_ascii=False)

        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO support_cache (cache_key, created_at, expires_at, response_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (cache_key, current_time, expires_at, safe_json),
                )
                self._conn.commit()
            except Exception:
                pass

    def clear(self) -> None:
        """Clears all cached entries."""
        with self._lock:
            self._conn.execute("DELETE FROM support_cache")
            self._conn.commit()
