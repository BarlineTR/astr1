#!/usr/bin/env python3
"""Comprehensive test suite for ASTRO Social Robot Modes (Office Greeter & Restaurant Host).

Verifies:
1. WaypointManager: loading, alias resolution, Turkish text normalization, home resolution.
2. SocialEscortController: lifecycle, proxemics distance checks, wait/resume, arrival, timeout.
3. ActionManager navigation integration: execute_navigate, execute_escort, list_destinations, execute_intent.
4. PersonaEngine ROBOT_MODE prompt synthesis and tool schemas.
"""

import os
import unittest
from unittest.mock import MagicMock

from astro_ai.navigation.waypoint_manager import WaypointManager, _normalize_text
from astro_ai.navigation.social_escort import SocialEscortController, EscortState
from astro_ai.action_manager import ActionManager, ActionResult
from astro_ai.persona_engine import PersonaEngine, ROBOT_TOOLS


class TestSocialRobotModes(unittest.TestCase):

    def setUp(self):
        self._orig_mode = os.environ.get("ROBOT_MODE")

    def tearDown(self):
        if self._orig_mode is not None:
            os.environ["ROBOT_MODE"] = self._orig_mode
        else:
            os.environ.pop("ROBOT_MODE", None)

    # ── 1. WaypointManager Tests ──────────────────────────────────────────

    def test_text_normalization(self):
        self.assertEqual(_normalize_text("Toplantı Odası A!"), "toplanti odasi a")
        self.assertEqual(_normalize_text("  Çay Ocağı & Dinlenme  "), "cay ocagi dinlenme")
        self.assertEqual(_normalize_text("MASA 2 (Cam Kenarı)"), "masa 2 cam kenari")

    def test_office_waypoints_loading_and_resolution(self):
        mgr = WaypointManager(mode="office")
        self.assertEqual(mgr.mode, "office")
        self.assertGreaterEqual(len(mgr.waypoints), 5)

        # Exact and alias matches
        wp_reception = mgr.resolve("danışma")
        self.assertIsNotNone(wp_reception)
        self.assertEqual(wp_reception.key, "reception")

        wp_meeting_a = mgr.resolve("Toplantı Odası A")
        self.assertIsNotNone(wp_meeting_a)
        self.assertEqual(wp_meeting_a.key, "meeting_room_a")
        self.assertAlmostEqual(wp_meeting_a.x, 4.5)
        self.assertAlmostEqual(wp_meeting_a.y, 2.0)

        wp_kitchen = mgr.resolve("çay ocağı")
        self.assertIsNotNone(wp_kitchen)
        self.assertEqual(wp_kitchen.key, "kitchen")

        wp_manager = mgr.resolve("müdür odası")
        self.assertIsNotNone(wp_manager)
        self.assertEqual(wp_manager.key, "manager_office")

        # Home waypoint
        home = mgr.get_home()
        self.assertIsNotNone(home)
        self.assertEqual(home.key, "reception")

    def test_restaurant_waypoints_loading_and_resolution(self):
        mgr = WaypointManager(mode="restaurant")
        self.assertEqual(mgr.mode, "restaurant")
        self.assertGreaterEqual(len(mgr.waypoints), 5)

        # Table resolution
        wp_t1 = mgr.resolve("Masa 1")
        self.assertIsNotNone(wp_t1)
        self.assertEqual(wp_t1.key, "table_1")

        wp_t2 = mgr.resolve("ikinci masa")
        self.assertIsNotNone(wp_t2)
        self.assertEqual(wp_t2.key, "table_2")

        wp_cashier = mgr.resolve("hesap ödeme")
        self.assertIsNotNone(wp_cashier)
        self.assertEqual(wp_cashier.key, "cashier")

        wp_bar = mgr.resolve("kokteyl barı")
        self.assertIsNotNone(wp_bar)
        self.assertEqual(wp_bar.key, "bar")

        # Nonexistent
        self.assertIsNone(mgr.resolve("uzay üssü"))

    # ── 2. SocialEscortController Tests ───────────────────────────────────

    def test_escort_lifecycle_normal_following(self):
        mgr = WaypointManager(mode="office")
        wp = mgr.resolve("meeting_room_a")
        self.assertIsNotNone(wp)

        escort = SocialEscortController()
        t0 = 100.0

        # Start
        start_res = escort.start_escort(wp, now=t0)
        self.assertEqual(start_res.state, EscortState.NAVIGATING)
        self.assertIn("Toplantı Odası A", start_res.speech_prompt)
        self.assertEqual(start_res.desired_speed_factor, 1.0)

        # Normal following: guest at 2.0m (ideal zone)
        step1 = escort.update(human_distance_m=2.0, nav_reached=False, now=t0 + 2.0)
        self.assertEqual(step1.state, EscortState.NAVIGATING)
        self.assertEqual(step1.desired_speed_factor, 1.0)

        # Destination reached
        step_arr = escort.update(human_distance_m=1.8, nav_reached=True, now=t0 + 10.0)
        self.assertEqual(step_arr.state, EscortState.ARRIVED)
        self.assertTrue(step_arr.is_complete)
        self.assertIn("Toplantı Odası A", step_arr.speech_prompt)

    def test_escort_proxemics_wait_and_resume(self):
        mgr = WaypointManager(mode="restaurant")
        wp = mgr.resolve("table_2")
        escort = SocialEscortController(stop_wait_distance_m=3.5, resume_distance_m=2.0)
        t0 = 200.0

        escort.start_escort(wp, now=t0)

        # Guest falls behind: distance 4.2m (> 3.5m)
        step_lag = escort.update(human_distance_m=4.2, nav_reached=False, now=t0 + 3.0)
        self.assertEqual(step_lag.state, EscortState.WAITING_FOR_GUEST)
        self.assertEqual(step_lag.desired_speed_factor, 0.0)
        self.assertIsNotNone(step_lag.head_yaw_hint_deg)  # Head looks back
        self.assertIn("bekliyorum", step_lag.speech_prompt)

        # Still waiting at t0 + 5.0s
        step_wait = escort.update(human_distance_m=3.8, nav_reached=False, now=t0 + 5.0)
        self.assertEqual(step_wait.state, EscortState.WAITING_FOR_GUEST)
        self.assertEqual(step_wait.desired_speed_factor, 0.0)

        # Guest catches up: distance 1.6m (<= 2.0m)
        step_resume = escort.update(human_distance_m=1.6, nav_reached=False, now=t0 + 7.0)
        self.assertEqual(step_resume.state, EscortState.NAVIGATING)
        self.assertEqual(step_resume.desired_speed_factor, 1.0)

    def test_escort_timeout_aborts(self):
        mgr = WaypointManager(mode="office")
        wp = mgr.resolve("kitchen")
        escort = SocialEscortController(max_wait_timeout_s=15.0)
        t0 = 300.0

        escort.start_escort(wp, now=t0)
        # Guest lost
        escort.update(human_distance_m=None, nav_reached=False, now=t0 + 5.0)
        # Exceed timeout (t0 + 5s + 16s = t0 + 21s)
        step_abort = escort.update(human_distance_m=None, nav_reached=False, now=t0 + 22.0)
        self.assertEqual(step_abort.state, EscortState.ABORTED)
        self.assertTrue(step_abort.is_complete)

    # ── 3. ActionManager Navigation Integration ───────────────────────────

    def test_action_manager_execute_navigate(self):
        os.environ["ROBOT_MODE"] = "office"
        action_mgr = ActionManager()

        # Valid destination
        res_ok = action_mgr.execute_navigate(destination="Toplantı Odası B")
        self.assertTrue(res_ok.success)
        self.assertEqual(res_ok.action, "navigate_to_location")
        self.assertIn("Toplantı Odası B", res_ok.message)

        # Invalid destination
        res_fail = action_mgr.execute_navigate(destination="Mars Krateri")
        self.assertFalse(res_fail.success)
        self.assertEqual(res_fail.error_code, "DESTINATION_NOT_FOUND")

    def test_action_manager_execute_escort(self):
        os.environ["ROBOT_MODE"] = "restaurant"
        action_mgr = ActionManager()

        res = action_mgr.execute_escort(destination="Masa 4")
        self.assertTrue(res.success)
        self.assertEqual(res.action, "escort_guest")
        self.assertIn("Masa 4", res.message)

    def test_action_manager_list_destinations(self):
        os.environ["ROBOT_MODE"] = "restaurant"
        action_mgr = ActionManager()

        dests = action_mgr.list_destinations()
        self.assertEqual(dests["status"], "success")
        self.assertEqual(dests["mode"], "restaurant")
        self.assertGreaterEqual(dests["count"], 5)

    def test_action_manager_intent_routing(self):
        os.environ["ROBOT_MODE"] = "office"
        action_mgr = ActionManager()

        mock_intent_nav = MagicMock()
        mock_intent_nav.action_type = "navigate_to_location"
        mock_intent_nav.parameters = {"destination": "mutfak"}
        mock_intent_nav.intent_id = "intent_nav_1"

        res = action_mgr.execute_intent(mock_intent_nav)
        self.assertTrue(res.success)
        self.assertEqual(res.action, "navigate_to_location")

        mock_intent_escort = MagicMock()
        mock_intent_escort.action_type = "escort_guest"
        mock_intent_escort.parameters = {"destination": "reception"}
        mock_intent_escort.intent_id = "intent_escort_1"

        res_esc = action_mgr.execute_intent(mock_intent_escort)
        self.assertTrue(res_esc.success)
        self.assertEqual(res_esc.action, "escort_guest")

    # ── 4. PersonaEngine & Tools Schemas ──────────────────────────────────

    def test_robot_tools_schema_includes_navigation(self):
        tool_names = [t["function"]["name"] for t in ROBOT_TOOLS]
        self.assertIn("navigate_to_location", tool_names)
        self.assertIn("escort_guest", tool_names)
        self.assertIn("list_available_destinations", tool_names)

    def test_persona_engine_prompt_mode_injection(self):
        engine = PersonaEngine()

        # Office mode
        os.environ["ROBOT_MODE"] = "office"
        prompt_office = engine.build_system_prompt()
        self.assertIn("OFİS KARŞILAMA VE REHBERLİK GÖREV TALİMATI", prompt_office)
        self.assertIn("escort_guest", prompt_office)

        # Restaurant mode
        os.environ["ROBOT_MODE"] = "restaurant"
        prompt_restaurant = engine.build_system_prompt()
        self.assertIn("RESTORAN KARŞILAMA VE MASA REFAKAT TALİMATI", prompt_restaurant)
        self.assertIn("escort_guest", prompt_restaurant)

        # General mode (default)
        os.environ["ROBOT_MODE"] = ""
        prompt_general = engine.build_system_prompt()
        self.assertNotIn("OFİS KARŞILAMA VE REHBERLİK GÖREV TALİMATI", prompt_general)
        self.assertNotIn("RESTORAN KARŞILAMA VE MASA REFAKAT TALİMATI", prompt_general)


if __name__ == "__main__":
    unittest.main()
