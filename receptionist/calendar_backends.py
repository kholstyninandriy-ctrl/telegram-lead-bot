"""Календарні бекенди: Cal.com, Google Calendar або Mock (для демо без ключів).

Вибір автоматичний за змінними оточення:
  CALCOM_API_KEY + CALCOM_EVENT_TYPE_ID      → Cal.com
  GOOGLE_SERVICE_ACCOUNT_JSON + GOOGLE_CALENDAR_ID → Google Calendar
  інакше                                     → MockCalendar (в пам'яті)
"""

import json
import logging
import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)

TZ_NAME = os.environ.get("BUSINESS_TIMEZONE", "Europe/Kyiv")
TZ = ZoneInfo(TZ_NAME)
WORK_START = int(os.environ.get("WORK_HOUR_START", "9"))
WORK_END = int(os.environ.get("WORK_HOUR_END", "18"))
SLOT_MINUTES = int(os.environ.get("SLOT_MINUTES", "30"))


def _candidate_slots(days_ahead: int, now: datetime | None = None) -> list[datetime]:
    """Робочі слоти (пн–сб) на найближчі days_ahead днів, починаючи з +1 год."""
    now = now or datetime.now(TZ)
    earliest = now + timedelta(hours=1)
    slots = []
    for d in range(days_ahead + 1):
        day = (now + timedelta(days=d)).date()
        if day.weekday() == 6:  # неділя
            continue
        t = datetime.combine(day, time(WORK_START), TZ)
        end = datetime.combine(day, time(WORK_END), TZ)
        while t + timedelta(minutes=SLOT_MINUTES) <= end:
            if t >= earliest:
                slots.append(t)
            t += timedelta(minutes=SLOT_MINUTES)
    return slots


class CalendarBackend:
    name = "base"

    def get_available_slots(self, days_ahead: int = 3, limit: int = 6) -> list[str]:
        raise NotImplementedError

    def book(self, start_iso: str, name: str, phone: str, email: str = "", notes: str = "") -> dict:
        raise NotImplementedError


class MockCalendar(CalendarBackend):
    """Календар у пам'яті — демо працює одразу, без жодних ключів."""

    name = "mock"

    def __init__(self):
        self.booked: set[str] = set()

    def get_available_slots(self, days_ahead: int = 3, limit: int = 6) -> list[str]:
        free = [s.isoformat() for s in _candidate_slots(days_ahead) if s.isoformat() not in self.booked]
        # розріджуємо, щоб календар виглядав «живим»
        return free[::3][:limit]

    def book(self, start_iso: str, name: str, phone: str, email: str = "", notes: str = "") -> dict:
        start = datetime.fromisoformat(start_iso).astimezone(TZ).isoformat()
        if start in self.booked:
            return {"ok": False, "error": "Слот уже зайнятий"}
        self.booked.add(start)
        return {"ok": True, "id": f"mock-{len(self.booked)}", "start": start, "link": ""}


class GoogleCalendar(CalendarBackend):
    """Google Calendar через service account.

    1. Створи service account у Google Cloud, увімкни Calendar API, завантаж JSON-ключ.
    2. У налаштуваннях календаря «Поділитися» → email service account → «Вносити зміни в події».
    3. GOOGLE_SERVICE_ACCOUNT_JSON = вміст JSON (одним рядком), GOOGLE_CALENDAR_ID = id календаря.
    """

    name = "google"
    API = "https://www.googleapis.com/calendar/v3"

    def __init__(self, sa_json: str, calendar_id: str):
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_info(
            json.loads(sa_json), scopes=["https://www.googleapis.com/auth/calendar"]
        )
        self.session = AuthorizedSession(creds)
        self.calendar_id = calendar_id

    def _busy(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        r = self.session.post(
            f"{self.API}/freeBusy",
            json={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "timeZone": TZ_NAME,
                "items": [{"id": self.calendar_id}],
            },
            timeout=10,
        )
        r.raise_for_status()
        busy = r.json()["calendars"][self.calendar_id].get("busy", [])
        return [
            (datetime.fromisoformat(b["start"].replace("Z", "+00:00")),
             datetime.fromisoformat(b["end"].replace("Z", "+00:00")))
            for b in busy
        ]

    def get_available_slots(self, days_ahead: int = 3, limit: int = 6) -> list[str]:
        cands = _candidate_slots(days_ahead)
        if not cands:
            return []
        busy = self._busy(cands[0], cands[-1] + timedelta(minutes=SLOT_MINUTES))
        dur = timedelta(minutes=SLOT_MINUTES)
        free = [s for s in cands if not any(s < be and s + dur > bs for bs, be in busy)]
        return [s.isoformat() for s in free[:limit]]

    def book(self, start_iso: str, name: str, phone: str, email: str = "", notes: str = "") -> dict:
        start = datetime.fromisoformat(start_iso).astimezone(TZ)
        end = start + timedelta(minutes=SLOT_MINUTES)
        if self._busy(start, end):
            return {"ok": False, "error": "Слот уже зайнятий"}
        r = self.session.post(
            f"{self.API}/calendars/{requests.utils.quote(self.calendar_id, safe='')}/events",
            json={
                "summary": f"AI-запис: {name}",
                "description": f"Телефон: {phone}\nEmail: {email or '-'}\n\n{notes}\n\nЗаписано AI-рецепціоністом",
                "start": {"dateTime": start.isoformat(), "timeZone": TZ_NAME},
                "end": {"dateTime": end.isoformat(), "timeZone": TZ_NAME},
            },
            timeout=10,
        )
        r.raise_for_status()
        ev = r.json()
        return {"ok": True, "id": ev["id"], "start": start.isoformat(), "link": ev.get("htmlLink", "")}


class CalCom(CalendarBackend):
    """Cal.com API v2. Потрібні CALCOM_API_KEY і CALCOM_EVENT_TYPE_ID."""

    name = "calcom"
    API = "https://api.cal.com/v2"

    def __init__(self, api_key: str, event_type_id: int):
        self.api_key = api_key
        self.event_type_id = event_type_id

    def _headers(self, version: str) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "cal-api-version": version}

    def get_available_slots(self, days_ahead: int = 3, limit: int = 6) -> list[str]:
        now = datetime.now(TZ)
        r = requests.get(
            f"{self.API}/slots",
            headers=self._headers("2024-09-04"),
            params={
                "eventTypeId": self.event_type_id,
                "start": now.date().isoformat(),
                "end": (now + timedelta(days=days_ahead)).date().isoformat(),
                "timeZone": TZ_NAME,
            },
            timeout=10,
        )
        r.raise_for_status()
        out = []
        for day_slots in r.json().get("data", {}).values():
            for s in day_slots:
                start = s["start"] if isinstance(s, dict) else s
                out.append(datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(TZ).isoformat())
        return sorted(out)[:limit]

    def book(self, start_iso: str, name: str, phone: str, email: str = "", notes: str = "") -> dict:
        start_utc = datetime.fromisoformat(start_iso).astimezone(ZoneInfo("UTC"))
        # Cal.com вимагає email — якщо клієнт не дав, ставимо технічний
        digits = "".join(ch for ch in phone if ch.isdigit()) or "guest"
        r = requests.post(
            f"{self.API}/bookings",
            headers=self._headers("2024-08-13"),
            json={
                "start": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "eventTypeId": self.event_type_id,
                "attendee": {
                    "name": name,
                    "email": email or f"{digits}@noemail.ai-receptionist.dev",
                    "timeZone": TZ_NAME,
                    "phoneNumber": phone if phone.startswith("+") else None,
                },
                "bookingFieldsResponses": {"notes": notes} if notes else {},
            },
            timeout=15,
        )
        if r.status_code >= 400:
            logger.error("Cal.com booking error %s: %s", r.status_code, r.text)
            return {"ok": False, "error": "Не вдалося створити запис у календарі"}
        data = r.json().get("data", {})
        return {"ok": True, "id": str(data.get("uid", data.get("id", ""))),
                "start": start_utc.astimezone(TZ).isoformat(), "link": ""}


def get_calendar() -> CalendarBackend:
    if os.environ.get("CALCOM_API_KEY") and os.environ.get("CALCOM_EVENT_TYPE_ID"):
        logger.info("Calendar backend: Cal.com")
        return CalCom(os.environ["CALCOM_API_KEY"], int(os.environ["CALCOM_EVENT_TYPE_ID"]))
    if os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") and os.environ.get("GOOGLE_CALENDAR_ID"):
        logger.info("Calendar backend: Google Calendar")
        return GoogleCalendar(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"], os.environ["GOOGLE_CALENDAR_ID"])
    logger.warning("Calendar backend: MOCK (календарні ключі не задані)")
    return MockCalendar()
