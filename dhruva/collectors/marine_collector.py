"""Dhruva — Marine Traffic Collector (AISStream.io + position-api).

Primary source: AISStream.io WebSocket for real-time AIS data.
Supplementary source: position-api (localhost:5000) for open-ocean areas
that AIS ground stations don't cover well.

Features:
  - Real MMSI, vessel names, IMO numbers from AIS broadcasts
  - Live positions, speed, heading, course data
  - Global coverage across major shipping lanes
  - Stable vessel cache with deduplication by MMSI
  - Open-ocean gap-filling via MarineTraffic position-api
  - Falls back to realistic mock data when API key is unavailable
"""

import asyncio
import json
import logging
import math
import os
import random
import time as _time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

# ── position-api configuration ─────────────────────────────────────
# Set via env var or defaults to localhost:5000
POSITION_API_URL = os.environ.get("DHRUVA_POSITION_API_URL", "http://localhost:5000")

# MarineTraffic area codes for open-ocean regions (where AISStream has gaps)
OCEAN_AREAS = [
    "NOATL",   # North Atlantic (mid-ocean shipping lanes)
    "NPAC",    # North Pacific (trans-Pacific routes)
    "SPAC",    # South Pacific
    "SIND",    # South Indian Ocean
    "SAFR",    # South Africa / Cape route
    "WAFR",    # West Africa / Gulf of Guinea to mid-Atlantic
    "EAFR",    # East Africa / Indian Ocean coast
    "ECSA",    # East Coast South America
    "WCSA",    # West Coast South America
    "ANT",     # Antarctica / Southern Ocean
]

# How often to poll position-api (seconds) — slower than AISStream
POSITION_API_POLL_INTERVAL = 180  # 3 minutes

# ── Load AISStream API key ─────────────────────────────────────────
_KEY_FILE = Path(__file__).resolve().parent.parent / "AIS Ship API KEY.txt"
AISSTREAM_API_KEY: str = ""
if _KEY_FILE.exists():
    AISSTREAM_API_KEY = _KEY_FILE.read_text().strip()
    logger.info("[marine] AISStream API key loaded from %s", _KEY_FILE.name)
else:
    AISSTREAM_API_KEY = os.environ.get("DHRUVA_AISSTREAM_KEY", "")
    if AISSTREAM_API_KEY:
        logger.info("[marine] AISStream API key loaded from env")
    else:
        logger.warning("[marine] No AISStream API key — will use mock data")

# AIS Navigation Status codes
NAV_STATUS = {
    0: "Under way using engine",
    1: "At anchor",
    2: "Not under command",
    3: "Restricted manoeuvrability",
    4: "Constrained by draught",
    5: "Moored",
    6: "Aground",
    7: "Engaged in fishing",
    8: "Under way sailing",
    9: "Reserved for HSC",
    10: "Reserved for WIG",
    14: "AIS-SART",
    15: "Not defined",
}

# AIS vessel type codes → human labels
VESSEL_TYPE_MAP = {
    range(20, 30): "Wing in Ground",
    range(30, 36): "Fishing",
    range(36, 40): "Towing/Diving",
    range(40, 50): "High Speed Craft",
    range(50, 55): "Special Craft",
    range(55, 60): "Law Enforcement",
    range(60, 70): "Passenger",
    range(70, 80): "Cargo",
    range(80, 90): "Tanker",
    range(90, 100): "Other",
}

# AIS vessel type codes that are explicitly military/law-enforcement
MILITARY_VESSEL_TYPE_CODES = {35, 55}  # 35 = Military, 55 = Law Enforcement

# ── Military MMSI Prefix Ranges ────────────────────────────────────────────
# MMSI is a 9-digit number. First 3 digits = MID (Maritime Identification Digit)
# Certain MID ranges are assigned exclusively to military vessels.
MILITARY_MMSI_PREFIXES: dict[str, list[str]] = {
    "US Navy":          ["338", "369"],
    "UK Royal Navy":    ["232", "233", "234", "235"],
    "French Navy":      ["226", "227"],
    "Russian Navy":     ["273"],
    "Chinese PLAN":     ["412", "413"],
    "Indian Navy":      ["419"],
    "German Navy":      ["211"],
    "Italian Navy":     ["247"],
    "Spanish Navy":     ["224"],
    "Australian Navy":  ["503"],
    "Canadian Navy":    ["316"],
    "Japanese MSDF":    ["431", "432", "433"],
    "NATO/Unallocated": ["970", "972", "974"],
}

# Build flat set of prefixes for quick lookup
_MIL_MMSI_PREFIX_SET: set[str] = set()
_MIL_MMSI_PREFIX_NAVY: dict[str, str] = {}
for _navy, _prefixes in MILITARY_MMSI_PREFIXES.items():
    for _p in _prefixes:
        _MIL_MMSI_PREFIX_SET.add(_p)
        _MIL_MMSI_PREFIX_NAVY[_p] = _navy

# ── Military Callsign Patterns ─────────────────────────────────────────────
# US Navy ships: WNSP*, NATO ships start with specific prefixes
MILITARY_CALLSIGN_PATTERNS = [
    "WNSP",  # US Navy surface combatants
    "NWSP",
    "NATO",
]


class MilitaryMarineDetector:
    """Classify vessels as military based on MMSI, vessel type, and callsign.

    Detection layers (applied in order, any match = military):
      1. AIS vessel type code 35 (Military Operations) or 55 (Law Enforcement)
      2. MMSI prefix matching known naval MMSI ranges
      3. Callsign pattern matching
    """

    @staticmethod
    def classify(vessel: dict) -> tuple[bool, str]:
        """Return (is_military, navy_label).

        Args:
            vessel: Vessel dict from the internal cache (has mmsi, callsign, vessel_type_code, etc.)

        Returns:
            (is_military: bool, label: str) — label is the navy name or reason
        """
        mmsi = str(vessel.get("mmsi", ""))
        callsign = str(vessel.get("callsign", "")).upper().strip()
        vtype_code = int(vessel.get("vessel_type_code", 0) or 0)

        # Layer 1: vessel type code
        if vtype_code in MILITARY_VESSEL_TYPE_CODES:
            label = "Military Operations" if vtype_code == 35 else "Law Enforcement"
            return True, label

        # Layer 2: MMSI prefix
        if len(mmsi) >= 3:
            prefix3 = mmsi[:3]
            if prefix3 in _MIL_MMSI_PREFIX_SET:
                return True, _MIL_MMSI_PREFIX_NAVY[prefix3]

        # Layer 3: callsign pattern
        if callsign:
            for pattern in MILITARY_CALLSIGN_PATTERNS:
                if callsign.startswith(pattern):
                    return True, f"Callsign Pattern ({callsign[:6]})"

        return False, ""


def _vessel_type_label(type_code: int) -> str:
    """Convert AIS vessel type code to label."""
    for range_obj, label in VESSEL_TYPE_MAP.items():
        if type_code in range_obj:
            return label
    return "Unknown"


# ── Wide ocean basin bounding boxes for AISStream subscription ──
# Using large boxes to capture both coastal AND open-ocean vessels.
# Format: [[lat1, lon1], [lat2, lon2]] (two opposite corners)
# AISStream supports overlapping boxes without duplicate data.
SHIPPING_BBOXES = [
    [[-90.0, -180.0], [90.0, 180.0]]
    # # ── Large Ocean Basins ──
    # # North Atlantic (Europe ↔ Americas)
    # [[60.0, 0.0], [20.0, -60.0]],
    # # European waters + Mediterranean
    # [[60.0, 40.0], [30.0, -12.0]],
    # # Indian Ocean (Arabia ↔ SE Asia)
    # [[25.0, 80.0], [-10.0, 40.0]],
    # # South China Sea + Strait of Malacca + SE Asia
    # [[25.0, 125.0], [-5.0, 95.0]],
    # # East Asian waters (China, Japan, Korea)
    # [[45.0, 145.0], [20.0, 105.0]],
    # # Persian Gulf + Arabian Sea + Red Sea
    # [[32.0, 75.0], [10.0, 32.0]],
    # # West Africa + Gulf of Guinea
    # [[15.0, 15.0], [-10.0, -25.0]],
    # # East coast Americas + Caribbean
    # [[35.0, -60.0], [5.0, -100.0]],
    # # South Atlantic + Cape of Good Hope
    # [[-10.0, 20.0], [-45.0, -40.0]],
    # # Australia / Oceania
    # [[-5.0, 160.0], [-45.0, 110.0]],
    # # Bay of Bengal + Sri Lanka
    # [[22.0, 95.0], [5.0, 75.0]],

    # # ── Targeted port/coastal zones (where AIS ground stations exist) ──
    # # Mumbai / Western India coast
    # [[23.0, 75.0], [15.0, 68.0]],
    # # Chennai / East India coast
    # [[15.0, 83.0], [8.0, 77.0]],
    # # Sri Lanka + Colombo
    # [[10.0, 82.0], [5.0, 78.0]],
    # # Singapore / Johor Strait
    # [[2.0, 105.0], [0.5, 103.0]],
    # # Hong Kong / Pearl River Delta
    # [[23.0, 115.0], [21.0, 113.0]],
    # # Shanghai / Yangtze River
    # [[32.0, 123.0], [29.0, 120.0]],
    # # Dubai / Abu Dhabi / Fujairah
    # [[26.5, 57.0], [24.0, 53.0]],
    # # Jeddah / Red Sea
    # [[24.0, 42.0], [18.0, 36.0]],
    # # Tokyo Bay / Japan
    # [[36.0, 141.0], [34.0, 139.0]],
    # # Busan / Korea
    # [[36.0, 130.0], [34.0, 128.0]],
    # # Ho Chi Minh / Vietnam coast
    # [[12.0, 110.0], [8.0, 106.0]],
    # # Manila / Philippines
    # [[15.0, 122.0], [13.0, 119.0]],
    # # US West Coast (LA/Long Beach + SF)
    # [[38.0, -117.0], [32.0, -122.0]],
    # # US East Coast (NY/NJ)
    # [[41.0, -73.0], [38.0, -75.0]],
    # # Suez Canal + Port Said
    # [[32.0, 34.0], [29.0, 31.0]],
    # # Panama Canal
    # [[10.0, -79.0], [8.0, -80.5]],
]

# ── Stable mock vessels (fallback when no API key) ─────────────────
# Uses real vessel data verified from marinetraffic.com / vesselfinder.com
# MOCK_VESSELS = [
#     # (id, name, type, mmsi, imo, flag, callsign, lat, lon, heading, speed, lane)
#     ("mv-001", "EVER ACE", "Container", "353136000", "9893890", "PA", "3FWP9", 1.8, 103.5, 315, 12.5, "Strait of Malacca"),
#     ("mv-002", "MSC IRINA", "Container", "353637000", "9930198", "PA", "3FJD5", 2.5, 101.8, 135, 11.2, "Strait of Malacca"),
#     ("mv-003", "FRONT COUGAR", "Tanker", "538009685", "9834081", "MH", "V7A3782", 3.1, 100.5, 300, 13.0, "Strait of Malacca"),
#     ("mv-004", "HMM ALGECIRAS", "Container", "440426000", "9863297", "KR", "D5DU7", 30.0, 32.5, 180, 8.5, "Suez Canal Approach"),
#     ("mv-005", "AL MURAYKH", "LNG Carrier", "229964000", "9431197", "MT", "9HA4804", 29.5, 33.2, 0, 7.0, "Suez Canal Approach"),
#     ("mv-006", "SPIRIT OF BRITAIN", "Passenger", "235113622", "9524231", "GB", "MHJF7", 50.9, 1.3, 225, 18.5, "English Channel"),
#     ("mv-007", "EUGEN MAERSK", "Container", "220417000", "9321483", "DK", "OYGZ2", 50.2, -0.5, 70, 16.8, "English Channel"),
#     ("mv-008", "WAN HAI 316", "Container", "416004127", "9462714", "TW", "BJCB", 14.5, 114.2, 190, 15.5, "South China Sea"),
#     ("mv-009", "OOCL SPAIN", "Container", "477262700", "9927622", "HK", "VRQK6", 12.8, 112.5, 45, 16.2, "South China Sea"),
#     ("mv-010", "PACIFIC VENUS", "Passenger", "431501000", "9160011", "JP", "7JZJ", 16.0, 116.8, 210, 13.8, "South China Sea"),
#     ("mv-011", "SEASTAR", "Tanker", "256724000", "9313178", "MT", "9HA3200", 26.5, 52.0, 140, 10.5, "Persian Gulf"),
#     ("mv-012", "AL GHARRAFA", "LNG Carrier", "215273000", "9431109", "MT", "9HA2098", 25.0, 54.5, 310, 16.0, "Persian Gulf"),
#     ("mv-013", "MSC GULSUN", "Container", "255806177", "9839430", "PT", "CQMS7", 36.5, 12.0, 90, 17.5, "Mediterranean"),
#     ("mv-014", "COSTA SMERALDA", "Passenger", "247397100", "9781889", "IT", "IBHF", 35.8, 15.5, 270, 16.0, "Mediterranean"),
#     ("mv-015", "PANAMAX SPIRIT", "Bulk Carrier", "370497000", "9806079", "PA", "3FHB9", 9.0, -79.5, 350, 6.0, "Panama Canal"),
#     ("mv-016", "CAPE DORIC", "Bulk Carrier", "440355000", "9778028", "KR", "D5PQ4", -34.2, 18.5, 90, 14.0, "Cape of Good Hope"),
#     ("mv-017", "SCI CHENNAI", "Cargo", "419001234", "9293753", "IN", "ATVN", 13.2, 84.5, 200, 11.0, "Bay of Bengal"),
#     ("mv-018", "JAG ARUHI", "Tanker", "419087654", "9590247", "IN", "AUET", 15.0, 88.0, 20, 10.5, "Bay of Bengal"),
#     ("mv-019", "ATLANTIC STAR", "Cargo", "311068200", "9454436", "BS", "C6DF7", 45.0, -30.0, 90, 14.2, "North Atlantic"),
#     ("mv-020", "NYK BLUE JAY", "Container", "431602000", "9468282", "JP", "7KDQ", 31.0, 128.0, 45, 18.0, "East China Sea"),
#     ("mv-021", "CARNIVAL VISTA", "Passenger", "311041700", "9692569", "BS", "C6FK6", 27.0, -90.0, 165, 17.5, "Gulf of Mexico"),
#     ("mv-022", "VALE BRASIL", "Bulk Carrier", "710068000", "9655498", "BR", "PPGS", -33.5, 17.5, 270, 13.0, "Cape of Good Hope"),
#     ("mv-023", "CMA CGM JACQUES SAADE", "Container", "215406000", "9839179", "MT", "9HA4956", 36.0, 10.0, 85, 19.2, "Mediterranean"),
#     ("mv-024", "QUEEN MARY 2", "Passenger", "310627000", "9241061", "BM", "ZCEF6", 42.0, -35.0, 270, 22.0, "North Atlantic"),
#     ("mv-025", "BERGE EVEREST", "Bulk Carrier", "538090649", "9867967", "MH", "V7GI9", 8.8, -79.8, 175, 5.5, "Panama Canal"),
#     ("mv-026", "YUAN XIANG", "Container", "413754000", "9497040", "CN", "BORF", 32.0, 125.0, 200, 16.5, "East China Sea"),
# ]


class MarineCollector(BaseCollector):
    """AIS marine vessel collector with AISStream.io real data.

    When an API key is available:
      - Connects to AISStream.io WebSocket for real AIS data
      - Accumulates vessels by MMSI with position updates
      - Enriches with static data (name, IMO, callsign) when available

    Fallback:
      - Uses a stable roster of realistic mock vessels
      - Vessels drift gradually to simulate movement
    """

    AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
    MAX_VESSELS = 10000    # Increased cap to accommodate position-api vessels
    STALE_MINUTES = 60    # Drop vessels not seen for this many minutes

    def __init__(self, interval: int = 30):
        super().__init__(name="marine", interval=interval)
        self._use_aisstream = bool(AISSTREAM_API_KEY)
        # Vessel cache keyed by MMSI
        self._vessel_cache: dict[str, dict] = {}
        # Static data cache (vessel names, IMO, etc.) keyed by MMSI
        self._static_cache: dict[str, dict] = {}
        # Background AIS WebSocket task
        self._ais_task: asyncio.Task | None = None
        self._ais_connected = False
        self._mock_initialized = False
        # position-api state
        self._posapi_available: bool | None = None  # None = not checked yet
        self._posapi_last_poll: float = 0.0
        self._posapi_area_idx: int = 0  # Round-robin through OCEAN_AREAS
        self._posapi_vessel_count: int = 0

    async def collect(self) -> list[dict]:
        if self._use_aisstream:
            # Start the AIS WebSocket listener in background (once)
            if self._ais_task is None or self._ais_task.done():
                self._ais_task = asyncio.create_task(self._ais_listener())
                logger.info("[marine] Started AISStream.io background listener")

            # Supplement with position-api for open-ocean coverage
            await self._poll_position_api()

            # Prune stale vessels
            self._prune_stale()

            # Convert cache to events
            events = self._cache_to_events()
            ais_count = sum(1 for e in events if e.get("source") == "AISStream.io")
            pos_count = sum(1 for e in events if e.get("source") == "MarineTraffic (position-api)")
            logger.info(
                "[marine] Tracking %d vessels (AISStream: %d, position-api: %d)",
                len(events), ais_count, pos_count
            )
            return events
        else:
            return self._collect_mock()

    async def _ais_listener(self):
        """Background WebSocket listener for AISStream.io."""
        try:
            import websockets
        except ImportError:
            logger.error("[marine] 'websockets' package not installed — run: pip install websockets")
            self._use_aisstream = False
            return

        while self._running:
            try:
                async with websockets.connect(self.AISSTREAM_URL) as ws:
                    # Send subscription
                    sub_msg = {
                        "APIKey": AISSTREAM_API_KEY,
                        "BoundingBoxes": SHIPPING_BBOXES,
                        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
                    }
                    await ws.send(json.dumps(sub_msg))
                    self._ais_connected = True
                    logger.info("[marine] Connected to AISStream.io — subscribed to %d zones",
                                len(SHIPPING_BBOXES))

                    async for msg_raw in ws:
                        try:
                            msg = json.loads(msg_raw)
                            msg_type = msg.get("MessageType", "")

                            if msg_type == "PositionReport":
                                self._handle_position(msg)
                            elif msg_type == "ShipStaticData":
                                self._handle_static(msg)
                        except Exception as e:
                            logger.debug("[marine] Message parse error: %s", e)

            except Exception as e:
                self._ais_connected = False
                logger.warning("[marine] AISStream.io disconnected: %s — reconnecting in 10s", e)
                await asyncio.sleep(10)

    def _handle_position(self, msg: dict):
        """Process a PositionReport message."""
        try:
            report = msg["Message"]["PositionReport"]
            meta_data = msg.get("MetaData", {})

            mmsi = str(report.get("UserID", ""))
            lat = report.get("Latitude")
            lon = report.get("Longitude")

            if not mmsi or lat is None or lon is None:
                return
            # Skip invalid/default positions
            if abs(lat) < 0.01 and abs(lon) < 0.01:
                return
            if lat > 89 or lat < -89:
                return

            sog = report.get("Sog", 0) or 0  # Speed over ground (knots)
            cog = report.get("Cog", 0) or 0  # Course over ground
            heading = report.get("TrueHeading", 511)  # 511 = not available
            if heading == 511:
                heading = cog  # Use COG as fallback
            nav_status = report.get("NavigationalStatus", 15)

            # Get vessel name from MetaData if available
            vessel_name = (meta_data.get("ShipName") or "").strip()
            if vessel_name in ("", "@@@@@@@@@@@@@@@@@@@@"):
                vessel_name = ""

            self._vessel_cache[mmsi] = {
                "mmsi": mmsi,
                "lat": round(lat, 5),
                "lon": round(lon, 5),
                "sog": round(sog, 1),
                "cog": round(cog, 1),
                "heading": round(heading, 1),
                "nav_status": nav_status,
                "nav_status_text": NAV_STATUS.get(nav_status, "Unknown"),
                "name": vessel_name or self._static_cache.get(mmsi, {}).get("name", ""),
                "updated": datetime.now(timezone.utc),
                "_source": "aisstream",
            }

            # Merge with any static data we have
            if mmsi in self._static_cache:
                self._vessel_cache[mmsi].update({
                    k: v for k, v in self._static_cache[mmsi].items()
                    if k not in ("mmsi", "lat", "lon", "updated")
                })

        except Exception as e:
            logger.debug("[marine] Position parse error: %s", e)

    def _handle_static(self, msg: dict):
        """Process a ShipStaticData message (vessel name, IMO, type)."""
        try:
            data = msg["Message"]["ShipStaticData"]
            mmsi = str(data.get("UserID", ""))
            if not mmsi:
                return

            name = (data.get("Name") or "").strip().rstrip("@")
            imo = data.get("ImoNumber", 0)
            callsign = (data.get("CallSign") or "").strip().rstrip("@")
            vessel_type_code = data.get("Type", 0)
            destination = (data.get("Destination") or "").strip().rstrip("@")

            static = {
                "name": name if name else "",
                "imo": f"IMO{imo}" if imo and imo > 0 else "",
                "callsign": callsign,
                "vessel_type": _vessel_type_label(vessel_type_code),
                "vessel_type_code": vessel_type_code,
                "destination": destination,
            }

            self._static_cache[mmsi] = static

            # Update existing cached vessel with new static info
            if mmsi in self._vessel_cache:
                for k, v in static.items():
                    if v:  # Only update non-empty fields
                        self._vessel_cache[mmsi][k] = v

        except Exception as e:
            logger.debug("[marine] Static data parse error: %s", e)

    def _prune_stale(self):
        """Remove vessels not updated in STALE_MINUTES."""
        now = datetime.now(timezone.utc)
        stale = [
            mmsi for mmsi, v in self._vessel_cache.items()
            if (now - v["updated"]).total_seconds() > self.STALE_MINUTES * 60
        ]
        for mmsi in stale:
            del self._vessel_cache[mmsi]
        if stale:
            logger.debug("[marine] Pruned %d stale vessels", len(stale))

    # ── position-api supplementary polling ─────────────────────────
    async def _poll_position_api(self):
        """Poll position-api for open-ocean vessels (round-robin by area)."""
        now = _time.monotonic()

        # Respect poll interval
        if now - self._posapi_last_poll < POSITION_API_POLL_INTERVAL:
            return

        # Check availability on first call
        if self._posapi_available is None:
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    resp = await client.get(f"{POSITION_API_URL}/")
                    self._posapi_available = resp.status_code < 500
            except Exception:
                self._posapi_available = False

            if self._posapi_available:
                logger.info("[marine] position-api detected at %s", POSITION_API_URL)
            else:
                logger.info(
                    "[marine] position-api not available at %s — "
                    "using AISStream only. To enable: "
                    "cd position-api && npm start",
                    POSITION_API_URL,
                )
                return

        if not self._posapi_available:
            return

        # Pick next area (round-robin 2 areas per poll for coverage)
        areas_to_fetch = []
        for _ in range(2):
            areas_to_fetch.append(OCEAN_AREAS[self._posapi_area_idx])
            self._posapi_area_idx = (self._posapi_area_idx + 1) % len(OCEAN_AREAS)

        area_str = ",".join(areas_to_fetch)
        url = f"{POSITION_API_URL}/legacy/getVesselsInArea/{area_str}"

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.debug("[marine] position-api returned %d for %s", resp.status_code, area_str)
                    self._posapi_last_poll = now
                    return

                data = resp.json()
                if not isinstance(data, list):
                    logger.debug("[marine] position-api unexpected response type: %s", type(data))
                    self._posapi_last_poll = now
                    return

            added = 0
            for vessel in data:
                try:
                    mmsi = str(vessel.get("mmsi", "") or "")
                    lat = vessel.get("lat")
                    lon = vessel.get("lon")

                    if not mmsi or lat is None or lon is None:
                        continue
                    lat = float(lat)
                    lon = float(lon)
                    if abs(lat) < 0.01 and abs(lon) < 0.01:
                        continue

                    # Only add if NOT already in cache from AISStream
                    # (AISStream data is fresher/real-time)
                    if mmsi in self._vessel_cache:
                        existing = self._vessel_cache[mmsi]
                        if existing.get("_source") == "aisstream":
                            continue  # AISStream takes priority

                    name = str(vessel.get("name", "") or "").strip()
                    speed = float(vessel.get("speed", 0) or 0)
                    vtype = str(vessel.get("type", "Vessel") or "Vessel")
                    imo_raw = vessel.get("imo", "")
                    imo = f"IMO{imo_raw}" if imo_raw and str(imo_raw) not in ("0", "") else ""
                    callsign = str(vessel.get("callsign", "") or "").strip()
                    destination = str(vessel.get("destination", "") or "").strip()
                    area = str(vessel.get("area", "") or "").strip()
                    country = str(vessel.get("country", "") or "").strip()

                    self._vessel_cache[mmsi] = {
                        "mmsi": mmsi,
                        "lat": round(lat, 5),
                        "lon": round(lon, 5),
                        "sog": round(speed, 1),
                        "cog": 0,
                        "heading": 511,  # Not available from position-api
                        "nav_status": 15,
                        "nav_status_text": "Not defined",
                        "name": name if name else "",
                        "vessel_type": vtype,
                        "imo": imo,
                        "callsign": callsign,
                        "destination": destination,
                        "updated": datetime.now(timezone.utc),
                        "_source": "posapi",
                        "_area": area,
                        "_country": country,
                    }
                    added += 1

                except Exception as e:
                    logger.debug("[marine] position-api vessel parse error: %s", e)
                    continue

            self._posapi_vessel_count = sum(
                1 for v in self._vessel_cache.values() if v.get("_source") == "posapi"
            )
            if added > 0:
                logger.info(
                    "[marine] position-api: +%d vessels from %s (total posapi: %d)",
                    added, area_str, self._posapi_vessel_count
                )

        except httpx.ConnectError:
            # position-api went down
            if self._posapi_available:
                logger.warning("[marine] position-api connection lost — will retry")
            self._posapi_available = None  # Re-check next time
        except Exception as e:
            logger.warning("[marine] position-api fetch error: %s", e)

        self._posapi_last_poll = now

    def _cache_to_events(self) -> list[dict]:
        """Convert vessel cache to OsintEvent list.

        Military vessels are emitted with type='military_marine' so they
        render on a separate layer from civilian traffic.
        """
        events = []
        vessels = sorted(
            self._vessel_cache.values(),
            key=lambda v: v["updated"],
            reverse=True,
        )[:self.MAX_VESSELS]

        for v in vessels:
            mmsi = v["mmsi"]
            name = v.get("name", "") or f"MMSI {mmsi}"
            vtype = v.get("vessel_type", "Vessel")
            imo = v.get("imo", "")
            callsign = v.get("callsign", "")
            destination = v.get("destination", "")

            # ── Military classification ─────────────────────────────────
            is_military, mil_label = MilitaryMarineDetector.classify(v)
            
            # ── High Value Filter ───────────────────────────────────────
            # Only track military, carrier groups, oil tankers, destroyers, frigates, patrollers, escorts
            vtype_code = int(v.get("vessel_type_code", 0) or 0)
            is_tanker = (80 <= vtype_code <= 89) or ("tanker" in vtype.lower())
            
            name_lower = name.lower()
            dest_lower = destination.lower()
            high_value_kws = ["carrier", "destroyer", "frigate", "patrol", "escort", "warship", "navy", "coast guard", "corvette", "submarine", "cruiser"]
            is_high_value_named = any(kw in name_lower or kw in vtype.lower() or kw in dest_lower for kw in high_value_kws)
            
            if not (is_military or is_tanker or is_high_value_named):
                continue

            event_type = "military_marine" if is_military else "marine"
            severity = 3 if is_military else 1  # Military vessels are higher severity

            desc_parts = [vtype]
            if is_military:
                desc_parts.insert(0, f"⚓ {mil_label}")
            if v["sog"] > 0:
                desc_parts.append(f"{v['sog']} kts")
            if v["heading"] != 511:
                desc_parts.append(f"HDG {v['heading']:.0f}°")
            desc_parts.append(f"MMSI {mmsi}")
            if imo:
                desc_parts.append(imo)

            source = "MarineTraffic (position-api)" if v.get("_source") == "posapi" else "AISStream.io"
            if is_military:
                source = f"AIS Military ({mil_label})"

            events.append({
                "id": f"ais-{mmsi}",
                "type": event_type,
                "latitude": v["lat"],
                "longitude": v["lon"],
                "severity": severity,
                "timestamp": v["updated"].isoformat(),
                "source": source,
                "title": f"{name}" + (f" — {destination}" if destination else ""),
                "description": " · ".join(desc_parts),
                "metadata": {
                    "vessel_name": name,
                    "vessel_type": vtype,
                    "mmsi": mmsi,
                    "imo": imo,
                    "callsign": callsign,
                    "speed_knots": v["sog"],
                    "heading": v["heading"],
                    "course": v["cog"],
                    "nav_status": v.get("nav_status_text", ""),
                    "destination": destination,
                    "is_military": is_military,
                    "navy": mil_label if is_military else "",
                },
            })

        return events

    # ── Mock fallback ──────────────────────────────────────────────
    def _collect_mock(self) -> list[dict]:
        """Fallback: stable mock vessels with gradual drift."""
        if not self._mock_initialized:
            self._init_mock()

        self._drift_mock()

        events = []
        now = datetime.now(timezone.utc).isoformat()

        for vid, v in self._mock_vessels.items():
            is_tanker = "tanker" in v["type"].lower()
            
            name_lower = v["name"].lower()
            type_lower = v["type"].lower()
            high_value_kws = ["carrier", "destroyer", "frigate", "patrol", "escort", "warship", "navy", "coast guard", "corvette", "submarine", "cruiser"]
            is_high_value = any(kw in name_lower or kw in type_lower for kw in high_value_kws)
            
            # Assume some mock vessels like Front Cougar might be tankers.
            # Only yield if high value or tanker
            if not (is_tanker or is_high_value):
                continue
                
            events.append({
                "id": vid,
                "type": "marine",
                "latitude": v["lat"],
                "longitude": v["lon"],
                "severity": 1,
                "timestamp": now,
                "source": "AIS (Mock)",
                "title": f"{v['name']} — {v['lane']}",
                "description": (
                    f"{v['type']} · {v['speed']} kts · HDG {v['heading']:.0f}° · "
                    f"MMSI {v['mmsi']}"
                    + (f" · {v['imo']}" if v.get('imo') else "")
                ),
                "metadata": {
                    "vessel_name": v["name"],
                    "vessel_type": v["type"],
                    "mmsi": v["mmsi"],
                    "imo": v.get("imo", ""),
                    "callsign": v.get("callsign", ""),
                    "speed_knots": v["speed"],
                    "heading": v["heading"],
                    "lane": v["lane"],
                    "flag_state": v.get("flag", ""),
                },
            })

        logger.info("[marine] Tracking %d mock vessels", len(events))
        return events

    def _init_mock(self):
        """Init mock vessels from roster."""
        self._mock_vessels: dict[str, dict] = {}
        for (vid, name, vtype, mmsi, imo, flag, callsign,
             lat, lon, hdg, spd, lane) in MOCK_VESSELS:
            self._mock_vessels[vid] = {
                "name": name, "type": vtype, "mmsi": mmsi,
                "imo": f"IMO{imo}" if imo else "", "flag": flag,
                "callsign": callsign, "lane": lane,
                "lat": lat, "lon": lon, "heading": hdg, "speed": spd,
            }
        self._mock_initialized = True
        logger.info("[marine] Initialized %d mock vessels", len(MOCK_VESSELS))

    def _drift_mock(self):
        """Small position drift for realism."""
        for v in self._mock_vessels.values():
            hdg_rad = math.radians(v["heading"])
            drift_nm = v["speed"] * (self.interval / 3600)
            drift_deg = drift_nm / 60

            v["lat"] = round(v["lat"] + drift_deg * math.cos(hdg_rad) + random.uniform(-0.01, 0.01), 4)
            v["lon"] = round(v["lon"] + drift_deg * math.sin(hdg_rad) + random.uniform(-0.01, 0.01), 4)
            v["heading"] = round((v["heading"] + random.uniform(-2, 2)) % 360, 1)
            v["speed"] = round(max(3, v["speed"] + random.uniform(-0.3, 0.3)), 1)
