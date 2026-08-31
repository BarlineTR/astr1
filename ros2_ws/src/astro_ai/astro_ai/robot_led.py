#!/usr/bin/env python3
"""ASTRO V1 — ReSpeaker 12 LED Ring Controller (pixel_ring Integration).

Thread-safe, non-blocking hardware LED controller with safe fallbacks:
  - IDLE:       idle()      (breath / standby glow)
  - LISTENING:  listening() (cyan/blue pulse / active listen)
  - THINKING:   thinking()  (spin / wait animation)
  - SPEAKING:   speaking()  (speech dynamic response)
  - ERROR:      error()     (red warning indicator)
  - OFF:        off()       (LEDs turned off)
"""

import logging
import queue
import threading
from typing import Optional

_LOG = logging.getLogger("RobotLED")


class RobotLED:
    """Non-blocking, thread-safe ReSpeaker 12 LED Ring Driver."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self._logger = logger or _LOG
        self._dev = None
        self._pixel_ring = None
        self._state_queue: queue.Queue = queue.Queue(maxsize=10)
        self._running = True
        self._lock = threading.Lock()
        self._last_state: str = "off"

        # Hardware initialization
        self._init_hardware()

        # Non-blocking async worker thread
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="LEDWorkerThread",
        )
        self._worker_thread.start()

    def _init_hardware(self):
        """Attempts to discover and initialize ReSpeaker USB Pixel Ring."""
        try:
            from pixel_ring import pixel_ring
            self._pixel_ring = pixel_ring
            try:
                if hasattr(pixel_ring, "change_pattern"):
                    pixel_ring.change_pattern('echo')
                if hasattr(pixel_ring, "set_brightness"):
                    pixel_ring.set_brightness(20)
                if hasattr(pixel_ring, "off"):
                    pixel_ring.off()
            except Exception:
                pass
            self._logger.info("✨ [RobotLED] ReSpeaker 12 LED Ring (pixel_ring) donanımı bağlandı.")
        except Exception as exc:
            self._logger.debug(f"[RobotLED] pixel_ring import/init notice: {exc}")

    def _worker_loop(self):
        """Worker loop processing LED commands asynchronously."""
        while self._running:
            try:
                state_cmd = self._state_queue.get(timeout=0.5)
                if state_cmd == "QUIT":
                    break
                self._apply_state(state_cmd)
                self._state_queue.task_done()
            except queue.Empty:
                continue
            except Exception as exc:
                self._logger.debug(f"[RobotLED] Worker error: {exc}")

    def _apply_state(self, state: str):
        """Applies state to hardware with safety guard."""
        if not self._pixel_ring:
            return
        try:
            with self._lock:
                if state == "idle":
                    if hasattr(self._pixel_ring, "wakeup"):
                        self._pixel_ring.wakeup()
                    elif hasattr(self._pixel_ring, "off"):
                        self._pixel_ring.off()
                elif state == "listening":
                    if hasattr(self._pixel_ring, "listen"):
                        self._pixel_ring.listen()
                    elif hasattr(self._pixel_ring, "mono"):
                        self._pixel_ring.mono(0, 180, 255)
                    elif hasattr(self._pixel_ring, "set_color"):
                        self._pixel_ring.set_color(r=0, g=180, b=255)
                elif state == "thinking":
                    if hasattr(self._pixel_ring, "think"):
                        self._pixel_ring.think()
                    elif hasattr(self._pixel_ring, "wait"):
                        self._pixel_ring.wait()
                    elif hasattr(self._pixel_ring, "spin"):
                        self._pixel_ring.spin()
                    elif hasattr(self._pixel_ring, "mono"):
                        self._pixel_ring.mono(255, 180, 0)
                    elif hasattr(self._pixel_ring, "set_color"):
                        self._pixel_ring.set_color(r=255, g=180, b=0)
                elif state == "speaking":
                    if hasattr(self._pixel_ring, "speak"):
                        self._pixel_ring.speak()
                    elif hasattr(self._pixel_ring, "trace"):
                        self._pixel_ring.trace()
                    elif hasattr(self._pixel_ring, "mono"):
                        self._pixel_ring.mono(0, 255, 120)
                    elif hasattr(self._pixel_ring, "set_color"):
                        self._pixel_ring.set_color(r=0, g=255, b=120)
                elif state == "error":
                    if hasattr(self._pixel_ring, "mono"):
                        self._pixel_ring.mono(255, 0, 0)
                    elif hasattr(self._pixel_ring, "set_color"):
                        self._pixel_ring.set_color(r=255, g=0, b=0)
                    elif hasattr(self._pixel_ring, "off"):
                        self._pixel_ring.off()
                elif state == "off":
                    if hasattr(self._pixel_ring, "off"):
                        self._pixel_ring.off()
        except Exception as exc:
            self._logger.debug(f"[RobotLED] Hardware apply error ({state}): {exc}")


    def set_state(self, state: str):
        """Queues a state change non-blockingly."""
        state_norm = (state or "").lower().strip()
        if state_norm == self._last_state:
            return
        self._last_state = state_norm
        try:
            # Drain queue if full to always apply latest state
            while not self._state_queue.empty():
                try:
                    self._state_queue.get_nowait()
                    self._state_queue.task_done()
                except Exception:
                    break
            self._state_queue.put_nowait(state_norm)
        except Exception:
            pass

    def idle(self):
        self.set_state("idle")

    def listening(self):
        self.set_state("listening")

    def thinking(self):
        self.set_state("thinking")

    def speaking(self):
        self.set_state("speaking")

    def error(self):
        self.set_state("error")

    def off(self):
        self.set_state("off")

    def shutdown(self):
        """Clean shutdown turning off LEDs."""
        self._running = False
        self.off()
        try:
            self._state_queue.put_nowait("QUIT")
        except Exception:
            pass
