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
FRESHNESS_WINDOW_DAYS = 60

# Load credentials
try:
    from backend.config import settings
    ACLED_EMAIL = getattr(settings, "acled_email", "") or ""
    ACLED_PASSWORD = getattr(settings, "acled_password", "") or ""
except Exception:
    ACLED_EMAIL = ""
    ACLED_PASSWORD = ""


class ACLEDCollector(BaseCollector):
    """Fetches real conflict events from the ACLED API.

    Requires ACLED email and password to be configured in credentials.json:
        {"acled_email": "YOUR_EMAIL", "acled_password": "YOUR_PASSWORD"}
    """

    MAX_EVENTS = 2000

    # ACLED event type to severity mapping
    SEVERITY_MAP = {
        "Battles": 4,
        "Explosions/Remote violence": 5,
        "Violence against civilians": 4,
        "Riots": 3,
        "Protests": 2,
        "Strategic developments": 1,
    }

    def __init__(self, interval: int = 7200):
        super().__init__(name="acled", interval=interval)
        self._last_fetched_at: datetime | None = None
        self._configured = bool(ACLED_EMAIL and ACLED_PASSWORD)
        self._logged_in = False

        if not self._configured:
            logger.warning(
                "[acled] ACLED email or password not configured. "
                "Register at https://developer.acleddata.com/ and add "
                '"acled_email" and "acled_password" to credentials.json'
            )

    async def _login(self) -> bool:
        """Authenticate with ACLED API via email/password."""
        login_url = "https://acleddata.com/user/login?_format=json"
        payload = {
            "name": ACLED_EMAIL,
            "pass": ACLED_PASSWORD
        }
        
        if not self._http_client:
            import httpx
            self._http_client = httpx.AsyncClient(timeout=30.0)
            
        try:
            resp = await self._http_client.post(login_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "csrf_token" in data:
                self._logged_in = True
                logger.info("[acled] Successfully authenticated with ACLED API")
                return True
            else:
                logger.error("[acled] Login failed: Unexpected response format")
                return False
        except Exception as e:
            logger.error("[acled] Login failed: %s", e)
            return False

    async def collect(self) -> list[dict]:
        """Fetch ACLED conflict events."""
        if not self._configured:
            logger.info("[acled] Skipping — credentials not configured")
            return []

        if not self._logged_in:
            success = await self._login()
            if not success:
                return []

        try:
            events = await self._fetch_acled_events()
            self._last_fetched_at = datetime.now(timezone.utc)
            return events
        except Exception as e:
            logger.error("[acled] Fetch failed: %s", e)
            self._logged_in = False  # Reset login status on error to try again next time
            return []

    async def _fetch_acled_events(self) -> list[dict]:
        """Fetch recent events from ACLED API."""
        # Query last N days
        since_date = (datetime.now(timezone.utc) - timedelta(days=FRESHNESS_WINDOW_DAYS))
        event_date_filter = since_date.strftime("%Y-%m-%d")

        params = {
            "event_date": event_date_filter,
            "event_date_where": ">=",
            "limit": self.MAX_EVENTS,
        }

        # The new ACLED API response structure includes cookies implicitly in the session.
        # However, the ACLED v3 /api/acled/read endpoint requires querying via GET.
        
        # When querying /api/acled/read, ACLED's UI essentially uses the session.
        # But looking at the user payload, it seems ACLED's python requests need to properly send
        # cookies after the login to maintain the session. We use the existing httpx Session internally.
        
        data = await self.fetch_json("https://acleddata.com/api/acled/read", params=params)

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

        data_id = record.get("event_id_cnty", "")
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
        
        # Handle the integer timestamp
        timestamp_int = record.get("timestamp")
        if timestamp_int:
            # ACLED usually returns seconds or sometimes miliseconds depending on endpoint
            timestamp = datetime.fromtimestamp(timestamp_int, timezone.utc).isoformat()
        else:
            timestamp = event_date or datetime.now(timezone.utc).isoformat()

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
            "timestamp": timestamp,
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
