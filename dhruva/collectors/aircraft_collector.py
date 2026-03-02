"""Dhruva — ADS-B Aircraft Tracking Collector (OpenSky).

Uses OpenSky Network as primary source with:
  - OAuth2 client-credentials authentication (4000 credits/day)
  - Bounding-box queries for credit efficiency
  - Extended metadata: squawk, category, vertical_rate, geo_altitude
  - Falls back to anonymous if credentials unavailable
"""

import asyncio
import logging
import os
import random
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

# ── Load OpenSky OAuth2 credentials ────────────────────────────────
_CREDS_FILE = Path(__file__).resolve().parent.parent / "credentials.json"
OPENSKY_CLIENT_ID: str = ""
OPENSKY_CLIENT_SECRET: str = ""

try:
    # First try from credentials.json
    if _CREDS_FILE.exists():
        import json
        _creds = json.loads(_CREDS_FILE.read_text(encoding="utf-8"))
        OPENSKY_CLIENT_ID = _creds.get("clientId", "")
        OPENSKY_CLIENT_SECRET = _creds.get("clientSecret", "")
        if OPENSKY_CLIENT_ID:
            logger.info("[aircraft] OpenSky OAuth2 credentials loaded from credentials.json")
except Exception as e:
    logger.warning("[aircraft] Failed to read credentials.json: %s", e)

# Fallback to env vars
if not OPENSKY_CLIENT_ID:
    OPENSKY_CLIENT_ID = os.environ.get("DHRUVA_OPENSKY_CLIENT_ID", "")
    OPENSKY_CLIENT_SECRET = os.environ.get("DHRUVA_OPENSKY_CLIENT_SECRET", "")
    if OPENSKY_CLIENT_ID:
        logger.info("[aircraft] OpenSky OAuth2 credentials loaded from env")

# ── Aircraft category labels ───────────────────────────────────────
AIRCRAFT_CATEGORIES = {
    0: "No info",
    1: "No ADS-B category",
    2: "Light (<15,500 lbs)",
    3: "Small (15,500–75,000 lbs)",
    4: "Large (75,000–300,000 lbs)",
    5: "High Vortex Large (B-757)",
    6: "Heavy (>300,000 lbs)",
    7: "High Performance (>5g, 400kts)",
    8: "Rotorcraft",
    9: "Glider / Sailplane",
    10: "Lighter-than-air",
    11: "Parachutist / Skydiver",
    12: "Ultralight / Hang-glider",
    13: "Reserved",
    14: "UAV",
    15: "Space / Trans-atmospheric",
    16: "Emergency Vehicle",
    17: "Service Vehicle",
    18: "Point Obstacle",
    19: "Cluster Obstacle",
    20: "Line Obstacle",
}

POSITION_SOURCES = {0: "ADS-B", 1: "ASTERIX", 2: "MLAT", 3: "FLARM"}



class OpenSkyAuth:
    """OAuth2 client-credentials token manager for OpenSky Network."""

    TOKEN_URL = (
        "https://auth.opensky-network.org/auth/realms/"
        "opensky-network/protocol/openid-connect/token"
    )
    TOKEN_LIFETIME = 25 * 60  # Refresh 5 min before 30-min expiry

    def __init__(self, client_id: str, client_secret: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    async def get_token(self, http_client) -> str | None:
        """Return a valid bearer token, refreshing if needed."""
        if not self.is_configured:
            return None

        async with self._lock:
            if self._token and time.monotonic() < self._expires_at:
                return self._token

            try:
                resp = await http_client.post(
                    self.TOKEN_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=15.0,
                )
                resp.raise_for_status()
                data = resp.json()
                self._token = data["access_token"]
                # Use server-reported expiry if available, else default
                expires_in = data.get("expires_in", 1800)
                self._expires_at = time.monotonic() + min(expires_in - 300, self.TOKEN_LIFETIME)
                logger.info("[aircraft] OpenSky OAuth2 token acquired (expires in %ds)", expires_in)
                return self._token
            except Exception as e:
                logger.warning("[aircraft] OpenSky OAuth2 token request failed: %s", e)
                self._token = None
                return None


class OpenSkyCreditManager:
    """Tracks OpenSky API credit usage to avoid exceeding daily limits."""

    def __init__(self, daily_limit: int = 4000):
        self.daily_limit = daily_limit
        self._credits_used = 0
        self._day_start = self._current_day()
        self._remaining_from_header: int | None = None

    def _current_day(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _reset_if_new_day(self):
        today = self._current_day()
        if today != self._day_start:
            self._credits_used = 0
            self._day_start = today
            self._remaining_from_header = None
            logger.info("[aircraft] OpenSky credit counter reset for new day")

    def estimate_cost(self, lat_span: float, lon_span: float) -> int:
        """Estimate credit cost based on bounding box area in square degrees."""
        area = abs(lat_span * lon_span)
        if area <= 25:
            return 1
        elif area <= 100:
            return 2
        elif area <= 400:
            return 3
        return 4

    def can_afford(self, cost: int) -> bool:
        self._reset_if_new_day()
        # Trust the server header if we have it
        if self._remaining_from_header is not None:
            return self._remaining_from_header >= cost
        return (self._credits_used + cost) < self.daily_limit

    def record_usage(self, cost: int, remaining_header: int | None = None):
        self._reset_if_new_day()
        self._credits_used += cost
        if remaining_header is not None:
            self._remaining_from_header = remaining_header

    @property
    def remaining(self) -> int:
        self._reset_if_new_day()
        if self._remaining_from_header is not None:
            return self._remaining_from_header
        return max(0, self.daily_limit - self._credits_used)


class AircraftCollector(BaseCollector):
    """ADS-B collector: OpenSky."""

    OPENSKY_URL = "https://opensky-network.org/api/states/all"

    MAX_AIRCRAFT = 5000       # Cap per-source per-region
    COLLECTION_INTERVAL = 30  # seconds between collections

    # Search regions for optimized continental coverage (lat_min, lat_max, lon_min, lon_max, label)
    # Using targeted "sniper boxes" prevents APIs from silently truncating massive oceanic bounding boxes.
    # SEARCH_REGIONS = [
    #     # ── High-Density Continental Core ──
    #     ( 25,  50, -125,  -70, "North America"),
    #     ( 35,  60,  -10,   30, "Europe Core"),
    #     ( 10,  35,   70,   95, "South Asia / India"),
    #     ( 20,  45,  100,  145, "East Asia / China / Japan"),
        
    #     # ── The User-Requested Gaps ──
    #     ( 45,  70,   30,   90, "Western Russia / Urals"),     # Added specific Russian coverage
    #     ( 45,  70,   90,  180, "Eastern Russia / Siberia"),   # Splitting Russia into 2 boxes prevents truncation
    #     ( 10,  35,   35,   65, "Middle East / Gulf"),         # Refined Middle East box
    #     (-35,   5,   10,   50, "Central & South Africa"),     # Split Africa to dive deeper
    #     (  5,  35,  -20,   35, "North Africa / Sahara"),      # North Africa specific
    #     (-55,  15,  -80,  -35, "South America Core"),         # South America
        
    #     # ── Extended Peripheral Zones ──
    #     ( -5,  25,   95,  140, "Southeast Asia"),
    #     (-15,  30,  -90,  -55, "Central America / Caribbean"),
    #     (-45, -10,  110,  155, "Australia"),
    #     (-45,   0,  155,  180, "New Zealand / Oceania"),
    #     ( 50,  70, -165, -130, "Alaska / Bering Sea"),
    # ]

    SEARCH_REGIONS = [
    # ── Northern Hemisphere ──
    ( 30,  90, -180, -120, "North Pacific / Alaska / Arctic"),
    ( 30,  90, -120,  -60, "North America / Arctic"),
    ( 30,  90,  -60,    0, "North Atlantic / Greenland / Arctic"),
    ( 30,  90,    0,   60, "Europe / West Russia / Arctic"),
    ( 30,  90,   60,  120, "Central & East Russia / Arctic"),
    ( 30,  90,  120,  180, "North Pacific / Far East Russia / Arctic"),

    # ── Equatorial Belt ──
    (-30,  30, -180, -120, "Central Pacific Ocean"),
    (-30,  30, -120,  -60, "Americas Tropical"),
    (-30,  30,  -60,    0, "Atlantic Tropical"),
    (-30,  30,    0,   60, "Africa / Middle East"),
    (-30,  30,   60,  120, "South & Southeast Asia"),
    (-30,  30,  120,  180, "Indonesia / West Pacific"),

    # ── Southern Hemisphere ──
    (-90, -30, -180,  -60, "South Pacific / Southern Ocean"),
    (-90, -30,  -60,   60, "South America / South Atlantic / Africa"),
    (-90, -30,   60,  180, "Indian Ocean / Australia / Antarctica"),
    ]
    def __init__(self, interval: int = 30):
        super().__init__(name="aircraft", interval=max(interval, self.COLLECTION_INTERVAL))
        self._osky_region_index = 0    # OpenSky region rotation (offset for coverage)

        # OpenSky auth & credit management
        self._opensky_auth = OpenSkyAuth(OPENSKY_CLIENT_ID, OPENSKY_CLIENT_SECRET)
        self._opensky_credits = OpenSkyCreditManager(daily_limit=4000)
        self._use_opensky = bool(OPENSKY_CLIENT_ID)

        # Region-keyed caches: keeps flights from all regions alive
        self._osky_cache: dict[int, list[dict]] = {}  # OpenSky

        # Start OpenSky at a different region offset for better coverage
        self._osky_region_index = len(self.SEARCH_REGIONS) // 2

    async def collect(self) -> list[dict]:
        """Collect flights from OpenSky."""
        await self._collect_opensky_safe()
        
        merged = self._merge_all_flights()

        # If nothing from source, generate mock
        if not merged:
            merged = self._generate_mock_data()

        return merged

    async def _collect_opensky_safe(self):
        """OpenSky collection with error handling."""
        try:
            await self._collect_opensky()
        except Exception as e:
            logger.warning("[aircraft] OpenSky error: %s", e)

    async def _collect_opensky(self) -> list[dict]:
        """Fetch flights from OpenSky Network with OAuth2 authentication."""
        if not self._http_client:
            import httpx
            self._http_client = httpx.AsyncClient(timeout=30.0)

        # Pick next region
        region_idx = self._osky_region_index % len(self.SEARCH_REGIONS)
        region = self.SEARCH_REGIONS[region_idx]
        self._osky_region_index += 1
        lat_min, lat_max, lon_min, lon_max, label = region

        # Estimate credit cost
        lat_span = abs(lat_max - lat_min)
        lon_span = abs(lon_max - lon_min)
        cost = self._opensky_credits.estimate_cost(lat_span, lon_span)

        if not self._opensky_credits.can_afford(cost):
            logger.warning(
                "[aircraft] OpenSky daily credit limit approaching (%d remaining), skipping",
                self._opensky_credits.remaining,
            )
            return []

        # Build request params with bounding box
        params = {
            "lamin": lat_min,
            "lomin": lon_min,
            "lamax": lat_max,
            "lomax": lon_max,
            "extended": 1,  # Request category data
        }

        # Build headers — authenticated if we have a token
        headers = {}
        token = await self._opensky_auth.get_token(self._http_client)
        if token:
            headers["Authorization"] = f"Bearer {token}"
            logger.info("[aircraft] OpenSky query (authenticated): %s", label)
        else:
            logger.info("[aircraft] OpenSky query (anonymous): %s", label)

        resp = await self._http_client.get(
            self.OPENSKY_URL,
            params=params,
            headers=headers,
            timeout=20.0,
        )
        resp.raise_for_status()

        # Track credit usage from response headers
        remaining_str = resp.headers.get("X-Rate-Limit-Remaining")
        remaining = int(remaining_str) if remaining_str else None
        self._opensky_credits.record_usage(cost, remaining)

        data = resp.json()
        events = []
        states = data.get("states", []) or []

        for state in states[:self.MAX_AIRCRAFT]:
            try:
                event = self._parse_opensky_state(state)
                if event:
                    events.append(event)
            except Exception as e:
                logger.debug("[aircraft] Skipping OpenSky state: %s", e)
                continue

        logger.info(
            "[aircraft] OpenSky returned %d flights from %s (credits remaining: %s)",
            len(events), label,
            remaining if remaining is not None else f"~{self._opensky_credits.remaining}",
        )
        self._osky_cache[region_idx] = events
        return events

    def _parse_opensky_state(self, state: list) -> dict | None:
        """Parse a single OpenSky state vector into an OsintEvent with full metadata."""
        # Index mapping from OpenSky docs
        icao24 = state[0]
        callsign = (state[1] or "").strip()
        origin_country = state[2]
        time_position = state[3]
        last_contact = state[4]
        lon = state[5]
        lat = state[6]
        baro_altitude = state[7]   # meters
        on_ground = state[8]
        velocity = state[9]        # m/s
        true_track = state[10]     # degrees
        vertical_rate = state[11]  # m/s
        # sensors = state[12]      # not needed
        geo_altitude = state[13] if len(state) > 13 else None   # meters
        squawk = state[14] if len(state) > 14 else None
        spi = state[15] if len(state) > 15 else False
        position_source = state[16] if len(state) > 16 else 0
        category = state[17] if len(state) > 17 else 0

        if lat is None or lon is None or on_ground:
            return None

        # Convert units
        speed_knots = round((velocity or 0) * 1.944, 1)
        alt_ft = round((baro_altitude or 0) * 3.281)
        geo_alt_ft = round((geo_altitude or 0) * 3.281) if geo_altitude else None
        vrate_fpm = round((vertical_rate or 0) * 196.85) if vertical_rate else 0

        # Build rich description
        desc_parts = []
        if alt_ft:
            desc_parts.append(f"FL{alt_ft // 100:03d}" if alt_ft > 18000 else f"{alt_ft:,}ft")
        if speed_knots:
            desc_parts.append(f"{speed_knots}kts")
        if true_track is not None:
            desc_parts.append(f"HDG {true_track:.0f}°")
        if vrate_fpm and abs(vrate_fpm) > 100:
            arrow = "↑" if vrate_fpm > 0 else "↓"
            desc_parts.append(f"{arrow}{abs(vrate_fpm)}fpm")
        if origin_country:
            desc_parts.append(origin_country)

        # Category label
        cat_label = AIRCRAFT_CATEGORIES.get(category, "Unknown")
        pos_source = POSITION_SOURCES.get(position_source, "Unknown")

        return {
            "id": f"osky-{icao24}",
            "type": "aircraft",
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "severity": 1,
            "timestamp": datetime.fromtimestamp(
                last_contact or time.time(), tz=timezone.utc
            ).isoformat() if last_contact else datetime.now(timezone.utc).isoformat(),
            "source": "OpenSky Network",
            "title": callsign or icao24.upper(),
            "description": " · ".join(desc_parts) if desc_parts else "In flight",
            "metadata": {
                "callsign": callsign,
                "icao24": icao24,
                "airline": "Unknown",
                "origin": "—",
                "destination": "—",
                "origin_country": origin_country,
                "altitude_ft": alt_ft,
                "geo_altitude_ft": geo_alt_ft,
                "speed_knots": speed_knots,
                "heading": true_track,
                "vertical_rate_fpm": vrate_fpm,
                "squawk": squawk,
                "spi": spi,
                "category": cat_label,
                "category_id": category,
                "position_source": pos_source,
                "on_ground": False,
            },
        }

    def _merge_all_flights(self) -> list[dict]:
        """Aggregate flights from OpenSky cache, deduplicating by ID."""
        seen_ids: set[str] = set()
        merged: list[dict] = []

        for region_flights in self._osky_cache.values():
            for flight in region_flights:
                fid = flight["id"]
                if fid not in seen_ids:
                    seen_ids.add(fid)
                    merged.append(flight)

        return merged

    def _generate_mock_data(self) -> list[dict]:
        """Fallback mock data when all APIs are unavailable."""
        routes = [
            ("AI101", "Air India",         22,   78,  35000, 480, 45,  "DEL", "LHR"),
            ("BA215", "British Airways",   48,  -20,  38000, 490, 280, "LHR", "JFK"),
            ("EK501", "Emirates",          30,   55,  40000, 510, 315, "DXB", "LHR"),
            ("LH440", "Lufthansa",         52,   10,  36000, 470, 270, "FRA", "JFK"),
            ("UA835", "United Airlines",   42, -100,  39000, 500, 90,  "ORD", "NRT"),
            ("QF1",   "Qantas",           -10,  115,  41000, 505, 225, "SYD", "LHR"),
            ("JL7",   "Japan Airlines",    38,  145,  37000, 485, 60,  "NRT", "LAX"),
            ("AF007", "Air France",        50,   -5,  38000, 490, 250, "CDG", "JFK"),
            ("SQ21",  "Singapore Airlines", 10,   95,  43000, 520, 320, "SIN", "JFK"),
            ("CA981", "Air China",         45,  160,  36000, 475, 45,  "PEK", "LAX"),
            ("DL1",   "Delta Air Lines",   55,  -40,  37000, 495, 70,  "ATL", "LHR"),
            ("TK77",  "Turkish Airlines",  46,   30,  39000, 500, 290, "IST", "JFK"),
        ]

        events = []
        for cs, airline, lat, lon, alt, spd, hdg, orig, dest in routes:
            lat += random.uniform(-3, 3)
            lon += random.uniform(-5, 5)
            hdg = (hdg + random.uniform(-10, 10)) % 360
            alt_ft = alt + random.randint(-1000, 1000)

            events.append({
                "id": f"mock-{cs}",
                "type": "aircraft",
                "latitude": round(lat, 4),
                "longitude": round(lon, 4),
                "severity": 1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "Mock (APIs unavailable)",
                "title": f"{cs} — {airline}",
                "description": f"FL{alt_ft // 100:03d} · {spd}kts · HDG {hdg:.0f}° · {orig} → {dest}",
                "metadata": {
                    "callsign": cs,
                    "airline": airline,
                    "origin": orig,
                    "destination": dest,
                    "altitude_ft": alt_ft,
                    "speed_knots": spd,
                    "heading": round(hdg, 1),
                    "vertical_rate_fpm": 0,
                },
            })
        return events
