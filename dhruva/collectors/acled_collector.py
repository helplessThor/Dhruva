"""Dhruva — ACLED Conflict Events Collector.

Uses the ACLED API v3 — requires a free API key and registered email.
Register at: https://developer.acleddata.com/

If credentials are not configured, this collector logs a warning
and returns empty results (no mock data).
"""

import logging
from datetime import datetime, timezone, timedelta

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

# ACLED API endpoint
ACLED_API_URL = "https://api.acleddata.com/acled/read"

# Freshness window
FRESHNESS_WINDOW_DAYS = 14

# Load credentials
try:
    from backend.config import settings
    ACLED_API_KEY = getattr(settings, "acled_api_key", "") or ""
    ACLED_EMAIL = getattr(settings, "acled_email", "") or ""
except Exception:
    ACLED_API_KEY = ""
    ACLED_EMAIL = ""


class ACLEDCollector(BaseCollector):
    """Fetches real conflict events from the ACLED API.

    Requires ACLED API key and email to be configured in credentials.json:
        {"acled_api_key": "YOUR_KEY", "acled_email": "YOUR_EMAIL"}
    """

    MAX_EVENTS = 200

    # ACLED event type to severity mapping
    SEVERITY_MAP = {
        "Battles": 4,
        "Explosions/Remote violence": 5,
        "Violence against civilians": 4,
        "Riots": 3,
        "Protests": 2,
        "Strategic developments": 1,
    }

    def __init__(self, interval: int = 300):
        super().__init__(name="acled", interval=interval)
        self._last_fetched_at: datetime | None = None
        self._configured = bool(ACLED_API_KEY and ACLED_EMAIL)

        if not self._configured:
            logger.warning(
                "[acled] ACLED API key not configured. "
                "Register at https://developer.acleddata.com/ and add "
                '"acled_api_key" and "acled_email" to credentials.json'
            )

    async def collect(self) -> list[dict]:
        """Fetch ACLED conflict events."""
        if not self._configured:
            logger.info("[acled] Skipping — API key not configured")
            return []

        try:
            events = await self._fetch_acled_events()
            self._last_fetched_at = datetime.now(timezone.utc)
            return events
        except Exception as e:
            logger.error("[acled] Fetch failed: %s", e)
            return []

    async def _fetch_acled_events(self) -> list[dict]:
        """Fetch recent events from ACLED API."""
        # Query last N days
        since_date = (datetime.now(timezone.utc) - timedelta(days=FRESHNESS_WINDOW_DAYS))
        event_date_filter = since_date.strftime("%Y-%m-%d")

        params = {
            "key": ACLED_API_KEY,
            "email": ACLED_EMAIL,
            "event_date": event_date_filter,
            "event_date_where": ">=",
            "limit": self.MAX_EVENTS,
        }

        data = await self.fetch_json(ACLED_API_URL, params=params)

        results = data.get("data", [])
        if not results:
            logger.info("[acled] No events returned")
            return []

        events = []
        for record in results:
            try:
                event = self._parse_acled_event(record)
                if event:
                    events.append(event)
            except Exception as e:
                logger.debug("[acled] Skipping record: %s", e)
                continue

        logger.info("[acled] Returned %d conflict events", len(events))
        return events

    def _parse_acled_event(self, record: dict) -> dict | None:
        """Parse a single ACLED record into an OsintEvent."""
        lat = record.get("latitude")
        lon = record.get("longitude")

        if lat is None or lon is None:
            return None

        try:
            lat = float(lat)
            lon = float(lon)
        except (ValueError, TypeError):
            return None

        data_id = record.get("data_id", "")
        event_type = record.get("event_type", "Unknown")
        sub_event_type = record.get("sub_event_type", "")
        event_date = record.get("event_date", "")
        country = record.get("country", "Unknown")
        admin1 = record.get("admin1", "")
        location = record.get("location", "")
        actor1 = record.get("actor1", "")
        actor2 = record.get("actor2", "")
        fatalities = int(record.get("fatalities", 0) or 0)
        notes = record.get("notes", "")
        source = record.get("source", "ACLED")

        severity = self.SEVERITY_MAP.get(event_type, 2)
        if fatalities >= 10:
            severity = min(5, severity + 1)

        # Build description
        desc = sub_event_type or event_type
        if location:
            desc += f" in {location}, {country}"
        if fatalities:
            desc += f" · Fatalities: {fatalities}"

        return {
            "id": f"acled-{data_id}",
            "type": "acled",
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "severity": severity,
            "timestamp": event_date or datetime.now(timezone.utc).isoformat(),
            "source": f"ACLED ({source})",
            "title": f"{event_type} — {country}",
            "description": desc,
            "metadata": {
                "event_type": event_type,
                "sub_event_type": sub_event_type,
                "country": country,
                "admin1": admin1,
                "location": location,
                "actor1": actor1,
                "actor2": actor2,
                "fatalities": fatalities,
                "notes": notes[:300] if notes else "",
                "acled_id": str(data_id),
                "event_date": event_date,
            },
        }
