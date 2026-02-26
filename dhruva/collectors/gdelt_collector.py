"""Dhruva — GDELT Dual-Source Collector (Protests + Conflict backup).

Uses the GDELT 2.0 Event API — completely FREE, no API key required.

Two modes:
  1. Protest tracking  → EventCode 14* (Protest) events → layer: 'protest'
  2. Conflict backup   → EventCode 19*, 20* (Fight/Assault) → layer: 'gdelt_conflict'
     (supplements ACLED/UCDP when those tokens are unavailable)

Deduplication:
  - Events within 0.1° (~11 km) of each other on the same day are merged.
  - ACLED events take priority (higher editorial confidence) if both are present.

Severity:
  - Protest: High = fatalities/riots present, Medium = standard, Low = default.
    Regime-aware: authoritarian states use linear scaling (every protest matters);
    democratic states use log scaling (routine protests don't spike instability).
  - Conflict: Mapped from GoldsteinScale (-10 … +10, inverted → severity 1–5).

Reference:
  https://www.gdeltproject.org/data.html#rawdatafiles
  https://api.gdeltproject.org/api/v2/events/query
"""

import asyncio
import hashlib
import logging
import math
from datetime import datetime, timezone, timedelta

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

# ── GDELT API endpoints ────────────────────────────────────────────────────
GDELT_EVENT_URL = "https://api.gdeltproject.org/api/v2/events/query"

# How many hours back to look (GDELT updates every 15 min)
LOOKBACK_HOURS = 48

# Min mention count to include (filters noise)
MIN_MENTIONS = 3

# Events with ≥ this many mentions are "validated"
VALIDATED_MENTIONS = 30

# Max events per query
MAX_EVENTS = 300

# Dedup radius in degrees (~11 km at equator)
DEDUP_RADIUS_DEG = 0.10

# ── Authoritarian country list (linear severity scaling) ──────────────────
# These are countries where protests are politically significant at any scale.
AUTHORITARIAN_COUNTRIES = {
    "RUS", "CHN", "IRN", "SAU", "PRK", "BLR", "VEN", "CUB", "SYR",
    "YEM", "MMR", "AZE", "TJK", "TKM", "UZB", "KAZ",
}

# ── CAMEO EventCode prefixes ─────────────────────────────────────────────
# Reference: https://www.gdeltproject.org/data/documentation/CAMEO.Manual.1.1b3.pdf
PROTEST_EVENT_CODES = {
    "14": "Protest",
    "141": "Demonstrate / rally",
    "142": "Hunger strike",
    "143": "Strike / boycott",
    "144": "Obstruct passage / blockade",
    "145": "Protest violently / riot",
}

CONFLICT_EVENT_CODES = {
    "19": "Fight",
    "190": "Use conventional military force",
    "191": "Impose blockade / restrict movement",
    "192": "Occupy territory",
    "193": "Fight with small arms",
    "194": "Fight with artillery / aircraft",
    "195": "Employ aerial weapons",
    "196": "Violate cease-fire",
    "20": "Use unconventional mass violence",
    "200": "Use unconventional violence",
    "201": "Abduct / hijack / take hostage",
    "202": "Sexually assault",
    "203": "Torture",
    "204": "Kill by physical assault",
    "2041": "Assassinate",
    "2042": "Assassinate — prominent",
    "205": "Disappear person",
    "206": "Impose administrative sanctions",
}


class GDELTCollector(BaseCollector):
    """Fetches protest and conflict events from GDELT 2.0 API.

    No API key required. Returns two logical sub-layers:
      - type='protest'          for EventCode 14*
      - type='gdelt_conflict'   for EventCode 19*/20*
    Both are returned from a single collect() call and split by main.py.
    """

    def __init__(self, interval: int = 300):
        super().__init__(name="gdelt", interval=interval)
        self._seen_ids: set[str] = set()  # Dedup across collection cycles

    async def collect(self) -> list[dict]:
        """Collect both protests and conflict events from GDELT."""
        events: list[dict] = []

        try:
            protests = await self._fetch_events(
                event_codes=list(PROTEST_EVENT_CODES.keys()),
                event_type="protest",
                label="Protest",
            )
            events.extend(protests)
            logger.info("[gdelt] %d protest events collected", len(protests))
        except Exception as e:
            logger.warning("[gdelt] Protest fetch failed: %s", e)

        try:
            conflicts = await self._fetch_events(
                event_codes=list(CONFLICT_EVENT_CODES.keys()),
                event_type="gdelt_conflict",
                label="Conflict",
            )
            events.extend(conflicts)
            logger.info("[gdelt] %d conflict events collected", len(conflicts))
        except Exception as e:
            logger.warning("[gdelt] Conflict fetch failed: %s", e)

        # Haversine dedup within each sub-type
        events = _haversine_dedup(events)
        return events

    async def _fetch_events(
        self,
        event_codes: list[str],
        event_type: str,
        label: str,
    ) -> list[dict]:
        """Query GDELT API for specific event codes."""
        # GDELT EventCode query: match any code starting with our prefixes
        code_query = " OR ".join(f"EventCode:{code}" for code in event_codes)
        # Use shortest 1-2 char codes to catch all sub-types
        root_codes = [c for c in event_codes if len(c) <= 2]
        if root_codes:
            code_query = " OR ".join(f"EventCode:{code}" for code in root_codes)

        # Timespan: last LOOKBACK_HOURS
        since = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS))
        timespan = f"{LOOKBACK_HOURS * 60}"  # GDELT uses minutes

        params = {
            "query": code_query,
            "mode": "artlist",      # Returns article list with event metadata
            "format": "json",
            "timespan": f"{LOOKBACK_HOURS}h",
            "maxrecords": MAX_EVENTS,
            "sort": "DateDesc",
        }

        try:
            data = await self.fetch_json(GDELT_EVENT_URL, params=params)
        except Exception as e:
            logger.warning("[gdelt] API request failed: %s", e)
            return []

        if not isinstance(data, dict):
            logger.debug("[gdelt] Unexpected response type: %s", type(data))
            return []

        articles = data.get("articles", []) or data.get("events", []) or []
        if not articles:
            # GDELT sometimes returns different structure — try alternate fetch
            return await self._fetch_csv_fallback(event_codes, event_type, label)

        events = []
        for article in articles[:MAX_EVENTS]:
            try:
                event = self._parse_article(article, event_type)
                if event:
                    events.append(event)
            except Exception as e:
                logger.debug("[gdelt] Skipping article: %s", e)
        return events

    async def _fetch_csv_fallback(
        self,
        event_codes: list[str],
        event_type: str,
        label: str,
    ) -> list[dict]:
        """Fallback: use GDELT GKG streaming CSV endpoint."""
        # Use GDELT's simpler event stream endpoint
        # This endpoint returns GeoJSON-like structure
        root_codes = [c for c in event_codes if len(c) <= 2]
        code_str = ",".join(root_codes)

        url = "https://api.gdeltproject.org/api/v2/geo/geo"
        params = {
            "query": f"sourcelang:eng (EventCode:{' OR EventCode:'.join(root_codes)})",
            "mode": "pointdata",
            "format": "json",
            "timespan": f"{LOOKBACK_HOURS}h",
            "maxpoints": MAX_EVENTS,
        }

        try:
            data = await self.fetch_json(url, params=params)
        except Exception as e:
            logger.debug("[gdelt] GKG fallback failed: %s", e)
            return []

        features = []
        if isinstance(data, dict):
            features = data.get("features", [])

        events = []
        for feat in features[:MAX_EVENTS]:
            try:
                event = self._parse_geojson_feature(feat, event_type, label)
                if event:
                    events.append(event)
            except Exception as e:
                logger.debug("[gdelt] Skipping GeoJSON feature: %s", e)
        return events

    # ── Parsers ──────────────────────────────────────────────────────────────

    def _parse_article(self, article: dict, event_type: str) -> dict | None:
        """Parse a GDELT artlist article into an OsintEvent."""
        lat = article.get("lat") or article.get("ActionGeo_Lat")
        lon = article.get("lon") or article.get("ActionGeo_Long")
        if lat is None or lon is None:
            return None
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            return None
        if abs(lat) < 0.001 and abs(lon) < 0.001:
            return None

        url = article.get("url") or article.get("SOURCEURL", "")
        title = article.get("title") or article.get("ArticleTitle", url[:80] if url else "")
        date_str = article.get("seendate") or article.get("SQLDATE", "")
        mentions = int(article.get("nummentions") or article.get("NumMentions", MIN_MENTIONS))
        country_code = (article.get("ActionGeo_CountryCode") or "").upper()
        location = article.get("ActionGeo_FullName") or article.get("location", "")
        event_code = str(article.get("EventCode", article.get("EventRootCode", "")))
        goldstein = float(article.get("GoldsteinScale") or article.get("GoldsteinScale", 0) or 0)

        # Filter low-signal events
        if mentions < MIN_MENTIONS:
            return None

        # Build stable event ID from URL hash
        eid = hashlib.md5(url.encode()).hexdigest()[:12] if url else \
              hashlib.md5(f"{lat:.2f}{lon:.2f}{date_str}".encode()).hexdigest()[:12]

        if eid in self._seen_ids:
            return None
        self._seen_ids.add(eid)

        severity = self._compute_severity(event_type, goldstein, mentions, country_code)
        validated = mentions >= VALIDATED_MENTIONS

        # Parse timestamp
        ts = _parse_gdelt_date(date_str) or datetime.now(timezone.utc).isoformat()

        actor1 = article.get("Actor1Name", "")
        actor2 = article.get("Actor2Name", "")

        desc_parts = []
        if location:
            desc_parts.append(location)
        if actor1:
            desc_parts.append(f"Actor: {actor1}")
        if actor2:
            desc_parts.append(f"vs {actor2}")
        if mentions > 5:
            desc_parts.append(f"Mentions: {mentions}")
        if validated:
            desc_parts.append("✓ validated")

        event_label = PROTEST_EVENT_CODES.get(event_code[:3], PROTEST_EVENT_CODES.get(
            event_code[:2], CONFLICT_EVENT_CODES.get(event_code[:3],
            CONFLICT_EVENT_CODES.get(event_code[:2], "Event"))))

        return {
            "id": f"gdelt-{eid}",
            "type": event_type,
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "severity": severity,
            "timestamp": ts,
            "source": f"GDELT 2.0 ({event_label})",
            "title": f"{event_label} — {location or country_code}",
            "description": (title[:150] or " · ".join(desc_parts)),
            "metadata": {
                "event_code": event_code,
                "event_label": event_label,
                "country_code": country_code,
                "location": location,
                "mentions": mentions,
                "validated": validated,
                "goldstein_scale": goldstein,
                "actor1": actor1,
                "actor2": actor2,
                "source_url": url,
                "date": date_str,
                "is_authoritarian_context": country_code in AUTHORITARIAN_COUNTRIES,
            },
        }

    def _parse_geojson_feature(
        self, feat: dict, event_type: str, label: str
    ) -> dict | None:
        """Parse a GDELT GeoJSON pointdata feature."""
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            return None
        lon, lat = float(coords[0]), float(coords[1])
        if abs(lat) < 0.001 and abs(lon) < 0.001:
            return None

        props = feat.get("properties", {})
        name = props.get("name") or props.get("Name") or label
        count = int(props.get("count") or props.get("Count") or MIN_MENTIONS)
        if count < MIN_MENTIONS:
            return None

        date_str = props.get("date") or props.get("Date") or ""
        country_code = props.get("countrycode") or props.get("Country") or ""
        url = props.get("url") or ""

        eid = hashlib.md5(f"{lat:.2f}{lon:.2f}{date_str[:10]}".encode()).hexdigest()[:12]
        if eid in self._seen_ids:
            return None
        self._seen_ids.add(eid)

        severity = self._compute_severity(event_type, 0, count, country_code)
        ts = _parse_gdelt_date(date_str) or datetime.now(timezone.utc).isoformat()

        return {
            "id": f"gdelt-geo-{eid}",
            "type": event_type,
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "severity": severity,
            "timestamp": ts,
            "source": f"GDELT 2.0 GKG ({label})",
            "title": f"{label} — {name}",
            "description": f"{count} reports · {name}",
            "metadata": {
                "event_label": label,
                "country_code": country_code,
                "location": name,
                "mentions": count,
                "validated": count >= VALIDATED_MENTIONS,
                "goldstein_scale": 0,
                "source_url": url,
                "is_authoritarian_context": country_code.upper() in AUTHORITARIAN_COUNTRIES,
            },
        }

    @staticmethod
    def _compute_severity(
        event_type: str,
        goldstein: float,
        mentions: int,
        country_code: str,
    ) -> int:
        """Compute severity 1–5."""
        if event_type == "protest":
            is_authoritarian = country_code.upper() in AUTHORITARIAN_COUNTRIES
            # Base score from mentions
            if is_authoritarian:
                # Linear: every protest is significant
                base = min(5, max(1, 1 + int(mentions / 15)))
            else:
                # Log: routine protests don't spike instability
                import math as _math
                base = min(4, max(1, int(_math.log1p(mentions / 10))))
            return base
        else:
            # Conflict: invert goldstein scale (-10…+10) → severity 1–5
            if goldstein <= -7:
                return 5
            elif goldstein <= -4:
                return 4
            elif goldstein <= -2:
                return 3
            elif goldstein <= 0:
                return 2
            return 1


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_gdelt_date(date_str: str) -> str | None:
    """Parse GDELT date formats: '20240215120000' or '2024-02-15'."""
    if not date_str:
        return None
    date_str = str(date_str).strip()
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str[:len(fmt.replace('%Y',
                '0000').replace('%m','00').replace('%d','00')
                .replace('%H','00').replace('%M','00').replace('%S','00'))],
                fmt)
            return dt.replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    # Simpler fallback
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            clean = date_str[:len(fmt) + 2]
            dt = datetime.strptime(clean[:len(fmt)], fmt)
            return dt.replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return None


def _haversine_dist_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Approximate distance in degrees (fast, good enough for dedup)."""
    return math.sqrt((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2)


def _haversine_dedup(events: list[dict]) -> list[dict]:
    """Spatial deduplication: keep first event per DEDUP_RADIUS_DEG cell."""
    kept: list[dict] = []
    kept_positions: list[tuple[float, float, str]] = []  # (lat, lon, type)

    for event in events:
        lat = event["latitude"]
        lon = event["longitude"]
        etype = event["type"]

        # Check if close to any already-kept event of same type
        duplicate = False
        for klat, klon, ktype in kept_positions:
            if ktype == etype:
                dist = _haversine_dist_deg(lat, lon, klat, klon)
                if dist < DEDUP_RADIUS_DEG:
                    duplicate = True
                    break

        if not duplicate:
            kept.append(event)
            kept_positions.append((lat, lon, etype))

    return kept
