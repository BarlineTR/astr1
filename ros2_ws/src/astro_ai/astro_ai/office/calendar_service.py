"""ASTRO V1 — Office Calendar Service.

Provides seamless calendar querying, Google Calendar REST integration,
and proactive pre-meeting reminder detection.
"""

import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from dotenv import find_dotenv, load_dotenv
    _env_path = find_dotenv(usecwd=True)
    if _env_path:
        load_dotenv(dotenv_path=_env_path)
    else:
        _repo_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".env"))
        if os.path.exists(_repo_env):
            load_dotenv(dotenv_path=_repo_env)
except Exception:
    pass


class CalendarService:
    def __init__(self, storage_path: Optional[str] = None):
        if storage_path:
            self.storage_path = storage_path
        else:
            astro_dir = os.path.expanduser(os.path.join("~", ".astro"))
            os.makedirs(astro_dir, exist_ok=True)
            self.storage_path = os.path.join(astro_dir, "office_calendar.json")

        self.google_api_key = os.environ.get("GOOGLE_CALENDAR_API_KEY", "")
        self.google_calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "") or "primary"
        self.google_ical_url = os.environ.get("GOOGLE_CALENDAR_ICAL_URL", "")
        self.google_access_token = os.environ.get("GOOGLE_CALENDAR_ACCESS_TOKEN", os.environ.get("GOOGLE_ACCESS_TOKEN", ""))
        self._reminded_event_ids = set()
        self._ical_cache: List[Dict[str, Any]] = []
        self._ical_cache_time: float = 0.0

        # Auto-derive calendar ID from secret iCal URL if not explicitly configured
        if (not self.google_calendar_id or self.google_calendar_id == "primary") and self.google_ical_url:
            m = re.search(r"/calendar/ical/([^/]+)/", self.google_ical_url)
            if m:
                extracted = urllib.parse.unquote(m.group(1))
                if extracted and ("@" in extracted or "." in extracted):
                    self.google_calendar_id = extracted

        self._ensure_storage_initialized()

    def _ensure_storage_initialized(self):
        """Initializes storage file. Never injects unsolicited mock events into user calendar; purges any legacy demo seeds."""
        if not os.path.exists(self.storage_path) or os.path.getsize(self.storage_path) == 0:
            try:
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump({"events": [], "deleted_event_ids": []}, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            return

        # Purge any legacy mock seed events from existing storage
        try:
            data = self._load_local_data()
            events = data.get("events", [])
            cleaned = [
                ev for ev in events
                if str(ev.get("id", "")) not in ("evt_sprint_review", "evt_arch_sync")
                and ev.get("title") not in ("Haftalık Sprint Değerlendirmesi", "Astro Sistem Mimarisi İncelemesi")
            ]
            if len(cleaned) != len(events):
                data["events"] = cleaned
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def seed_demo_events(self):
        """Explicitly seeds demo events when requested by automated test suites or sandbox demos."""
        now = datetime.now()
        default_owner = os.environ.get("ASTRO_OWNER_NAME", "Kullanıcı")
        seed_events = [
            {
                "id": "evt_sprint_review",
                "title": "Haftalık Sprint Değerlendirmesi",
                "start_time": (now + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M"),
                "duration_minutes": 45,
                "location": "Toplantı Odası A",
                "organizer": default_owner,
                "attendees": list(dict.fromkeys([default_owner, "Baran", "Selin", "Ahmet"])),
                "description": "Yeni robotik ve arayüz geliştirmelerinin değerlendirilmesi."
            },
            {
                "id": "evt_arch_sync",
                "title": "Astro Sistem Mimarisi İncelemesi",
                "start_time": (now + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"),
                "duration_minutes": 60,
                "location": "Lobi / Ar-Ge Alanı",
                "organizer": default_owner,
                "attendees": list(dict.fromkeys([default_owner, "Baran", "Yapay Zeka Ekibi"])),
                "description": "ROS2 ve LLM gerçek zamanlı gecikme optimizasyonları."
            }
        ]
        data = self._load_local_data()
        data["events"] = seed_events
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_local_data(self) -> Dict[str, Any]:
        if not os.path.exists(self.storage_path):
            return {"events": [], "deleted_event_ids": []}
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return {"events": data, "deleted_event_ids": []}
                return data
        except Exception:
            return {"events": [], "deleted_event_ids": []}

    def _load_local_events(self) -> List[Dict[str, Any]]:
        return self._load_local_data().get("events", [])

    def _load_deleted_ids(self) -> set:
        return set(self._load_local_data().get("deleted_event_ids", []))

    def _fetch_google_rest_events(self) -> List[Dict[str, Any]]:
        """Fetches upcoming events via Google Calendar v3 REST API (if key and calendar ID provided)."""
        if not self.google_api_key or not self.google_calendar_id:
            return []
        import urllib.request
        import urllib.parse
        now_iso = datetime.now(timezone.utc).isoformat()
        cal_id = urllib.parse.quote(self.google_calendar_id)
        url = (
            f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events"
            f"?key={self.google_api_key}&timeMin={now_iso}&singleEvents=true&orderBy=startTime&maxResults=15"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AstroV1-OfficeBot"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])
                events = []
                for it in items:
                    st_val = it.get("start", {}).get("dateTime", it.get("start", {}).get("date", ""))
                    title = it.get("summary", "Toplantı")
                    loc = it.get("location", "Ofis")
                    attendees = [a.get("displayName", a.get("email", "")) for a in it.get("attendees", [])]
                    events.append({
                        "id": it.get("id"),
                        "title": title,
                        "start_time": st_val,
                        "duration_minutes": 30,
                        "location": loc,
                        "organizer": it.get("organizer", {}).get("displayName", "Ekip"),
                        "attendees": attendees
                    })
                return events
        except Exception:
            return []

    def _fetch_google_ical_events(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Fetches upcoming events via Google Calendar Secret iCal Feed URL (Zero API Key needed!)."""
        if not self.google_ical_url:
            return []

        # Return cached events if fresh (< 60s)
        if not force_refresh and self._ical_cache and (time.time() - self._ical_cache_time < 60.0):
            return self._ical_cache

        import urllib.request
        try:
            req = urllib.request.Request(self.google_ical_url, headers={"User-Agent": "AstroV1-OfficeBot"})
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                content = resp.read().decode("utf-8", errors="ignore")

            # RFC 5545 Line Unfolding: lines starting with space/tab are continuations
            unfolded_lines = []
            for raw_line in content.splitlines():
                if raw_line.startswith((" ", "\t")) and unfolded_lines:
                    unfolded_lines[-1] += raw_line[1:]
                else:
                    unfolded_lines.append(raw_line)

            def _unescape_ical(text: str) -> str:
                return (
                    text.replace("\\n", "\n")
                    .replace("\\N", "\n")
                    .replace("\\,", ",")
                    .replace("\\;", ";")
                    .replace("\\\\", "\\")
                    .strip()
                )

            events = []
            cur_event = None
            for raw_unfolded in unfolded_lines:
                line = raw_unfolded.strip()
                if line == "BEGIN:VEVENT":
                    cur_event = {}
                elif line == "END:VEVENT" and cur_event is not None:
                    if "title" in cur_event and "start_time" in cur_event:
                        events.append(cur_event)
                    cur_event = None
                elif cur_event is not None:
                    if line.startswith("SUMMARY:"):
                        cur_event["title"] = _unescape_ical(line[8:])
                    elif line.startswith("LOCATION:"):
                        cur_event["location"] = _unescape_ical(line[9:])
                    elif line.startswith("DESCRIPTION:"):
                        cur_event["description"] = _unescape_ical(line[12:])
                    elif line.startswith("UID:"):
                        cur_event["id"] = line[4:].strip()
                    elif line.startswith("DTSTART"):
                        val_raw = line.split(":")[-1].strip()
                        is_utc = val_raw.endswith("Z")
                        val = val_raw.replace("Z", "")
                        try:
                            if len(val) == 8 and val.isdigit():
                                dt = datetime.strptime(val, "%Y%m%d")
                                cur_event["start_time"] = dt.strftime("%Y-%m-%d 09:00")
                            else:
                                dt = datetime.strptime(val[:15], "%Y%m%dT%H%M%S")
                                if is_utc:
                                    # Convert UTC to local system time (e.g. Europe/Istanbul UTC+3)
                                    dt = dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
                                cur_event["start_time"] = dt.strftime("%Y-%m-%d %H:%M")
                            if "duration_minutes" not in cur_event:
                                cur_event["duration_minutes"] = 45
                            cur_event["organizer"] = "Google Takvim"
                            if "id" not in cur_event:
                                cur_event["id"] = f"ical_{val[:15]}_{abs(hash(cur_event.get('title', '')))}"
                        except Exception:
                            pass
                    elif line.startswith("DTEND"):
                        val_raw = line.split(":")[-1].strip()
                        is_utc = val_raw.endswith("Z")
                        val = val_raw.replace("Z", "")
                        try:
                            if len(val) >= 15 and "start_time" in cur_event:
                                dt_end = datetime.strptime(val[:15], "%Y%m%dT%H%M%S")
                                if is_utc:
                                    dt_end = dt_end.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
                                dt_start = datetime.strptime(cur_event["start_time"], "%Y-%m-%d %H:%M")
                                dur = int((dt_end - dt_start).total_seconds() / 60.0)
                                if dur > 0:
                                    cur_event["duration_minutes"] = dur
                        except Exception:
                            pass

            self._ical_cache = events
            self._ical_cache_time = time.time()
            return events
        except Exception:
            return self._ical_cache or []

    def _google_rest_headers(self) -> Dict[str, str]:
        headers = {"User-Agent": "AstroV1-OfficeBot", "Content-Type": "application/json"}
        if self.google_access_token:
            headers["Authorization"] = f"Bearer {self.google_access_token}"
        return headers

    def _google_rest_insert_event(self, event_data: Dict[str, Any]) -> Optional[str]:
        """Creates event on Google Calendar via v3 REST API if access token and calendar ID are set."""
        if not self.google_access_token or not self.google_calendar_id:
            return None
        import urllib.request
        import urllib.parse
        cal_id = urllib.parse.quote(self.google_calendar_id)
        url = f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events"

        st_str = event_data.get("start_time", "")
        dur = event_data.get("duration_minutes", 30)
        try:
            if "T" in st_str:
                st_dt = datetime.fromisoformat(st_str.replace("Z", "+00:00")).replace(tzinfo=None)
            else:
                st_dt = datetime.strptime(st_str, "%Y-%m-%d %H:%M")
            end_dt = st_dt + timedelta(minutes=dur)
            st_iso = st_dt.isoformat()
            end_iso = end_dt.isoformat()
        except Exception:
            return None

        body = {
            "summary": event_data.get("title", "Toplantı"),
            "location": event_data.get("location", "Ofis"),
            "description": event_data.get("description", "Astro Sosyal Robot tarafından oluşturuldu."),
            "start": {"dateTime": f"{st_iso}+03:00" if "+" not in st_iso else st_iso},
            "end": {"dateTime": f"{end_iso}+03:00" if "+" not in end_iso else end_iso},
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers=self._google_rest_headers(),
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                return res_data.get("id")
        except Exception:
            return None

    def _google_rest_patch_event(self, google_event_id: str, patch_data: Dict[str, Any]) -> bool:
        """Updates event on Google Calendar via v3 REST API."""
        if not self.google_access_token or not self.google_calendar_id or not google_event_id:
            return False
        import urllib.request
        import urllib.parse
        cal_id = urllib.parse.quote(self.google_calendar_id)
        ev_id = urllib.parse.quote(google_event_id)
        url = f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events/{ev_id}"
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(patch_data).encode("utf-8"),
                headers=self._google_rest_headers(),
                method="PATCH"
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                return resp.status in (200, 204)
        except Exception:
            return False

    def _google_rest_delete_event(self, google_event_id: str) -> bool:
        """Deletes event from Google Calendar via v3 REST API."""
        if not self.google_access_token or not self.google_calendar_id or not google_event_id:
            return False
        import urllib.request
        import urllib.parse
        cal_id = urllib.parse.quote(self.google_calendar_id)
        ev_id = urllib.parse.quote(google_event_id)
        url = f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events/{ev_id}"
        try:
            req = urllib.request.Request(
                url,
                headers=self._google_rest_headers(),
                method="DELETE"
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                return resp.status in (200, 204)
        except Exception:
            return False

    def get_upcoming_events(self, hours: float = 12.0) -> List[Dict[str, Any]]:
        """Returns sorted upcoming events merged across Google Calendar (REST or iCal) and local storage."""
        # 1. Collect from Google Calendar (if configured)
        google_events = self._fetch_google_ical_events() or self._fetch_google_rest_events()

        # 2. Collect from local JSON storage
        local_events = self._load_local_events()
        deleted_ids = self._load_deleted_ids()

        # Merge with deduplication (by event id or title+start_time)
        all_events = []
        seen_keys = set()

        for ev in (google_events + local_events):
            ev_id = str(ev.get("id", ""))
            t_key = f"{ev.get('title')}_{ev.get('start_time')}"
            if (ev_id and ev_id in deleted_ids) or (t_key in deleted_ids):
                continue
            if t_key not in seen_keys:
                seen_keys.add(t_key)
                all_events.append(ev)

        now = datetime.now()
        cutoff = now + timedelta(hours=hours)

        upcoming = []
        for ev in all_events:
            try:
                st_str = ev.get("start_time", "")
                if "T" in st_str:
                    st = datetime.fromisoformat(st_str.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
                else:
                    st = datetime.strptime(st_str, "%Y-%m-%d %H:%M")

                dur = ev.get("duration_minutes", 30)
                end = st + timedelta(minutes=dur)

                # Include if currently in-progress (st <= now <= end) or starting within window
                if (st <= now <= end) or (now <= st <= cutoff) or (now - timedelta(minutes=15) <= st <= cutoff):
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

    def get_events_summary(self, days: int = 7, query: str = "") -> str:
        """Returns structured Turkish summary of events for specified days (e.g. 7 days / this week)."""
        q_low = (query or "").lower().strip()
        if "bugün" in q_low or "bugun" in q_low:
            return self.get_today_summary()

        hours = float(max(1, days) * 24)
        events = self.get_upcoming_events(hours=hours)

        if q_low and q_low not in ("bu hafta", "hafta", "önümüzdeki hafta", "onumuzdeki hafta"):
            filtered = [
                e for e in events
                if q_low in e.get("title", "").lower() or q_low in e.get("location", "").lower()
            ]
            if filtered:
                events = filtered

        if not events:
            return f"Önümüzdeki {days} gün için planlanmış herhangi bir etkinlik veya toplantı bulunmuyor."

        tr_days = {
            "Monday": "Pazartesi", "Tuesday": "Salı", "Wednesday": "Çarşamba",
            "Thursday": "Perşembe", "Friday": "Cuma", "Saturday": "Cumartesi", "Sunday": "Pazar"
        }
        tr_months = {
            1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan", 5: "Mayıs", 6: "Haziran",
            7: "Temmuz", 8: "Ağustos", 9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık"
        }

        grouped = {}
        for ev in events:
            dt = ev["dt_start"]
            d_key = dt.strftime("%Y-%m-%d")
            if d_key not in grouped:
                day_name = tr_days.get(dt.strftime("%A"), dt.strftime("%A"))
                m_name = tr_months.get(dt.month, "")
                label = f"{day_name} ({dt.day} {m_name})"
                grouped[d_key] = {"label": label, "items": []}
            grouped[d_key]["items"].append(ev)

        lines = [f"Önümüzdeki {days} gün için toplam {len(events)} etkinlik bulunuyor:"]
        for d_key, grp in grouped.items():
            lines.append(f"\n📅 {grp['label']}:")
            for ev in grp["items"]:
                t_str = ev["dt_start"].strftime("%H:%M")
                title = ev.get("title", "Toplantı")
                loc = ev.get("location", "")
                loc_str = f" ({loc})" if loc else ""
                lines.append(f"  • {t_str} - {title}{loc_str}")

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
        organizer: Optional[str] = None,
        attendees: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Adds an event to local storage and syncs to Google Calendar if configured."""
        org = organizer or os.environ.get("ASTRO_OWNER_NAME", "Kullanıcı")
        data = self._load_local_data()
        events = data.get("events", [])
        new_event = {
            "id": f"evt_{int(time.time())}",
            "title": title,
            "start_time": start_time_str,
            "duration_minutes": duration_minutes,
            "location": location,
            "organizer": org,
            "attendees": attendees or [org]
        }

        # Attempt Google Calendar REST insert
        try:
            google_id = self._google_rest_insert_event(new_event)
            if google_id:
                new_event["google_id"] = google_id
        except Exception:
            pass

        events.append(new_event)
        data["events"] = events
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return {"status": "success", "event": new_event}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def delete_event(self, query: str) -> Dict[str, Any]:
        """Deletes an event matching the query title or keyword from local storage and Google Calendar."""
        q_low = query.lower().strip()
        if not q_low:
            return {"status": "error", "message": "Silinecek etkinlik adı belirtilmedi."}

        data = self._load_local_data()
        events = data.get("events", [])
        deleted_ids = set(data.get("deleted_event_ids", []))
        to_keep = []
        deleted = []

        for ev in events:
            title = ev.get("title", "").lower()
            ev_id = str(ev.get("id", "")).lower()
            if q_low in title or q_low in ev_id or (len(q_low) > 3 and all(w in title for w in q_low.split())):
                deleted.append(ev)
            else:
                to_keep.append(ev)

        # If not found in local events, also search in Google iCal events
        if not deleted:
            for ical_ev in self._fetch_google_ical_events():
                title = ical_ev.get("title", "").lower()
                ev_id = str(ical_ev.get("id", "")).lower()
                if q_low in title or q_low in ev_id or (len(q_low) > 3 and all(w in title for w in q_low.split())):
                    deleted.append(ical_ev)

        if not deleted:
            return {
                "status": "not_found",
                "message": f"'{query}' ile eşleşen bir etkinlik bulunamadı."
            }

        # Track deleted IDs to mask from iCal in future queries
        for dev in deleted:
            if dev.get("id"):
                deleted_ids.add(str(dev["id"]))
            if dev.get("title") and dev.get("start_time"):
                deleted_ids.add(f"{dev.get('title')}_{dev.get('start_time')}")

            # Attempt Google Calendar REST delete for deleted events
            gid = dev.get("google_id") or (dev.get("id") if not str(dev.get("id", "")).startswith("evt_") else None)
            if gid:
                try:
                    self._google_rest_delete_event(gid)
                except Exception:
                    pass

        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump({"events": to_keep, "deleted_event_ids": list(deleted_ids)}, f, ensure_ascii=False, indent=2)
            del_title = deleted[0].get("title", query)
            return {
                "status": "success",
                "deleted_title": del_title,
                "count": len(deleted),
                "message": f"'{del_title}' takvimden başarıyla kaldırıldı."
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def update_event(
        self,
        query: str,
        new_title: Optional[str] = None,
        new_start_time: Optional[str] = None,
        new_duration_minutes: Optional[int] = None,
        new_location: Optional[str] = None,
        new_description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Updates fields of an existing event matching the query in local storage and Google Calendar."""
        q_low = query.lower().strip()
        if not q_low:
            return {"status": "error", "message": "Güncellenecek etkinlik adı belirtilmedi."}

        data = self._load_local_data()
        events = data.get("events", [])
        deleted_ids = set(data.get("deleted_event_ids", []))
        target_event = None
        target_idx = -1

        for idx, ev in enumerate(events):
            title = ev.get("title", "").lower()
            ev_id = str(ev.get("id", "")).lower()
            if q_low in title or q_low in ev_id or (len(q_low) > 3 and all(w in title for w in q_low.split())):
                target_event = ev
                target_idx = idx
                break

        # If not in local events, check if it exists in iCal events
        if not target_event:
            for ical_ev in self._fetch_google_ical_events():
                title = ical_ev.get("title", "").lower()
                ev_id = str(ical_ev.get("id", "")).lower()
                if q_low in title or q_low in ev_id or (len(q_low) > 3 and all(w in title for w in q_low.split())):
                    target_event = dict(ical_ev)
                    if ical_ev.get("id"):
                        deleted_ids.add(str(ical_ev["id"]))
                    if ical_ev.get("title") and ical_ev.get("start_time"):
                        deleted_ids.add(f"{ical_ev.get('title')}_{ical_ev.get('start_time')}")
                    events.append(target_event)
                    target_idx = len(events) - 1
                    break

        if not target_event:
            return {"status": "not_found", "message": f"'{query}' ile eşleşen bir etkinlik bulunamadı."}

        old_title = target_event.get("title", query)
        changes = []

        if new_title and new_title.strip():
            target_event["title"] = new_title.strip()
            changes.append(f"başlık: '{target_event['title']}'")

        if new_start_time and new_start_time.strip():
            target_event["start_time"] = new_start_time.strip()
            changes.append(f"zaman: {target_event['start_time']}")

        if new_duration_minutes is not None and int(new_duration_minutes) > 0:
            target_event["duration_minutes"] = int(new_duration_minutes)
            changes.append(f"süre: {target_event['duration_minutes']} dk")

        if new_location and new_location.strip():
            target_event["location"] = new_location.strip()
            changes.append(f"konum: {target_event['location']}")

        if new_description is not None:
            target_event["description"] = new_description

        events[target_idx] = target_event

        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump({"events": events, "deleted_event_ids": list(deleted_ids)}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return {"status": "error", "message": f"Yerel depolama güncellenemedi: {e}"}

        # Google Calendar REST Patch sync
        gid = target_event.get("google_id") or (target_event.get("id") if not str(target_event.get("id", "")).startswith("evt_") else None)
        if gid:
            patch_payload = {}
            if new_title:
                patch_payload["summary"] = new_title
            if new_location:
                patch_payload["location"] = new_location
            if new_start_time:
                try:
                    st_dt = datetime.strptime(new_start_time, "%Y-%m-%d %H:%M")
                    dur = target_event.get("duration_minutes", 30)
                    end_dt = st_dt + timedelta(minutes=dur)
                    patch_payload["start"] = {"dateTime": f"{st_dt.isoformat()}+03:00"}
                    patch_payload["end"] = {"dateTime": f"{end_dt.isoformat()}+03:00"}
                except Exception:
                    pass
            if patch_payload:
                try:
                    self._google_rest_patch_event(gid, patch_payload)
                except Exception:
                    pass

        change_str = ", ".join(changes) if changes else "bilgiler güncellendi"
        return {
            "status": "success",
            "event": target_event,
            "old_title": old_title,
            "changes": changes,
            "message": f"'{old_title}' etkinliği başarıyla güncellendi ({change_str})."
        }

    def update_event_smart(
        self,
        query: str,
        new_date: Optional[str] = None,
        new_time: Optional[str] = None,
        new_location: Optional[str] = None,
        new_title: Optional[str] = None,
        new_duration: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Smart event updater that parses relative Turkish date/time words and updates event."""
        new_start_time = None
        if new_date or new_time:
            events = self._load_local_events()
            q_low = query.lower().strip()
            cur_dt = datetime.now()
            for ev in events:
                if q_low in ev.get("title", "").lower() or q_low in str(ev.get("id", "")).lower():
                    try:
                        st_str = ev.get("start_time", "")
                        if "T" in st_str:
                            cur_dt = datetime.fromisoformat(st_str.replace("Z", "+00:00")).replace(tzinfo=None)
                        else:
                            cur_dt = datetime.strptime(st_str, "%Y-%m-%d %H:%M")
                    except Exception:
                        pass
                    break

            target_date = cur_dt
            now = datetime.now()
            if new_date:
                d_low = new_date.lower().strip()
                tr_weekdays = {
                    "pazartesi": 0, "salı": 1, "sali": 1, "çarşamba": 2, "carsamba": 2,
                    "perşembe": 3, "persembe": 3, "cuma": 4, "cumartesi": 5, "pazar": 6
                }
                if "bugün" in d_low or "bugun" in d_low:
                    target_date = now
                elif "yarın" in d_low or "yarin" in d_low:
                    target_date = now + timedelta(days=1)
                elif "öbür gün" in d_low or "obur gun" in d_low:
                    target_date = now + timedelta(days=2)
                elif any(w in d_low for w in tr_weekdays):
                    for w_name, w_idx in tr_weekdays.items():
                        if w_name in d_low:
                            cur_w = now.weekday()
                            days_ahead = (w_idx - cur_w) % 7
                            if days_ahead == 0 or "gelecek" in d_low or "önümüzdeki" in d_low or "onumuzdeki" in d_low:
                                days_ahead += 7
                            target_date = now + timedelta(days=days_ahead)
                            break
                elif len(d_low) == 10 and "-" in d_low:
                    try:
                        target_date = datetime.strptime(d_low, "%Y-%m-%d")
                    except Exception:
                        pass

            hour = target_date.hour
            minute = target_date.minute
            if new_time:
                clean_time = new_time.replace(".", ":").strip()
                if ":" not in clean_time and clean_time.isdigit():
                    clean_time = f"{int(clean_time):02d}:00"
                try:
                    t_parts = [int(p) for p in clean_time.split(":")[:2]]
                    hour = t_parts[0]
                    minute = t_parts[1]
                except Exception:
                    pass

            new_start_time = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M")

        return self.update_event(
            query=query,
            new_title=new_title,
            new_start_time=new_start_time,
            new_duration_minutes=new_duration,
            new_location=new_location
        )

    def add_event_smart(
        self,
        title: str,
        date_str: str = "bugün",
        time_str: str = "10:00",
        duration_minutes: int = 45,
        location: str = "Ofis",
        organizer: Optional[str] = None,
        attendees: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Smart event creator that parses relative Turkish date words and saves event."""
        org = organizer or os.environ.get("ASTRO_OWNER_NAME", "Kullanıcı")
        now = datetime.now()
        target_date = now

        d_low = (date_str or "").lower().strip()
        tr_weekdays = {
            "pazartesi": 0, "salı": 1, "sali": 1, "çarşamba": 2, "carsamba": 2,
            "perşembe": 3, "persembe": 3, "cuma": 4, "cumartesi": 5, "pazar": 6
        }

        if "yarın" in d_low or "yarin" in d_low:
            target_date = now + timedelta(days=1)
        elif "öbür gün" in d_low or "obur gun" in d_low:
            target_date = now + timedelta(days=2)
        elif any(w in d_low for w in tr_weekdays):
            for w_name, w_idx in tr_weekdays.items():
                if w_name in d_low:
                    cur_w = now.weekday()
                    days_ahead = (w_idx - cur_w) % 7
                    if days_ahead == 0 or "gelecek" in d_low or "önümüzdeki" in d_low or "onumuzdeki" in d_low:
                        days_ahead += 7
                    target_date = now + timedelta(days=days_ahead)
                    break
        elif len(d_low) == 10 and "-" in d_low:
            try:
                target_date = datetime.strptime(d_low, "%Y-%m-%d")
            except Exception:
                pass

        # Parse time string: e.g. "14:00", "15.30", "14"
        clean_time = (time_str or "10:00").replace(".", ":").strip()
        if ":" not in clean_time and clean_time.isdigit():
            clean_time = f"{int(clean_time):02d}:00"

        try:
            t_parts = [int(p) for p in clean_time.split(":")[:2]]
            full_dt = target_date.replace(hour=t_parts[0], minute=t_parts[1], second=0, microsecond=0)
        except Exception:
            full_dt = target_date.replace(hour=10, minute=0, second=0, microsecond=0)

        start_time_str = full_dt.strftime("%Y-%m-%d %H:%M")
        return self.add_event(
            title=title,
            start_time_str=start_time_str,
            duration_minutes=duration_minutes,
            location=location,
            organizer=org,
            attendees=attendees
        )
