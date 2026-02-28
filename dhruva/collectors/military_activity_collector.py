"""Dhruva — Military Aircraft Detector (4-layer detection hierarchy).

Detection priority (highest → lowest confidence):

  1. DB FLAG  — hexdb.io lookup by ICAO24:
                If `RegisteredOwners` or `Type` matches military keywords /
                aircraft type codes → CONFIRMED military.
                Results are cached in-memory (ICAO24 doesn't change).

  2. LADD/PIA — Privacy signals:
                LADD: hexdb returns data but owner is blank/LADD-blocked.
                PIA:  hexdb returns 404 (Privacy ICAO Address — rotating hex).
                Either + supporting heuristic signal → SUSPECTED military.

  3. HEURISTICS — Using OpenSky state-vector fields we already receive:
                  • Category = 7  (High Performance >5G, 400 kts → fighters)
                  • Speed > 450 kts below FL200
                  • Altitude > FL500  (U-2, Global Hawk)
                  • Squawk 7700/7777  (emergency / military intercept)
                  • No callsign at all

  4. CALLSIGN — Public military callsign prefixes (NATO, USAF, IAF, etc.)
                Reliable for Western militaries that broadcast standard CSs.

Also collects real NAVAREA broadcast warnings from NGA MSI (maritime / military
exercise zones — type "military").

No mock data. All outputs cite their detection source.
"""

import asyncio
import logging
import hashlib
from datetime import datetime, timezone, timedelta

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

# ── External DB ───────────────────────────────────────────────────────────
NGA_MSI_BROADCAST_WARN_URL = "https://msi.gs.mil/api/publications/broadcast-warn"
HEXDB_URL = "https://hexdb.io/api/v1/aircraft/{icao}"

# ── ICAO24 hex ranges that are 100% military-exclusive ───────────────────
# Removed aggressively broad ICAO prefix matching due to civilian false-positives.
MILITARY_ICAO_PREFIXES: dict[str, str] = {}

# ── Known military ICAO aircraft type codes ───────────────────────────────
# Cross-referenced from ICAO Doc 8643 + ADS-B Exchange military list.
MILITARY_TYPE_CODES: set[str] = {
    # USAF bombers
    "B52", "B1", "B2", "B21",
    # USAF / allied transports
    "C5", "C17", "C130", "C135", "C141", "C160", "C295", "C27",
    "A400",                            # Airbus A400M (all are military)
    # VIP / Staff transport
    "C137", "VC25",                    # Air Force One variants
    # Tankers
    "KC10", "KC135", "KC46", "MRTT", "KC130",
    # USAF fighters
    "F15", "F16", "F22", "F35", "F117",
    # US Navy
    "F18", "FA18", "E2", "S3",
    # Attack / CAS
    "A10", "AC130",
    # ISR / SIGINT
    "E3", "E8", "E6", "U2", "TR1", "RC135", "EP3",
    # UAS
    "RQ4", "MQ9", "MQ1", "RQ7",
    # Rotary
    "MH60", "UH60", "CH47", "AH64", "AH1",
    # V/STOL
    "V22", "MV22",
    # Trainers (military-only types)
    "T38", "T45", "T6", "T1",
    # Foreign military types
    "SU27", "SU30", "SU34", "SU35", "SU57",
    "MIG29", "MIG31",
    "TU95", "TU160", "TU22",
    "IL76", "IL78", "AN124",           # Russian military transports
    "JAS39",                           # Gripen
    "TYPHOON", "EUFI",                 # Eurofighter
    "RAFAL",                           # Rafale
    "TRND",                            # Tornado
    "HAWK",                            # Hawk trainer (RAF/IAF)
    "PC9", "PC21",                     # Pilatus trainers (military only)
    "L39",                             # Albatros trainer
}

# ── Keywords in RegisteredOwners that confirm military ───────────────────
MILITARY_OWNER_KEYWORDS: list[str] = [
    "air force", "navy", "army", "marine corps", "marines", "military",
    "defense", "defence", "department of defense", "department of defence",
    "dod", "usaf", "usn", "usmc", "us army",
    "royal air force", "raf",
    "luftwaffe", "bundeswehr",
    "armée de l'air", "armee de l air",
    "indian air force", "iaf",
    "pla air force", "plaaf", "pla navy",
    "russian air force", "russian aerospace", "vks",
    "israel air force", "israeli air force",
    "pakistan air force", "paf",
    "royal australian air force", "raaf",
    "turkish air force",
    "french navy", "marine nationale",
    "nato",
    "national security",
]

# ── Callsign prefixes (reliable for Western/NATO, limited for others) ────
MILITARY_CALLSIGN_PATTERNS: list[str] = [
    # US Air Force
    "RCH", "REACH", "RRR", "EVAC", "FORTE", "JAKE", "SPAR", "SAM",
    "EXEC", "IRON", "NOBLE", "DRAGON", "GATOR", "HAVOC", "SLICK",
    "SWIFT", "HOMER", "QUID",
    # US Army
    "DUKE", "ARMY", "COBRA", "APACHE", "HAWK", "VIPER", "WOLF",
    # US Navy / Marines
    "NAVY", "TOPCAT", "ROWDY", "STORM", "MARINES", "VMGR",
    # UK RAF
    "ASCOT", "TARTAN", "VANGUARD", "VIKING", "TUDOR", "BENSON",
    # French Air Force
    "MMF", "FAF", "COTAM",
    # German Air Force
    "GAF", "GAFONE",
    # Italian Air Force
    "IAM", "ISF",
    # Spanish Air Force
    "SPAF",
    # NATO
    "NATO", "NCHO", "NAEW",
    # Israeli Air Force
    "IAF", "ELI",
    # Indian Air Force (callsign only — NOT hex prefix 80)
    "INCA", "MAGNUS", "INDIA",
    # Russian Air Force
    "RFR", "RUSS",
    # Chinese PLA
    "CFC", "CNV", "PLAAF",
    # Pakistani Air Force
    "PAF", "PAKAF",
    # Turkish Air Force
    "TUAF", "TURKISH",
    # Coalition / UN
    "AIRMOVE", "USMIL",
]

# ── Freshness ─────────────────────────────────────────────────────────────
NAVAREA_FRESHNESS_HOURS = 48
DB_CACHE_TTL_HOURS = 24   # hexdb results don't change, but evict daily


class MilitaryActivityCollector(BaseCollector):
    """Infers military activity zones from real OSINT signals."""

    def __init__(self, interval: int = 120):
        super().__init__(name="military", interval=interval)
        self._last_fetched_at: datetime | None = None

    async def collect(self) -> list[dict]:
        events = []
        try:
            navarea_events = await self._fetch_navarea_warnings()
            events.extend(navarea_events)
        except Exception as e:
            logger.warning("[military] NGA NAVAREA fetch failed: %s", e)
        self._last_fetched_at = datetime.now(timezone.utc)
        return events

    # ── NAVAREA warnings ──────────────────────────────────────────────────

    async def _fetch_navarea_warnings(self) -> list[dict]:
        params = {"output": "json", "status": "active"}
        try:
            data = await self.fetch_json(NGA_MSI_BROADCAST_WARN_URL, params=params)
        except Exception as e:
            logger.warning("[military] NGA MSI API error: %s", e)
            return []

        warnings = data if isinstance(data, list) else data.get("broadcast-warn", [])
        if not warnings:
            warnings = data.get("broadcastWarns", data.get("results", []))

        events = []
        for warn in warnings:
            try:
                event = self._parse_navarea_warning(warn)
                if event:
                    events.append(event)
            except Exception as e:
                logger.debug("[military] Skipping NAVAREA warning: %s", e)
        logger.info("[military] NGA NAVAREA returned %d active warnings", len(events))
        return events

    def _parse_navarea_warning(self, warn: dict) -> dict | None:
        lat = warn.get("latitude") or warn.get("lat")
        lon = warn.get("longitude") or warn.get("lon")
        position = warn.get("position", {})
        if not lat and position:
            lat = position.get("latitude") or position.get("lat")
            lon = position.get("longitude") or position.get("lon")
        if not lat:
            area = warn.get("area", {})
            if area:
                lat = area.get("latitude")
                lon = area.get("longitude")
        if lat is None or lon is None:
            return None
        try:
            lat, lon = float(lat), float(lon)
        except (ValueError, TypeError):
            return None

        warn_number = warn.get("msgNumber", warn.get("number", ""))
        warn_year   = warn.get("msgYear",   warn.get("year",   ""))
        navarea     = warn.get("navArea",   warn.get("area_name", ""))
        text        = warn.get("text", warn.get("message", "")) or \
                      warn.get("messageText", warn.get("subject", ""))
        authority   = warn.get("authority", "NGA")
        status      = warn.get("status", "active")
        issue_date  = warn.get("issueDate", warn.get("date", ""))
        cancel_date = warn.get("cancelDate", "")
        warning_type = warn.get("type", "NAVAREA Warning")
        subregion   = warn.get("subregion", "")

        text_upper = (text or "").upper()
        if any(k in text_upper for k in ["MISSILE", "FIRING", "WEAPONS", "MILITARY EXERCISE"]):
            severity, inferred_type = 4, "Military Exercise / Weapons Activity"
        elif any(k in text_upper for k in ["SUBMARINE", "NAVAL", "WARSHIP"]):
            severity, inferred_type = 3, "Naval Activity"
        elif any(k in text_upper for k in ["RESTRICTED", "DANGER", "PROHIBITED"]):
            severity, inferred_type = 3, "Restricted Zone"
        elif any(k in text_upper for k in ["MINE", "ORDNANCE", "UXO"]):
            severity, inferred_type = 4, "Mine / Ordnance Warning"
        else:
            severity, inferred_type = 2, "Maritime Safety Warning"

        warn_id = f"{navarea}-{warn_number}-{warn_year}" if warn_number else \
                  hashlib.md5(f"{lat}{lon}{(text or '')[:50]}".encode()).hexdigest()[:12]

        desc = (text or inferred_type)[:200].strip()
        if len(text or "") > 200:
            desc += "..."

        return {
            "id": f"mil-nav-{warn_id}",
            "type": "military",
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "severity": severity,
            "timestamp": issue_date or datetime.now(timezone.utc).isoformat(),
            "source": f"NGA MSI NAVAREA {navarea}",
            "title": f"{inferred_type} — NAVAREA {navarea}",
            "description": desc,
            "metadata": {
                "warning_type": warning_type,
                "inferred_type": inferred_type,
                "navarea": navarea,
                "subregion": subregion,
                "msg_number": str(warn_number),
                "msg_year": str(warn_year),
                "authority": authority,
                "status": status,
                "issue_date": issue_date,
                "cancel_date": cancel_date,
                "full_text": (text or "")[:500],
            },
        }


# ═══════════════════════════════════════════════════════════════════════════
#  Military Aircraft Detector — called from main.py after each ADS-B fetch
# ═══════════════════════════════════════════════════════════════════════════

class MilitaryAircraftDetector:
    """4-layer military aircraft detection with hexdb.io as primary source.

    Layer 1 — DB Flag:     hexdb.io ICAO24 lookup → type codes + owner keywords
    Layer 2 — LADD / PIA: privacy signals → LADD owner flag, PIA (404)
    Layer 3 — Heuristics:  OpenSky category, speed, altitude, squawk
    Layer 4 — Callsign:    military callsign prefix matching

    Results per ICAO24 are cached for DB_CACHE_TTL_HOURS to avoid
    redundant API calls (the same aircraft flies every day).
    """

    def __init__(self):
        # Cache: icao24 → {"result": DetectionResult|None, "cached_at": float}
        self._cache: dict[str, dict] = {}
        self._http_client = None
        self._pending: set[str] = set()   # ICAO24s currently being fetched
        self._lock = asyncio.Lock()

    async def _get_http(self):
        if not self._http_client:
            import httpx
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client

    # ── Layer 1 + 2: hexdb.io lookup ──────────────────────────────────────

    async def _lookup_hexdb(self, icao24: str) -> dict | None:
        """Return hexdb aircraft record, or None if PIA / not found."""
        import time
        now = time.monotonic()

        async with self._lock:
            cached = self._cache.get(icao24)
            if cached:
                age_h = (now - cached["cached_at"]) / 3600
                if age_h < DB_CACHE_TTL_HOURS:
                    return cached["record"]

        try:
            http = await self._get_http()
            resp = await http.get(
                HEXDB_URL.format(icao=icao24.upper()),
                timeout=8.0,
            )
            if resp.status_code == 404:
                record = None   # PIA — no registration exists
            else:
                resp.raise_for_status()
                record = resp.json()
        except Exception as e:
            logger.debug("[mil-detect] hexdb lookup failed for %s: %s", icao24, e)
            return None   # Treat as unknown, not PIA

        async with self._lock:
            import time as _t
            self._cache[icao24] = {"record": record, "cached_at": _t.monotonic()}

        return record

    @staticmethod
    def _db_flag_check(record: dict) -> tuple[bool, str]:
        """Layer 1: Is the aircraft confirmed military by DB?"""
        if not record:
            return False, ""

        owner = (record.get("RegisteredOwners") or "").lower().strip()
        type_code = (record.get("ICAOTypeCode") or "").upper().strip()
        full_type = (record.get("Type") or "").upper().strip()

        # Owner keyword match
        for kw in MILITARY_OWNER_KEYWORDS:
            if kw in owner:
                return True, f"DB: owner='{record.get('RegisteredOwners')}'"

        # ICAO type code match (exact)
        if type_code in MILITARY_TYPE_CODES:
            return True, f"DB: type={type_code}"

        # Type name match (e.g. "Boeing C-17 Globemaster")
        for code in MILITARY_TYPE_CODES:
            if code in full_type.replace("-", "").replace(" ", ""):
                return True, f"DB: type_name={record.get('Type')}"

        return False, ""

    @staticmethod
    def _privacy_check(record: dict | None, callsign: str) -> tuple[bool, str]:
        """Layer 2: LADD or PIA signals."""
        if record is None:
            # hexdb returned 404 — this ICAO24 has no registration (PIA)
            return True, "PIA: no ICAO24 registration found"

        owner = (record.get("RegisteredOwners") or "").strip()
        if not owner or owner.upper() in ("LADD", "BLOCKED", "PRIVACY", "RESTRICTED"):
            return True, f"LADD: owner field blocked ('{owner}')"

        return False, ""

    @staticmethod
    def _heuristic_check(meta: dict) -> tuple[bool, str]:
        """Layer 3: Behavioral signals from OpenSky state vector."""
        signals = []

        # OpenSky ADS-B category 7 = High Performance (>5G, >400kts) — fighters
        cat_id = meta.get("category_id", 0)
        if cat_id == 7:
            signals.append("cat=HighPerf")

        # Very high speed at low altitude — commercial jets cruise at ~FL350+
        speed = meta.get("speed_knots", 0) or 0
        alt   = meta.get("altitude_ft", 0) or 0
        if speed > 450 and alt < 20000:
            signals.append(f"speed={speed:.0f}kts@{alt}ft")

        # Extreme altitude — U-2 (70,000ft), Global Hawk (60,000ft)
        if alt > 50000:
            signals.append(f"alt={alt}ft")

        # Squawk 7777 = military intercept in progress
        squawk = str(meta.get("squawk") or "")
        if squawk == "7777":
            signals.append("squawk=7777(intercept)")

        # SPI (Special Position Identification) — often set by military ATC
        if meta.get("spi"):
            signals.append("spi=true")

        # No callsign at all + not on ground → suspicious for monitoring
        callsign = (meta.get("callsign") or "").strip()
        if not callsign:
            signals.append("no-callsign")

        return bool(signals), f"heuristics:[{','.join(signals)}]"

    @staticmethod
    def _callsign_check(callsign: str) -> tuple[bool, str]:
        """Layer 4: Military callsign prefix matching."""
        cs = callsign.upper().strip()
        if not cs:
            return False, ""
        for pattern in MILITARY_CALLSIGN_PATTERNS:
            if cs.startswith(pattern):
                return True, f"callsign={cs}(prefix:{pattern})"
        return False, ""

    @staticmethod
    def _icao_prefix_check(icao24: str) -> tuple[bool, str]:
        """Confirmed-exclusive ICAO24 block (US DoD, NATO AWACS)."""
        icao_l = icao24.lower()
        for prefix, label in MILITARY_ICAO_PREFIXES.items():
            if icao_l.startswith(prefix):
                return True, f"icao_block={label}({prefix}xxxx)"
        return False, ""

    async def detect(self, aircraft_events: list[dict]) -> list[dict]:
        """Run all 4 detection layers against a batch of ADS-B events.

        Returns list of military_aircraft OsintEvent dicts.
        """
        # Deduplicate by ICAO24 (take freshest position)
        by_icao: dict[str, dict] = {}
        for event in aircraft_events:
            meta = event.get("metadata", {})
            icao24 = (meta.get("icao24") or "").lower().strip()
            if icao24:
                by_icao[icao24] = event

        if not by_icao:
            return []

        # Batch hexdb lookups concurrently (max 10 at once to be polite)
        sem = asyncio.Semaphore(10)

        async def safe_lookup(icao24: str):
            async with sem:
                return icao24, await self._lookup_hexdb(icao24)

        lookup_tasks = [safe_lookup(icao) for icao in by_icao]
        lookup_results: dict[str, dict | None] = {}
        for icao, record in await asyncio.gather(*lookup_tasks):
            lookup_results[icao] = record

        # Now run all 4 layers for each aircraft
        now = datetime.now(timezone.utc)
        military: list[dict] = []

        for icao24, event in by_icao.items():
            meta     = event.get("metadata", {})
            callsign = (meta.get("callsign") or "").strip()
            record   = lookup_results.get(icao24)

            detection_source = ""
            confidence       = ""

            # ── Layer 0: Confirmed exclusive ICAO block ────────────────
            hit, reason = self._icao_prefix_check(icao24)
            if hit:
                detection_source = "CONFIRMED"
                confidence       = reason
            else:
                # ── Layer 1: DB Flag ───────────────────────────────────
                hit, reason = self._db_flag_check(record)
                if hit:
                    detection_source = "CONFIRMED"
                    confidence       = reason
                else:
                    # ── Layer 2: LADD / PIA ───────────────────────────
                    priv_hit, priv_reason = self._privacy_check(record, callsign)

                    # ── Layer 3: Heuristics ───────────────────────────
                    heur_hit, heur_reason = self._heuristic_check(meta)

                    # ── Layer 4: Callsign ─────────────────────────────
                    cs_hit, cs_reason = self._callsign_check(callsign)

                    # Scoring: need at least 2 signals for SUSPECTED,
                    # OR callsign alone is sufficient (high confidence)
                    signals_hit = sum([priv_hit, heur_hit, cs_hit])

                    if cs_hit:
                        detection_source = "CONFIRMED"
                        confidence       = cs_reason
                    elif signals_hit >= 2:
                        detection_source = "SUSPECTED"
                        reasons = [r for hit, r in
                                   [(priv_hit, priv_reason), (heur_hit, heur_reason)]
                                   if hit]
                        confidence = " + ".join(reasons)
                    elif priv_hit and heur_hit:
                        detection_source = "SUSPECTED"
                        confidence = f"{priv_reason} + {heur_reason}"
                    else:
                        continue   # Not enough signals → skip

            # Build military_aircraft event
            owner = ""
            ac_type = ""
            if record:
                owner   = record.get("RegisteredOwners", "")
                ac_type = record.get("ICAOTypeCode") or record.get("Type", "")

            mil_label = owner or _infer_mil_label(icao24, callsign)

            military.append({
                "id": f"mil-air-{icao24 or callsign}",
                "type": "military_aircraft",
                "latitude": event["latitude"],
                "longitude": event["longitude"],
                "severity": 3 if detection_source == "CONFIRMED" else 2,
                "timestamp": event.get("timestamp", now.isoformat()),
                "source": f"ADS-B + hexdb.io [{detection_source}]",
                "title": f"Military Aircraft — {callsign or icao24.upper()}",
                "description": (
                    f"{detection_source}: {confidence} · "
                    f"{event.get('description', '')}"
                ),
                "metadata": {
                    "detection_source": detection_source,
                    "detection_confidence": confidence,
                    "military_label": mil_label,
                    "registered_owner": owner,
                    "aircraft_type": ac_type,
                    "callsign": callsign,
                    "icao24": icao24,
                    "original_source": event.get("source", ""),
                    "altitude_ft": meta.get("altitude_ft", 0),
                    "speed_knots": meta.get("speed_knots", 0),
                    "heading": meta.get("heading", 0),
                    "squawk": meta.get("squawk"),
                    "category": meta.get("category", ""),
                },
            })

        confirmed = sum(1 for e in military if e["metadata"]["detection_source"] == "CONFIRMED")
        suspected = len(military) - confirmed
        logger.info(
            "[mil-detect] %d military aircraft detected (%d confirmed, %d suspected)",
            len(military), confirmed, suspected,
        )
        return military


def _infer_mil_label(icao24: str, callsign: str) -> str:
    """Best-effort human label when DB owner is unavailable."""
    icao_l = icao24.lower()
    for prefix, label in MILITARY_ICAO_PREFIXES.items():
        if icao_l.startswith(prefix):
            return label
    cs = callsign.upper()
    for pattern in MILITARY_CALLSIGN_PATTERNS:
        if cs.startswith(pattern):
            return f"Military ({pattern})"
    return "Military (inferred)"


# ── Module-level singleton — shared across all calls from main.py ──────
_detector = MilitaryAircraftDetector()


async def infer_military_aircraft(aircraft_events: list[dict]) -> list[dict]:
    """Public async entry-point called from main.py."""
    return await _detector.detect(aircraft_events)
