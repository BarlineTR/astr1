"""ASTRO V1 — Realtime Playback Watchdog.

Monitors TTS request-to-DAC playback latency. If a speech generation request is issued
but physical playback does not begin within deadline (default 1500ms), the watchdog detects
the silent stall and forces an immediate emergency fallback synthesis.
"""

import os
import threading
import time
from typing import Any, Callable, Dict, Optional


class PlaybackWatchdog:
    """Watchdog for detecting and resolving silent audio playback stalls."""

    DEFAULT_DEADLINE_MS = 1500.0

    def __init__(
        self,
        deadline_ms: Optional[float] = None,
        on_stall_callback: Optional[Callable[[int, str], None]] = None,
        logger: Optional[Callable[[str, str], None]] = None,
    ):
        self.deadline_ms = deadline_ms or float(os.getenv("TTS_PLAYBACK_START_DEADLINE_MS", str(self.DEFAULT_DEADLINE_MS)))
        self._on_stall = on_stall_callback
        self._log = logger or (lambda lvl, msg: None)

        self._pending_turns: Dict[int, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._running = True

        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def _safe_log(self, lvl: str, msg: str):
        try:
            if self._log:
                self._log(lvl, msg)
        except Exception:
            pass

    def register_turn_issued(self, generation_id: int, expected_provider: str, text: str):
        """Registers a newly issued TTS request with the watchdog."""
        with self._lock:
            self._pending_turns[generation_id] = {
                "start_time": time.monotonic(),
                "expected_provider": expected_provider,
                "text": text,
                "playback_started": False,
            }

    def mark_playback_started(self, generation_id: int):
        """Notifies watchdog that physical DAC playback has commenced."""
        with self._lock:
            if generation_id in self._pending_turns:
                self._pending_turns[generation_id]["playback_started"] = True

    def mark_turn_finished(self, generation_id: int):
        """Removes generation from watchdog tracking once turn completes."""
        with self._lock:
            self._pending_turns.pop(generation_id, None)

    def _monitor_loop(self):
        while self._running:
            time.sleep(0.1)
            now = time.monotonic()
            stalled_items = []

            with self._lock:
                for gen_id, info in list(self._pending_turns.items()):
                    elapsed_ms = (now - info["start_time"]) * 1000.0
                    if not info["playback_started"] and elapsed_ms > self.deadline_ms:
                        stalled_items.append((gen_id, info["expected_provider"], info["text"], elapsed_ms))
                        # Prevent duplicate stall triggers
                        info["playback_started"] = True

            for gen_id, exp_prov, text, elapsed in stalled_items:
                self._safe_log(
                    "warn",
                    f"🚨 [TTS PLAYBACK WATCHDOG]\n"
                    f"  generation_id={gen_id}\n"
                    f"  expected_provider={exp_prov}\n"
                    f"  elapsed_ms={elapsed:.1f}ms > deadline={self.deadline_ms:.0f}ms\n"
                    f"  action=force_fallback"
                )
                if self._on_stall:
                    try:
                        self._on_stall(gen_id, exp_prov)
                    except Exception as e:
                        self._safe_log("error", f"Watchdog stall callback exception: {e}")

    def stop(self):
        self._running = False
