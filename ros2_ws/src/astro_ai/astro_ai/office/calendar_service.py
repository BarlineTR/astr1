"""ASTRO V1 — Office Calendar Service.

Provides seamless calendar querying, Google Calendar REST integration,
and proactive pre-meeting reminder detection.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple


class CalendarService:
    def __init__(self, storage_path: Optional[str] = None):
        if storage_path:
            self.storage_path = storage_path
        else:
            astro_dir = os.path.expanduser(os.path.join("~", ".astro"))
            os.makedirs(astro_dir, exist_ok=True)
            self.storage_path = os.path.join(astro_dir, "office_calendar.json")

        self.google_api_key = os.environ.get("GOOGLE_CALENDAR_API_KEY", "")
        self.google_calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
        self._reminded_event_ids = set()

        self._ensure_storage_initialized()

    def _ensure_storage_initialized(self):
        """Seeds default office events if storage file is missing or empty."""
        if not os.path.exists(self.storage_path) or os.path.getsize(self.storage_path) == 0:
            now = datetime.now()
            # Seed 2 realistic events for today
            seed_events = [
                {
                    "id": "evt_sprint_review",
                    "title": "Haftalık Sprint Değerlendirmesi",
                    "start_time": (now + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M"),
                    "duration_minutes": 45,
                    "location": "Toplantı Odası A",
                    "organizer": "Baran",
                    "attendees": ["Baran", "Selin", "Ahmet"],
                    "description": "Yeni robotik ve arayüz geliştirmelerinin değerlendirilmesi."
                },
                {
                    "id": "evt_arch_sync",
                    "title": "Astro Sistem Mimarisi İncelemesi",
                    "start_time": (now + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"),
                    "duration_minutes": 60,
                    "location": "Lobi / Ar-Ge Alanı",
                    "organizer": "Baran",
                    "attendees": ["Baran", "Yapay Zeka Ekibi"],
                    "description": "ROS2 ve LLM gerçek zamanlı gecikme optimizasyonları."
                }
            ]
            try:
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump({"events": seed_events}, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def _load_local_events(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.storage_path):
            return []
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("events", [])
        except Exception:
            return []

    def get_upcoming_events(self, hours: float = 12.0) -> List[Dict[str, Any]]:
        """Returns sorted upcoming events within specified hours."""
        events = self._load_local_events()
        now = datetime.now()
        cutoff = now + timedelta(hours=hours)

        upcoming = []
        for ev in events:
            try:
                # Handle formats like "YYYY-MM-DD HH:MM" or ISO
                st_str = ev.get("start_time", "")
                if "T" in st_str:
                    st = datetime.fromisoformat(st_str.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
                else:
                    st = datetime.strptime(st_str, "%Y-%m-%d %H:%M")

                if now - timedelta(minutes=15) <= st <= cutoff:
                    ev_copy = dict(ev)
                    ev_copy["dt_start"] = st
                    upcoming.append(ev_copy)
            except Exception:
                continue

        upcoming.sort(key=lambda x: x["dt_start"])
        return upcoming

    def get_today_summary(self) -> str:
        """Returns concise Turkish conversational summary of today's schedule."""
        events = self.get_upcoming_events(hours=14.0)
        if not events:
            return "Bugün için planlanmış herhangi bir toplantı veya etkinlik bulunmuyor."

        lines = [f"Bugün toplam {len(events)} etkinlik bulunuyor:"]
        for ev in events:
            time_part = ev["dt_start"].strftime("%H:%M")
            title = ev.get("title", "Toplantı")
            loc = ev.get("location", "")
            loc_str = f" ({loc})" if loc else ""
            lines.append(f"- Saat {time_part}: {title}{loc_str}")

        return "\n".join(lines)

    def is_employee_in_meeting(self, employee_name: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Checks if employee is currently in a meeting or one is ending soon."""
        now = datetime.now()
        events = self._load_local_events()
        low_name = employee_name.lower()

        for ev in events:
            try:
                st = datetime.strptime(ev["start_time"], "%Y-%m-%d %H:%M")
                dur = ev.get("duration_minutes", 30)
                end = st + timedelta(minutes=dur)

                attendees = [a.lower() for a in ev.get("attendees", [])]
                organizer = ev.get("organizer", "").lower()

                if low_name in organizer or any(low_name in a for a in attendees):
                    # Currently in meeting or ending within 10 minutes
                    if st <= now <= end:
                        return True, ev
                    # If meeting starts in <= 15 minutes:
                    if timedelta(0) <= (st - now) <= timedelta(minutes=15):
                        return True, ev
            except Exception:
                continue

        return False, None

    def check_meeting_reminders(self, lead_minutes: int = 10) -> List[Dict[str, Any]]:
        """Returns meetings starting within lead_minutes that haven't been reminded yet."""
        now = datetime.now()
        events = self.get_upcoming_events(hours=2.0)
        reminders_due = []

        for ev in events:
            ev_id = ev.get("id", ev.get("title", ""))
            if ev_id in self._reminded_event_ids:
                continue

            dt_start = ev.get("dt_start")
            if not dt_start:
                continue

            diff = (dt_start - now).total_seconds() / 60.0
            # Trigger reminder if within lead window, e.g. between 0 and lead_minutes + 1
            if 0.0 <= diff <= (lead_minutes + 1.0):
                self._reminded_event_ids.add(ev_id)
                reminders_due.append({
                    "event_id": ev_id,
                    "title": ev.get("title", "Toplantı"),
                    "minutes_left": int(round(max(1.0, diff))),
                    "location": ev.get("location", "Toplantı Odası"),
                    "attendees": ev.get("attendees", []),
                    "organizer": ev.get("organizer", "Ekip")
                })

        return reminders_due

    def add_event(
        self,
        title: str,
        start_time_str: str,
        duration_minutes: int = 30,
        location: str = "Ofis",
        organizer: str = "Baran",
        attendees: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Adds an event to local storage."""
        events = self._load_local_events()
        new_event = {
            "id": f"evt_{int(time.time())}",
            "title": title,
            "start_time": start_time_str,
            "duration_minutes": duration_minutes,
            "location": location,
            "organizer": organizer,
            "attendees": attendees or [organizer]
        }
        events.append(new_event)
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump({"events": events}, f, ensure_ascii=False, indent=2)
            return {"status": "success", "event": new_event}
        except Exception as e:
            return {"status": "error", "message": str(e)}
