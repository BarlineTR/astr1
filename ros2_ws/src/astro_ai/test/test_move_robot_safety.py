#!/usr/bin/env python3
"""ASTRO V1 — move_robot güvenlik kapısı testleri."""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"


def _healthy(node, **overrides):
    health = {
        "serial_connected": True,
        "handshake": True,
        "heartbeat_healthy": True,
        "motor_enabled": True,
        "updated_at": time.monotonic(),
    }
    health.update(overrides)
    node.motor_health = health


class TestMoveRobotSafetyGate(unittest.TestCase):
    def setUp(self):
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        self.node = AstroRealtimeNode()
        self.node.pub_cmd_vel = MagicMock()
        self.node.has_motion_backend = True

    def test_rejected_when_no_health_received_at_all(self):
        self.node.motor_health = {}
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertEqual(res["status"], "rejected")
        self.assertEqual(res["reason"], "motor_health_unproven")
        self.node.pub_cmd_vel.publish.assert_not_called()

    def test_rejected_when_serial_disconnected(self):
        _healthy(self.node, serial_connected=False)
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertEqual(res["status"], "rejected")
        self.node.pub_cmd_vel.publish.assert_not_called()

    def test_rejected_when_handshake_missing(self):
        _healthy(self.node, handshake=False)
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertEqual(res["status"], "rejected")
        self.node.pub_cmd_vel.publish.assert_not_called()

    def test_rejected_when_heartbeat_unhealthy(self):
        _healthy(self.node, heartbeat_healthy=False)
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertEqual(res["status"], "rejected")
        self.node.pub_cmd_vel.publish.assert_not_called()

    def test_rejected_when_motor_disabled(self):
        _healthy(self.node, motor_enabled=False)
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertEqual(res["status"], "rejected")
        self.node.pub_cmd_vel.publish.assert_not_called()

    def test_rejected_when_health_is_stale(self):
        """Arduino ölürse son 'sağlıklı' mesaj hareketi yetkilendirmemeli."""
        _healthy(self.node, updated_at=time.monotonic() - 30.0)
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertEqual(res["status"], "rejected")
        self.assertEqual(res["reason"], "motor_health_stale")
        self.node.pub_cmd_vel.publish.assert_not_called()

    def test_rejected_when_no_motion_backend(self):
        """base_bridge yokken /cmd_vel'i kimse dinlemiyor — sessizce başarı DÖNMEZ."""
        _healthy(self.node)
        self.node.has_motion_backend = False
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertEqual(res["status"], "rejected")
        self.assertEqual(res["reason"], "no_motion_backend")
        self.node.pub_cmd_vel.publish.assert_not_called()

    def test_allowed_when_fully_healthy(self):
        _healthy(self.node)
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertEqual(res["status"], "success")
        self.node.pub_cmd_vel.publish.assert_called()

    def test_stop_is_always_allowed(self):
        """Durdurma komutu güvenlik kapısına takılmaz — durmak her zaman güvenlidir."""
        self.node.motor_health = {}
        res = self.node._execute_realtime_tool("move_robot", {"direction": "stop"})
        self.assertEqual(res["status"], "success")
        self.node.pub_cmd_vel.publish.assert_called()

    def test_rejection_carries_spoken_message(self):
        """Model reddi kullanıcıya sözle iletebilmeli."""
        self.node.motor_health = {}
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertIn("message", res)
        self.assertTrue(res["message"].strip())


class TestMotorHealthParsing(unittest.TestCase):
    def setUp(self):
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        self.node = AstroRealtimeNode()

    def test_diagnostics_message_populates_health(self):
        # SimpleNamespace kullanılıyor: MagicMock'ta `name=` özel bir kwarg'dır
        # (mock'un adını ayarlar, attribute yaratmaz) ve sessizce yanıltır.
        from types import SimpleNamespace

        kv = [
            SimpleNamespace(key="serial_connected", value="True"),
            SimpleNamespace(key="handshake", value="True"),
            SimpleNamespace(key="heartbeat_healthy", value="True"),
            SimpleNamespace(key="motor_enabled", value="False"),
        ]
        status = SimpleNamespace(name="arduino", values=kv)
        msg = SimpleNamespace(status=[status])

        self.node._on_arduino_diagnostics(msg)

        self.assertTrue(self.node.motor_health["serial_connected"])
        self.assertTrue(self.node.motor_health["handshake"])
        self.assertTrue(self.node.motor_health["heartbeat_healthy"])
        self.assertFalse(self.node.motor_health["motor_enabled"])
        self.assertGreater(self.node.motor_health["updated_at"], 0.0)

    def test_malformed_message_does_not_raise(self):
        from types import SimpleNamespace
        self.node._on_arduino_diagnostics(SimpleNamespace(status=None))
        self.node._on_arduino_diagnostics(SimpleNamespace())


if __name__ == "__main__":
    unittest.main()
