"""ASTRO V1 — Office Automation & Autonomous Concierge Test Suite.

Verifies:
  1. CalendarService: event retrieval, daily summary, pre-meeting reminders.
  2. SlackService: visitor arrival notification, command parsing.
  3. OfficeConciergeManager: LiDAR 1.5 - 2.0m entrance detection, head nod gesture,
     unknown visitor vs known person greetings, host status check.
  4. AstroRealtimeNode tool integration: check_calendar_events, notify_via_slack.
"""

import json
import os
import sys
import unittest
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# Ensure test import paths
pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for p in [
    os.path.join(pkg_root, "astro_ai"),
    os.path.join(pkg_root, "astro_ai", "astro_ai"),
    os.path.join(pkg_root, "astro_audio"),
    os.path.join(pkg_root, "astro_audio", "astro_audio"),
    os.path.join(pkg_root, "astro_vision"),
    os.path.join(pkg_root, "astro_vision", "astro_vision"),
    os.path.join(pkg_root, "astro_base"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

from astro_ai.office.calendar_service import CalendarService
from astro_ai.office.slack_service import SlackService
from astro_ai.office.office_concierge import OfficeConciergeManager
from astro_ai.astro_realtime_node import AstroRealtimeNode


class TestOfficeCalendarAndSlack(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.test_dir = tempfile.mkdtemp()
        self.cal_file = os.path.join(self.test_dir, "test_calendar.json")
        self.calendar = CalendarService(storage_path=self.cal_file)
        self.calendar.seed_demo_events()
        self.slack = SlackService()

    def test_01_calendar_summary_and_employee_meeting_status(self):
        summary = self.calendar.get_today_summary()
        self.assertIn("Bugün toplam", summary)
        self.assertIn("Sprint", summary)

        # Host Baran meeting status
        in_meeting, ev = self.calendar.is_employee_in_meeting("Baran")
        self.assertTrue(in_meeting)
        self.assertIsNotNone(ev)

    def test_02_pre_meeting_proactive_reminder(self):
        # Add an event starting in 8 minutes
        now = datetime.now()
        self.calendar.add_event(
            title="Tasarım Değerlendirmesi",
            start_time_str=(now + timedelta(minutes=8)).strftime("%Y-%m-%d %H:%M"),
            duration_minutes=30,
            location="Oda B",
            organizer="Baran"
        )

        reminders = self.calendar.check_meeting_reminders(lead_minutes=10)
        self.assertGreaterEqual(len(reminders), 1)
        titles = [r["title"] for r in reminders]
        self.assertTrue(any("Tasarım" in t or "Sprint" in t for t in titles))

        # Check deduplication: second check immediately should NOT re-trigger the same events
        reminders_second = self.calendar.check_meeting_reminders(lead_minutes=10)
        self.assertEqual(len(reminders_second), 0)

    def test_03_slack_visitor_notification_and_command_parsing(self):
        res = self.slack.notify_visitor_arrival(
            employee_name="Baran",
            visitor_name="Selin Hanım",
            note="Proje görüşmesi"
        )
        self.assertEqual(res["status"], "success")
        self.assertTrue(res.get("delivered"))
        self.assertEqual(len(self.slack.sent_messages_history), 1)

        # Command parsing
        p1 = self.slack.parse_incoming_command("/astro gel baran_masa")
        self.assertEqual(p1["action"], "navigate_to")
        self.assertEqual(p1["target"], "baran_masa")

        p2 = self.slack.parse_incoming_command("/astro durum")
        self.assertEqual(p2["action"], "report_status")

        p3 = self.slack.parse_incoming_command('{"command": "come_to_desk", "target": "ahmet_masa"}')
        self.assertEqual(p3["action"], "come_to_desk")


class TestOfficeConcierge(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.test_dir = tempfile.mkdtemp()
        self.cal_file = os.path.join(self.test_dir, "test_calendar.json")
        self.calendar = CalendarService(storage_path=self.cal_file)
        self.calendar.seed_demo_events()
        self.slack = SlackService()
        self.concierge = OfficeConciergeManager(
            calendar_service=self.calendar,
            slack_service=self.slack,
            cooldown_seconds=5.0
        )

    def test_04_unknown_visitor_entrance_detection(self):
        # Simulate LiDAR ranges with 1.7m cluster at door
        ranges = [3.0] * 100
        # Forward samples: indices 0..8 and 92..99
        ranges[0] = 1.72
        ranges[1] = 1.68
        ranges[2] = 1.70
        ranges[98] = 1.75
        ranges[99] = 1.69

        action = self.concierge.evaluate_entrance_presence(
            lidar_ranges=ranges,
            recognized_identity={"is_known": False},
            is_speaking=False
        )

        self.assertIsNotNone(action)
        self.assertEqual(action["type"], "unknown_visitor_welcome")
        self.assertEqual(action["gesture"], "nod")
        self.assertIn("Hoş geldiniz! Kimi aramıştınız?", action["speech_text"])

        # Visitor responds with who they are looking for
        answer_res = self.concierge.process_visitor_answer("Baran Bey ile saat 14:00 randevum vardı")
        self.assertEqual(answer_res["status"], "notified")
        self.assertEqual(answer_res["host"], "Baran")
        self.assertIn("Baran Bey'e", answer_res["response_text"])

    def test_05_known_partner_entrance_greeting(self):
        ranges = [3.0] * 100
        ranges[0] = 1.65
        ranges[1] = 1.70
        ranges[2] = 1.68

        identity = {
            "is_known": True,
            "name": "Selin",
            "formal_title": "Selin Hanım"
        }

        action = self.concierge.evaluate_entrance_presence(
            lidar_ranges=ranges,
            recognized_identity=identity,
            is_speaking=False
        )

        self.assertIsNotNone(action)
        self.assertEqual(action["type"], "known_person_welcome")
        self.assertEqual(action["gesture"], "nod")
        self.assertIn("Selin Hanım", action["speech_text"])
        self.assertIn("Baran Bey", action["speech_text"])


class TestAstroRealtimeNodeOfficeTools(unittest.TestCase):
    @patch.dict(os.environ, {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-mock-key"})
    def setUp(self):
        import tempfile
        self.node = AstroRealtimeNode()
        # Test isolation: use a temporary calendar file with fresh seed events
        temp_dir = tempfile.mkdtemp()
        self.temp_cal = os.path.join(temp_dir, "test_node_cal.json")
        self.node.calendar_service = CalendarService(storage_path=self.temp_cal)
        self.node.calendar_service.seed_demo_events()

    def test_06_realtime_tools_check_calendar_events(self):
        res = self.node._execute_realtime_tool("check_calendar_events", {"query": "bugün"})
        self.assertEqual(res["status"], "success")
        self.assertIn("Bugün toplam", res["schedule"])

    def test_07_realtime_tools_notify_via_slack(self):
        res = self.node._execute_realtime_tool("notify_via_slack", {
            "recipient": "Baran",
            "message": "Toplantı için Selin Hanım geldi."
        })
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["recipient"], "Baran")
        self.assertTrue(res["delivered"])

    def test_08_get_events_summary_7_days(self):
        summary = self.node.calendar_service.get_events_summary(days=7, query="bu hafta")
        self.assertIn("Önümüzdeki 7 gün", summary)

    def test_09_add_and_delete_event_smart(self):
        cal = self.node.calendar_service
        # Add smart event
        add_res = cal.add_event_smart(
            title="Ahmet ile Tasarım Toplantısı",
            date_str="yarın",
            time_str="14:30",
            location="Oda C"
        )
        self.assertEqual(add_res["status"], "success")
        self.assertIn("Tasarım", add_res["event"]["title"])

        # Check it appears in upcoming
        events = cal.get_upcoming_events(hours=48)
        self.assertTrue(any("Tasarım" in e.get("title", "") for e in events))

        # Delete event
        del_res = cal.delete_event("Tasarım")
        self.assertEqual(del_res["status"], "success")
        self.assertIn("Ahmet ile Tasarım Toplantısı", del_res["deleted_title"])

    def test_10_realtime_tools_add_and_delete(self):
        # Test tool calling add_calendar_event
        res_add = self.node._execute_realtime_tool("add_calendar_event", {
            "title": "Diş Randevusu",
            "date": "önümüzdeki salı",
            "time": "15:00",
            "location": "Klinik"
        })
        self.assertEqual(res_add["status"], "success")
        self.assertIn("Diş Randevusu", res_add["title"])

        # Test tool calling delete_calendar_event
        res_del = self.node._execute_realtime_tool("delete_calendar_event", {
            "query": "Diş Randevusu"
        })
        self.assertEqual(res_del["status"], "success")
        self.assertIn("kaldırıldı", res_del["message"])

    def test_11_realtime_tools_update_calendar_event(self):
        # Add an initial event
        self.node.calendar_service.add_event_smart(
            title="Sistem Planlama",
            date_str="bugün",
            time_str="11:00",
            location="Oda 1"
        )
        # Update event via tool call
        res_upd = self.node._execute_realtime_tool("update_calendar_event", {
            "query": "Sistem Planlama",
            "new_time": "16:00",
            "new_location": "Büyük Konferans Salonu"
        })
        self.assertEqual(res_upd["status"], "success")
        self.assertIn("güncellendi", res_upd["message"])
        self.assertEqual(res_upd["event"]["location"], "Büyük Konferans Salonu")
        self.assertIn("16:00", res_upd["event"]["start_time"])

    def test_12_reminder_lifecycle_and_due_alert(self):
        # 1. Set reminder via tool (clear any previous in-memory reminders for test isolation)
        self.node._reminders.clear()
        res_rem = self.node._execute_realtime_tool("set_reminder", {
            "minutes": 5.0,
            "topic": "çay içeceğim"
        })
        self.assertEqual(res_rem["status"], "success")
        self.assertEqual(res_rem["minutes"], 5.0)
        self.assertEqual(res_rem["topic"], "çay içeceğim")
        self.assertEqual(len(self.node._reminders), 1)

        # 2. Check persistence in memory profile
        persisted = self.node.memory.profile.get_active_reminders()
        self.assertGreaterEqual(len(persisted), 1)
        self.assertTrue(any("çay içeceğim" in r.get("reminder_text", "") for r in persisted))

        # 3. Simulate due time arrived
        self.node._reminders[0]["due_time"] = time.monotonic() - 1.0

        # 4. Trigger _check_reminders and verify speech output is invoked (not blocked by proactive_speech_enabled)
        tts_messages = []
        self.node.pub_tts = MagicMock()
        self.node.pub_tts.publish = lambda msg: tts_messages.append(msg.data)
        
        self.node._check_reminders()
        self.assertEqual(len(self.node._reminders), 0)
        self.assertGreaterEqual(len(tts_messages), 1)
        self.assertIn("çay içeceğim", tts_messages[0])

    def test_13_google_calendar_ical_integration(self):
        cal = self.node.calendar_service
        cal.google_ical_url = (
            "https://calendar.google.com/calendar/ical/"
            "7953b2fc68f9a7f3efb93736c65c67c4c2bb91b66f05eb9287bec4a31f9783d0%40group.calendar.google.com/"
            "private-6e5454dd9d2f21dbff4c43ad7cc4633d/basic.ics"
        )
        # Verify calendar ID derivation
        import re, urllib.parse
        m = re.search(r"/calendar/ical/([^/]+)/", cal.google_ical_url)
        self.assertIsNotNone(m)
        self.assertEqual(
            urllib.parse.unquote(m.group(1)),
            "7953b2fc68f9a7f3efb93736c65c67c4c2bb91b66f05eb9287bec4a31f9783d0@group.calendar.google.com"
        )

        sample_ics = (
            "BEGIN:VCALENDAR\r\n"
            "PRODID:-//Google Inc//Google Calendar 70.9054//EN\r\n"
            "VERSION:2.0\r\n"
            "X-WR-CALNAME:ast1\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:sample_gcal_001@google.com\r\n"
            "SUMMARY:Astro Ekip\r\n"
            "  Senkronizasyonu\r\n"
            "DESCRIPTION:Proje detaylari ve\r\n"
            "  yol haritasi\r\n"
            "LOCATION:Ar-Ge Odasi\r\n"
            "DTSTART:20260925T110000Z\r\n"
            "DTEND:20260925T120000Z\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR"
        )

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = sample_ics.encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            # 1. Fetch and parse with force_refresh
            events = cal._fetch_google_ical_events(force_refresh=True)
            self.assertEqual(len(events), 1)
            ev = events[0]
            self.assertEqual(ev["title"], "Astro Ekip Senkronizasyonu")
            self.assertEqual(ev["location"], "Ar-Ge Odasi")
            self.assertEqual(ev["id"], "sample_gcal_001@google.com")
            self.assertEqual(ev["duration_minutes"], 60)

            # 2. Test cache: second call does not invoke urlopen
            mock_urlopen.reset_mock()
            cached_events = cal._fetch_google_ical_events(force_refresh=False)
            self.assertEqual(len(cached_events), 1)
            mock_urlopen.assert_not_called()

            # 3. Test deleting an iCal event masks it locally
            del_res = cal.delete_event("Astro Ekip")
            self.assertEqual(del_res["status"], "success")
            self.assertIn("Astro Ekip Senkronizasyonu", del_res["deleted_title"])

            # 4. Verify it is now masked from upcoming events
            upcoming = cal.get_upcoming_events(hours=48)
            self.assertFalse(any(e.get("id") == "sample_gcal_001@google.com" for e in upcoming))

    def test_14_clean_empty_calendar_by_default(self):
        # Verify that without seed_demo_events, calendar starts completely empty
        import tempfile
        tmp_dir = tempfile.mkdtemp()
        fresh_cal_path = os.path.join(tmp_dir, "empty_cal.json")
        clean_cal = CalendarService(storage_path=fresh_cal_path)

        events = clean_cal.get_upcoming_events(hours=24)
        self.assertEqual(len(events), 0)

        summary = clean_cal.get_today_summary()
        self.assertIn("bulunmuyor", summary)

        reminders = clean_cal.check_meeting_reminders(lead_minutes=10)
        self.assertEqual(len(reminders), 0)


if __name__ == "__main__":
    unittest.main()


