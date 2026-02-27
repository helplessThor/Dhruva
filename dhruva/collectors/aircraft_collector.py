"""Dhruva — ADS-B Aircraft Tracking Collector (FlightAware + OpenSky Dual-Source).

Uses FlightAware AeroAPI v4 as primary source with:
  - Strict 10 requests/minute sliding-window rate limiter
  - Real origin/destination/airline from API
  - Heading, altitude, speed in metadata

Uses OpenSky Network as concurrent enrichment source with:
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

# ── Load FlightAware API key ────────────────────────────────────────
_KEY_FILE = Path(__file__).resolve().parent.parent / "flight api key.txt"
FLIGHTAWARE_API_KEY: str = ""
if _KEY_FILE.exists():
    FLIGHTAWARE_API_KEY = _KEY_FILE.read_text().strip()
    logger.info("[aircraft] FlightAware API key loaded from %s", _KEY_FILE.name)
else:
    FLIGHTAWARE_API_KEY = os.environ.get("DHRUVA_FLIGHTAWARE_KEY", "")
    if FLIGHTAWARE_API_KEY:
        logger.info("[aircraft] FlightAware API key loaded from env")
    else:
        logger.warning("[aircraft] No FlightAware API key found — will use mock data")

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


class RateLimiter:
    """Sliding-window rate limiter: max N calls per window_seconds."""

    def __init__(self, max_calls: int = 10, window_seconds: float = 60.0):
        self.max_calls = max_calls
        self.window = window_seconds
        self._timestamps: deque[float] = deque()

    def can_call(self) -> bool:
        self._prune()
        return len(self._timestamps) < self.max_calls

    def record(self):
        self._timestamps.append(time.monotonic())

    def wait_time(self) -> float:
        """Seconds until the next call is allowed."""
        self._prune()
        if len(self._timestamps) < self.max_calls:
            return 0.0
        oldest = self._timestamps[0]
        return max(0.0, self.window - (time.monotonic() - oldest))

    def _prune(self):
        cutoff = time.monotonic() - self.window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()


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
    """ADS-B collector: FlightAware (primary) + OpenSky (enrichment)."""

    AEROAPI_BASE = "https://aeroapi.flightaware.com/aeroapi"
    OPENSKY_URL = "https://opensky-network.org/api/states/all"

    MAX_AIRCRAFT = 400       # Cap per-source per-region
    COLLECTION_INTERVAL = 30  # seconds between collections

    # Search regions for global coverage (lat_min, lat_max, lon_min, lon_max, label)
    SEARCH_REGIONS = [
        (20, 50, 60, 100, "South Asia / India"),
        (30, 55, -10, 40, "Europe"),
        (25, 50, -130, -60, "North America"),
        (0, 30, 90, 145, "Southeast Asia / Pacific"),
        (15, 40, 30, 65, "Middle East"),
        (50, 72, 30, 180, "Russia / Siberia"),
        (-35, 15, -20, 55, "Africa"),
        (-55, 15, -80, -35, "South America"),
        (-10, 25, -60, -15, "Atlantic / Caribbean"),
        (-50, -10, 110, 180, "Australia / Oceania"),
        (30, 55, 100, 145, "East Asia / China / Japan"),
        (-70, -50, -180, 180, "Southern Ocean / Antarctica"),
    ]

    def __init__(self, interval: int = 30):
        super().__init__(name="aircraft", interval=max(interval, self.COLLECTION_INTERVAL))
        self._fa_rate_limiter = RateLimiter(max_calls=10, window_seconds=60.0)
        self._fa_region_index = 0      # FlightAware region rotation
        self._osky_region_index = 0    # OpenSky region rotation (offset for coverage)
        self._use_flightaware = bool(FLIGHTAWARE_API_KEY)

        # OpenSky auth & credit management
        self._opensky_auth = OpenSkyAuth(OPENSKY_CLIENT_ID, OPENSKY_CLIENT_SECRET)
        self._opensky_credits = OpenSkyCreditManager(daily_limit=4000)
        self._use_opensky = bool(OPENSKY_CLIENT_ID)

        # Region-keyed caches: keeps flights from all regions alive
        self._fa_cache: dict[int, list[dict]] = {}   # FlightAware
        self._osky_cache: dict[int, list[dict]] = {}  # OpenSky

        # Start OpenSky at a different region offset for better coverage
        self._osky_region_index = len(self.SEARCH_REGIONS) // 2

    async def collect(self) -> list[dict]:
        """Collect from both sources concurrently and merge."""
        tasks = []

        # FlightAware task
        if self._use_flightaware:
            tasks.append(self._collect_flightaware_safe())
        
        # OpenSky task (runs concurrently, not just as fallback)
        tasks.append(self._collect_opensky_safe())

        if tasks:
            await asyncio.gather(*tasks)

        merged = self._merge_all_flights()

        # If nothing from either source, generate mock
        if not merged:
            merged = self._generate_mock_data()

        return merged

    async def _collect_flightaware_safe(self):
        """FlightAware collection with error handling."""
        try:
            events = await self._collect_flightaware()
            if events is not None:
                return
        except Exception as e:
            logger.warning("[aircraft] FlightAware error: %s", e)

    async def _collect_opensky_safe(self):
        """OpenSky collection with error handling."""
        try:
            await self._collect_opensky()
        except Exception as e:
            logger.warning("[aircraft] OpenSky error: %s", e)

    async def _collect_flightaware(self) -> list[dict] | None:
        """Fetch flights from FlightAware AeroAPI /flights/search."""
        wait = self._fa_rate_limiter.wait_time()
        if wait > 0:
            logger.info("[aircraft] FlightAware rate limited — waiting %.1fs", wait)
            await asyncio.sleep(wait)

        region_idx = self._fa_region_index % len(self.SEARCH_REGIONS)
        region = self.SEARCH_REGIONS[region_idx]
        self._fa_region_index += 1
        lat_min, lat_max, lon_min, lon_max, label = region

        query = f'-latlong "{lat_min} {lon_min} {lat_max} {lon_max}"'
        url = f"{self.AEROAPI_BASE}/flights/search"

        if not self._http_client:
            import httpx
            self._http_client = httpx.AsyncClient(timeout=30.0)

        self._fa_rate_limiter.record()
        logger.info("[aircraft] AeroAPI query: %s (%s)", label, query)

        resp = await self._http_client.get(
            url,
            params={"query": query},
            headers={"x-apikey": FLIGHTAWARE_API_KEY},
        )
        resp.raise_for_status()
        data = resp.json()

        flights = data.get("flights", []) or []
        events = []

        for flight in flights[:self.MAX_AIRCRAFT]:
            try:
                event = self._parse_flightaware_flight(flight)
                if event:
                    events.append(event)
            except Exception as e:
                logger.debug("[aircraft] Skipping FA flight: %s", e)
                continue

        logger.info("[aircraft] AeroAPI returned %d flights from %s", len(events), label)
        self._fa_cache[region_idx] = events
        return events

    async def _collect_opensky(self) -> list[dict]:
        """Fetch flights from OpenSky Network with OAuth2 authentication."""
        if not self._http_client:
            import httpx
            self._http_client = httpx.AsyncClient(timeout=30.0)

        # Pick next region (rotates independently from FlightAware)
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
        """Merge flights from both FlightAware and OpenSky caches, deduplicating by ID."""
        seen_ids: set[str] = set()
        merged: list[dict] = []

        # FlightAware first (higher quality data)
        for region_flights in self._fa_cache.values():
            for flight in region_flights:
                fid = flight["id"]
                if fid not in seen_ids:
                    seen_ids.add(fid)
                    merged.append(flight)

        # Then OpenSky (supplements with additional aircraft)
        # Also try to match by callsign to avoid duplicates across sources
        fa_callsigns = {
            f.get("metadata", {}).get("callsign", "").strip().upper()
            for f in merged if f.get("metadata", {}).get("callsign")
        }

        for region_flights in self._osky_cache.values():
            for flight in region_flights:
                fid = flight["id"]
                callsign = flight.get("metadata", {}).get("callsign", "").strip().upper()
                # Skip if we already have this ID or callsign from FlightAware
                if fid in seen_ids:
                    continue
                if callsign and callsign in fa_callsigns:
                    continue
                seen_ids.add(fid)
                merged.append(flight)

        return merged

    def _parse_flightaware_flight(self, flight: dict) -> dict | None:
        """Parse a single FlightAware flight object into an OsintEvent."""
        last_pos = flight.get("last_position") or {}
        lat = last_pos.get("latitude")
        lon = last_pos.get("longitude")

        if lat is None or lon is None:
            return None

        # Extract fields
        ident = flight.get("ident", "")
        ident_icao = flight.get("ident_icao", "")
        flight_number = flight.get("flight_number", "")

        # Origin / destination
        origin_info = flight.get("origin") or {}
        dest_info = flight.get("destination") or {}
        origin_code = origin_info.get("code_iata") or origin_info.get("code_icao") or "—"
        origin_name = origin_info.get("name", "")
        origin_city = origin_info.get("city", "")
        dest_code = dest_info.get("code_iata") or dest_info.get("code_icao") or "—"
        dest_name = dest_info.get("name", "")
        dest_city = dest_info.get("city", "")

        # Operator / airline
        operator = flight.get("operator", "")
        operator_icao = flight.get("operator_icao", "")

        # Position data
        altitude = last_pos.get("altitude", 0) or 0
        alt_ft = altitude * 100 if altitude < 1000 else altitude
        groundspeed = last_pos.get("groundspeed", 0) or 0
        heading = last_pos.get("heading", 0)
        aircraft_type = flight.get("aircraft_type", "")

        # Build description
        desc_parts = []
        if alt_ft:
            desc_parts.append(f"FL{alt_ft // 100:03d}" if alt_ft > 18000 else f"{alt_ft:,}ft")
        if groundspeed:
            desc_parts.append(f"{groundspeed}kts")
        if heading is not None:
            desc_parts.append(f"HDG {heading:.0f}°")
        if origin_code != "—" and dest_code != "—":
            desc_parts.append(f"{origin_code} → {dest_code}")

        display_name = ident or ident_icao or flight_number or "Unknown"
        airline_name = operator or operator_icao or "Unknown"

        return {
            "id": f"fa-{flight.get('fa_flight_id', ident)}",
            "type": "aircraft",
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "severity": 1,
            "timestamp": last_pos.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "source": "FlightAware AeroAPI",
            "title": f"{display_name} — {airline_name}",
            "description": " · ".join(desc_parts) if desc_parts else "In flight",
            "metadata": {
                "callsign": ident,
                "flight_number": flight_number,
                "icao24": ident_icao,
                "airline": airline_name,
                "operator_icao": operator_icao,
                "origin": origin_code,
                "origin_name": f"{origin_name}, {origin_city}" if origin_city else origin_name,
                "destination": dest_code,
                "destination_name": f"{dest_name}, {dest_city}" if dest_city else dest_name,
                "aircraft_type": aircraft_type,
                "registration": flight.get("registration", ""),
                "altitude_ft": alt_ft,
                "speed_knots": groundspeed,
                "heading": heading,
                "fa_flight_id": flight.get("fa_flight_id", ""),
            },
        }

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
