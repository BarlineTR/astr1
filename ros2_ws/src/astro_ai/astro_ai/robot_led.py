#!/usr/bin/env python3
"""ASTRO V1 — ReSpeaker 12 LED Ring Controller & Native USB Driver.

Thread-safe, non-blocking hardware LED controller for Seeed ReSpeaker USB 4-Mic Array.
Directly interfaces with the XMOS XVF3000 USB Endpoint 0 vendor control transfer
protocol (0x2886:0x0018), eliminating erroneous APA102 SPI fallbacks.

LED Modes:
  - IDLE:       idle()      (dim glow / standby off)
  - LISTENING:  listening() (cyan pulse / active listen)
  - THINKING:   thinking()  (spin / wait animation)
  - SPEAKING:   speaking()  (speech dynamic response)
  - ERROR:      error()     (red warning indicator)
  - OFF:        off()       (LEDs turned off)
"""

import logging
import queue
import threading
import time
from typing import Any, Dict, List, Optional

_LOG = logging.getLogger("RobotLED")


class LEDState:
    """Standard LED Ring visual states."""
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"
    OFF = "off"


class NativeReSpeakerUsbRing:
    """Direct hardware driver for Seeed ReSpeaker USB 4-Mic Array (XMOS XVF3000).

    Uses USB vendor control transfers directly to endpoint 0:
      bmRequestType = 0x40 (CTRL_OUT | CTRL_TYPE_VENDOR | CTRL_RECIPIENT_DEVICE)
      bRequest = 0
      wValue = Command ID (0: trace, 1: mono, 2: listen, 3: speak, 4: think, 5: spin, 0x20: brightness)
      wIndex = 0x1C
      data = payload bytes (e.g. [0] or [r, g, b, 0] or [brightness])
    """

    VID = 0x2886
    PID = 0x0018
    TIMEOUT = 2000

    def __init__(self, dev: Optional[Any] = None, logger: Optional[logging.Logger] = None):
        self._dev = dev
        self._logger = logger or _LOG
        self._brightness = 25
        self._last_err_logged: float = 0.0
        self._last_init_attempt: float = 0.0
        self._init_device()

    def _init_device(self) -> bool:
        if self._dev is not None:
            return True
        now = time.monotonic()
        if now - self._last_init_attempt < 2.5:
            return False
        self._last_init_attempt = now
        try:
            import usb.core
            dev = usb.core.find(idVendor=self.VID, idProduct=self.PID)
            if dev is None:
                # Fallback to Seeed vendor ID lookup
                dev = usb.core.find(idVendor=self.VID)
            if dev is not None:
                self._dev = dev
                self._logger.info(
                    f"✨ [RobotLED] ReSpeaker USB donanımı doğrudan bağlandı (VID=0x{self.VID:04x}, PID=0x{self.PID:04x})."
                )
                self.set_brightness(self._brightness)
                return True
        except Exception as exc:
            self._handle_usb_error("init", exc)
        return False

    def _handle_usb_error(self, action: str, exc: Exception):
        now = time.monotonic()
        exc_str = str(exc)
        is_pipe_err = "32" in exc_str or "pipe" in exc_str.lower()
        limit_s = 10.0 if is_pipe_err else 5.0
        if now - self._last_err_logged < limit_s:
            return
        self._last_err_logged = now

        if "Access denied" in exc_str or "13" in exc_str or "insufficient permissions" in exc_str.lower():
            self._logger.warning(
                f"⚠️ [RobotLED] ReSpeaker USB erişim izni yok ({action}): {exc}\n"
                "Çözüm için terminalde şu komutu çalıştırarak udev kuralı ekleyin:\n"
                "  echo 'SUBSYSTEM==\"usb\", ATTR{idVendor}==\"2886\", MODE=\"0666\"' | sudo tee /etc/udev/rules.d/60-respeaker.rules\n"
                "  sudo udevadm control --reload-rules && sudo udevadm trigger"
            )
        elif is_pipe_err:
            self._logger.warning(f"⚠️ [RobotLED] ReSpeaker USB endpoint stall/pipe uyarısı ({action}): {exc}. Otomatik USB reset denenecek.")
        else:
            self._logger.warning(f"⚠️ [RobotLED] ReSpeaker USB donanım uyarısı ({action}): {exc}")

    def write(self, cmd: int, data: Optional[List[int]] = None) -> bool:
        """Sends a vendor control transfer to ReSpeaker USB endpoint 0."""
        if data is None:
            data = [0]
        if self._dev is None:
            if not self._init_device() or self._dev is None:
                return False
        try:
            # 0x40 = usb.util.CTRL_OUT | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE
            self._dev.ctrl_transfer(0x40, 0, cmd, 0x1C, data, self.TIMEOUT)
            return True
        except Exception as exc:
            self._handle_usb_error(f"write(cmd={cmd})", exc)
            if "32" in str(exc) or "pipe" in str(exc).lower():
                try:
                    self._dev.reset()
                except Exception:
                    pass
            self._dev = None  # Re-enumerate on next attempt
            return False

    def listen(self) -> bool:
        """Command 2: Listen mode (cyan pulse animation)."""
        return self.write(2)

    def wakeup(self) -> bool:
        """Alias for listen mode."""
        return self.listen()

    def think(self) -> bool:
        """Command 4: Think mode (spin / wait animation)."""
        return self.write(4)

    def speak(self) -> bool:
        """Command 3: Speak mode (speech voice tracking animation)."""
        return self.write(3)

    def trace(self) -> bool:
        """Command 0: Trace mode (DOA & VAD tracking)."""
        return self.write(0)

    def spin(self) -> bool:
        """Command 5: Spin mode."""
        return self.write(5)

    def mono(self, r: int = 0, g: int = 0, b: int = 0) -> bool:
        """Command 1: Single static RGB color."""
        return self.write(1, [r & 0xFF, g & 0xFF, b & 0xFF, 0])

    def off(self) -> bool:
        """Turns all LEDs off."""
        return self.mono(0, 0, 0)

    def set_brightness(self, brightness: int = 25) -> bool:
        """Command 0x20: Sets brightness (1-100)."""
        self._brightness = max(1, min(100, int(brightness)))
        return self.write(0x20, [self._brightness])

    @property
    def is_connected(self) -> bool:
        return self._dev is not None


class RobotLED:
    """Non-blocking, thread-safe ReSpeaker 12 LED Ring Driver."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self._logger = logger or _LOG
        self._driver: Optional[Any] = None
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
        """Discovers and binds ReSpeaker USB hardware directly."""
        try:
            native_driver = NativeReSpeakerUsbRing(logger=self._logger)
            if native_driver.is_connected:
                self._driver = native_driver
                self._logger.info("✨ [RobotLED] ReSpeaker 12 LED Ring (NativeReSpeakerUsbRing) donanımı bağlandı.")
                return
        except Exception as exc:
            self._logger.debug(f"[RobotLED] NativeReSpeakerUsbRing init notice: {exc}")

        # Fallback: Check if UsbPixelRingV2 from pixel_ring is present and actually USB
        try:
            import usb.core
            from pixel_ring.usb_pixel_ring_v2 import PixelRing as UsbPixelRingV2
            dev = usb.core.find(idVendor=0x2886, idProduct=0x0018)
            if not dev:
                dev = usb.core.find(idVendor=0x2886)
            if dev is not None:
                self._driver = UsbPixelRingV2(dev)
                self._logger.info("✨ [RobotLED] ReSpeaker 12 LED Ring (UsbPixelRingV2) donanımı bağlandı.")
                return
        except Exception as exc:
            self._logger.debug(f"[RobotLED] UsbPixelRingV2 fallback notice: {exc}")

        self._logger.debug("[RobotLED] ReSpeaker LED donanımı henüz bulunamadı (otomatik denenecek).")

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
                if not self._driver:
                    self._init_hardware()
                continue
            except Exception as exc:
                self._logger.debug(f"[RobotLED] Worker loop error: {exc}")

    def _apply_state(self, state: str):
        """Applies state to hardware non-blockingly."""
        if not self._driver:
            self._init_hardware()
            if not self._driver:
                return

        try:
            with self._lock:
                if state == "idle":
                    if hasattr(self._driver, "off"):
                        self._driver.off()
                    elif hasattr(self._driver, "mono"):
                        self._driver.mono(0, 0, 0)
                elif state == "listening":
                    if hasattr(self._driver, "listen"):
                        self._driver.listen()
                    elif hasattr(self._driver, "wakeup"):
                        self._driver.wakeup()
                    elif hasattr(self._driver, "mono"):
                        self._driver.mono(0, 180, 255)
                elif state == "thinking":
                    if hasattr(self._driver, "think"):
                        self._driver.think()
                    elif hasattr(self._driver, "spin"):
                        self._driver.spin()
                    elif hasattr(self._driver, "mono"):
                        self._driver.mono(255, 180, 0)
                elif state == "speaking":
                    if hasattr(self._driver, "speak"):
                        self._driver.speak()
                    elif hasattr(self._driver, "trace"):
                        self._driver.trace()
                    elif hasattr(self._driver, "mono"):
                        self._driver.mono(0, 255, 120)
                elif state == "error":
                    if hasattr(self._driver, "mono"):
                        self._driver.mono(255, 0, 0)
                    elif hasattr(self._driver, "off"):
                        self._driver.off()
                elif state == "off":
                    if hasattr(self._driver, "off"):
                        self._driver.off()

                self._logger.info(f"✨ [RobotLED] LED Durumu: {state.upper()}")
        except Exception as exc:
            self._logger.warning(f"⚠️ [RobotLED] Hardware apply error ({state}): {exc}")

    def set_state(self, state: str):
        """Queues a state change non-blockingly."""
        state_norm = (state or "").lower().strip()
        if state_norm == self._last_state:
            return
        self._last_state = state_norm
        try:
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

    @property
    def driver(self) -> Optional[Any]:
        return self._driver
