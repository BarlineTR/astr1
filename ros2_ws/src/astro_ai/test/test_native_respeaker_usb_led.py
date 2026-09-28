#!/usr/bin/env python3
"""ASTRO V1 — Unit Tests for Native ReSpeaker USB LED Ring Driver & RobotLED Controller.

Verifies:
  - Native XMOS XVF3000 USB Endpoint 0 Vendor Control Transfer Commands:
      * LISTEN / WAKEUP -> cmd=2, wIndex=0x1C
      * SPEAK -> cmd=3, wIndex=0x1C
      * THINK -> cmd=4, wIndex=0x1C
      * TRACE -> cmd=0, wIndex=0x1C
      * OFF / MONO -> cmd=1, wIndex=0x1C
      * BRIGHTNESS -> cmd=0x20, wIndex=0x1C
  - Proper Permission Handling (Errno 13 / Access denied logs clear udev instructions)
  - Non-blocking Queue & Thread-safe execution
  - Exclusion of erroneous APA102 SPI dummy objects
"""

import logging
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

from astro_ai.robot_led import NativeReSpeakerUsbRing, RobotLED


class TestNativeReSpeakerUsbRing(unittest.TestCase):
    """Verifies low-level USB vendor control transfers for ReSpeaker 4-Mic Array."""

    def setUp(self):
        self.mock_dev = MagicMock()
        self.logger = logging.getLogger("TestRobotLED")
        self.ring = NativeReSpeakerUsbRing(dev=self.mock_dev, logger=self.logger)

    def test_listen_command_ctrl_transfer(self):
        success = self.ring.listen()
        self.assertTrue(success)
        self.mock_dev.ctrl_transfer.assert_called_with(
            0x40, 0, 2, 0x1C, [0], 2000
        )

    def test_wakeup_alias_for_listen(self):
        success = self.ring.wakeup()
        self.assertTrue(success)
        self.mock_dev.ctrl_transfer.assert_called_with(
            0x40, 0, 2, 0x1C, [0], 2000
        )

    def test_think_command_ctrl_transfer(self):
        success = self.ring.think()
        self.assertTrue(success)
        self.mock_dev.ctrl_transfer.assert_called_with(
            0x40, 0, 4, 0x1C, [0], 2000
        )

    def test_speak_command_ctrl_transfer(self):
        success = self.ring.speak()
        self.assertTrue(success)
        self.mock_dev.ctrl_transfer.assert_called_with(
            0x40, 0, 3, 0x1C, [0], 2000
        )

    def test_trace_command_ctrl_transfer(self):
        success = self.ring.trace()
        self.assertTrue(success)
        self.mock_dev.ctrl_transfer.assert_called_with(
            0x40, 0, 0, 0x1C, [0], 2000
        )

    def test_off_command_ctrl_transfer(self):
        success = self.ring.off()
        self.assertTrue(success)
        self.mock_dev.ctrl_transfer.assert_called_with(
            0x40, 0, 1, 0x1C, [0, 0, 0, 0], 2000
        )

    def test_mono_custom_color_ctrl_transfer(self):
        success = self.ring.mono(r=255, g=128, b=64)
        self.assertTrue(success)
        self.mock_dev.ctrl_transfer.assert_called_with(
            0x40, 0, 1, 0x1C, [255, 128, 64, 0], 2000
        )

    def test_brightness_command_ctrl_transfer(self):
        success = self.ring.set_brightness(50)
        self.assertTrue(success)
        self.mock_dev.ctrl_transfer.assert_called_with(
            0x40, 0, 0x20, 0x1C, [50], 2000
        )

    def test_permission_error_logs_udev_guidance(self):
        self.mock_dev.ctrl_transfer.side_effect = Exception(
            "[Errno 13] Access denied (insufficient permissions)"
        )
        with self.assertLogs(self.logger, level="WARNING") as log_capture:
            success = self.ring.think()
            self.assertFalse(success)
            self.assertTrue(any("udev kuralı ekleyin" in msg for msg in log_capture.output))
            self.assertTrue(any("60-respeaker.rules" in msg for msg in log_capture.output))


class TestRobotLEDController(unittest.TestCase):
    """Verifies thread-safe RobotLED non-blocking queue operations."""

    def test_robot_led_state_transitions(self):
        mock_hw = MagicMock()
        mock_usb = MagicMock()
        mock_usb.core = MagicMock()
        mock_usb.core.find.return_value = mock_hw

        with patch.dict(sys.modules, {"usb": mock_usb, "usb.core": mock_usb.core}):
            controller = RobotLED()
            # Verify driver is NativeReSpeakerUsbRing, not APA102 SPI
            self.assertIsInstance(controller.driver, NativeReSpeakerUsbRing)

            controller.listening()
            time.sleep(0.1)
            mock_hw.ctrl_transfer.assert_called_with(0x40, 0, 2, 0x1C, [0], 2000)

            controller.thinking()
            time.sleep(0.1)
            mock_hw.ctrl_transfer.assert_called_with(0x40, 0, 4, 0x1C, [0], 2000)

            controller.speaking()
            time.sleep(0.1)
            mock_hw.ctrl_transfer.assert_called_with(0x40, 0, 3, 0x1C, [0], 2000)

            controller.off()
            time.sleep(0.1)
            mock_hw.ctrl_transfer.assert_called_with(0x40, 0, 1, 0x1C, [0, 0, 0, 0], 2000)

            controller.shutdown()


if __name__ == "__main__":
    unittest.main()

