"""Dhruva — Internet Outage Collector (IODA alerts API)."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from datetime import datetime, timezone

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

IODA_ALERTS_URL = "https://api.ioda.inetintel.cc.gatech.edu/v2/outages/alerts"
WINDOW_SECONDS = 30 * 60  # fixed 30-minute query windows

# Optional IODA filters (recommended by IODA docs to limit result volume)
IODA_ENTITY_TYPE = os.environ.get("DHRUVA_IODA_ENTITY_TYPE", "").strip()  # e.g. country, asn
IODA_ENTITY_CODE = os.environ.get("DHRUVA_IODA_ENTITY_CODE", "").strip()  # e.g. US, 3307

# Rough centroids for common entities returned by outage feeds.
# Used only when alert payload does not contain coordinates.
COUNTRY_CENTROIDS: dict[str, tuple[float, float]] = {
    "US": (39.8, -98.6),
    "IN": (20.6, 78.9),
    "RU": (61.5, 105.3),
    "CN": (35.8, 104.1),
    "IR": (32.4, 53.7),
    "PK": (30.4, 69.4),
    "UA": (48.4, 31.2),
    "GB": (55.4, -3.4),
    "DE": (51.2, 10.4),
    "FR": (46.2, 2.2),
    "BR": (-14.2, -51.9),
    "ID": (-2.2, 117.3),
    "MM": (21.9, 95.9),
    "ET": (9.1, 40.5),
    "CU": (21.5, -77.8),
    "VE": (6.4, -66.6),
    "NG": (9.1, 8.7),
    "AU": (-25.3, 133.8),
    "HK": (22.3, 114.2),
    "TW": (23.7, 121.0),
    "ZA": (-30.6, 22.9),
    "PS": (31.9, 35.2),
    "IL": (31.0, 35.0),
    "SG": (1.35, 103.82),
    "JP": (36.2, 138.3),
    "TR": (39.0, 35.2),
    "VN": (14.1, 108.3),
    "NL": (52.1, 5.3),
    "HU": (47.2, 19.5),
    "BG": (42.7, 25.5),
    "RS": (44.2, 20.8),
    "IT": (41.9, 12.6),
    "PL": (52.1, 19.1),
    "KR": (36.5, 127.9),
    "PH": (12.9, 122.8),
    "AZ": (40.1, 47.6),
    "CZ": (49.8, 15.5),
    "NC": (-21.3, 165.6),
}

SEVERITY_BY_LEVEL = {
    "critical": 5,
    "warning": 4,
    "minor": 3,
    "normal": 1,
}


class OutageCollector(BaseCollector):
    """Collect internet outage alerts from IODA using discrete 30-minute windows."""

    def __init__(self, interval: int = WINDOW_SECONDS):
        super().__init__(name="outage", interval=interval)

    async def collect(self) -> list[dict]:
        # Query the *previous closed* 30-minute window to avoid partial data.
        now_ts = int(time.time())
        until_ts = (now_ts // WINDOW_SECONDS) * WINDOW_SECONDS
        from_ts = until_ts - WINDOW_SECONDS

        params = {"from": from_ts, "until": until_ts}
        if IODA_ENTITY_TYPE:
            params["entityType"] = IODA_ENTITY_TYPE
        if IODA_ENTITY_CODE:
            params["entityCode"] = IODA_ENTITY_CODE

        try:
            data = await self.fetch_json(IODA_ALERTS_URL, params=params)
        except Exception as e:
            logger.warning("[outage] IODA alerts API error: %s", e)
            return []

        alerts = self._extract_alerts(data)
        if not alerts:
            logger.info("[outage] IODA returned 0 alerts (%d-%d)", from_ts, until_ts)
            return []

        events: list[dict] = []
        for alert in alerts:
            event = self._alert_to_event(alert, from_ts=from_ts, until_ts=until_ts)
            if event:
                events.append(event)

        logger.info("[outage] IODA returned %d alerts (%d-%d)", len(events), from_ts, until_ts)
        return events

    def _extract_alerts(self, payload: object) -> list[dict]:
        """Normalize possible IODA response envelopes into a list of alert dicts."""
        if isinstance(payload, list):
            return [a for a in payload if isinstance(a, dict)]

        if not isinstance(payload, dict):
            return []

        for key in ("alerts", "results", "data", "items", "outages"):
            value = payload.get(key)
            if isinstance(value, list):
                return [a for a in value if isinstance(a, dict)]
            if isinstance(value, dict):
                nested = self._extract_alerts(value)
                if nested:
                    return nested

        return []

    def _alert_to_event(self, alert: dict, *, from_ts: int, until_ts: int) -> dict | None:
        lat = self._to_float(alert.get("latitude") or alert.get("lat"))
        lon = self._to_float(alert.get("longitude") or alert.get("lon"))

        entity_obj = alert.get("entity") if isinstance(alert.get("entity"), dict) else {}

        entity = (
            str(
                alert.get("entityName")
                or alert.get("entity_name")
                or entity_obj.get("name")
                or alert.get("entityCode")
                or alert.get("entity_code")
                or entity_obj.get("code")
                or alert.get("country")
                or alert.get("name")
                or "Unknown"
            )
            .strip()
        )
        entity_code = str(
            alert.get("entityCode")
            or alert.get("entity_code")
            or entity_obj.get("code")
            or ""
        ).strip()
        entity_type = str(
            alert.get("entityType")
            or alert.get("entity_type")
            or entity_obj.get("type")
            or ""
        ).strip()

        if lat is None or lon is None:
            centroid = self._centroid_for_entity(entity, entity_code=entity_code)
            if centroid:
                lat, lon = centroid
            else:
                return None

        impact = self._to_float(
            alert.get("impact")
            or alert.get("value")
            or alert.get("score")
            or alert.get("severity")
            or 0
        )
        level = str(alert.get("level") or "").strip().lower()
        severity = self._severity_from_impact(impact, level=level)

        started_ts = self._to_int(
            alert.get("start")
            or alert.get("startTime")
            or alert.get("started_at")
            or alert.get("timestamp")
            or alert.get("time")
            or until_ts
        )

        duration_min = max(0, (until_ts - started_ts) // 60)

        alert_id = str(
            alert.get("id")
            or alert.get("alert_id")
            or alert.get("uuid")
            or hashlib.md5(f"{entity}-{started_ts}-{lat}-{lon}".encode()).hexdigest()[:12]
        )

        return {
            "id": f"outage-{alert_id}",
            "type": "outage",
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "severity": severity,
            "timestamp": datetime.fromtimestamp(started_ts, timezone.utc).isoformat(),
            "source": "IODA Alerts API",
            "title": f"Internet Outage Alert — {entity}",
            "description": (
                f"IODA detected outage conditions for {entity} "
                f"(level={level or 'unknown'}, impact={impact:.2f}, active~{duration_min} min)"
            ),
            "metadata": {
                "entity": entity,
                "entity_code": entity_code,
                "entity_type": entity_type,
                "datasource": alert.get("datasource", ""),
                "level": level,
                "condition": alert.get("condition", ""),
                "value": alert.get("value"),
                "history_value": alert.get("historyValue"),
                "impact": impact,
                "window_from_unix": from_ts,
                "window_until_unix": until_ts,
                "alert_start_unix": started_ts,
                "raw": alert,
            },
        }

    @staticmethod
    def _to_float(value: object) -> float | None:
        try:
            if value is None or value == "":
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: object) -> int:
        try:
            if value is None or value == "":
                return int(time.time())
            return int(float(value))
        except (TypeError, ValueError):
            return int(time.time())

    @staticmethod
    def _severity_from_impact(impact: float | None, *, level: str = "") -> int:
        level = (level or "").lower().strip()
        if level in SEVERITY_BY_LEVEL:
            return SEVERITY_BY_LEVEL[level]
        if impact is None:
            return 2
        if impact >= 0.9:
            return 5
        if impact >= 0.7:
            return 4
        if impact >= 0.4:
            return 3
        return 2

    @staticmethod
    def _centroid_for_entity(entity: str, *, entity_code: str = "") -> tuple[float, float] | None:
        key = entity.strip().upper()

        # Parse explicit country code hints from entity code e.g. 12400-IL, 28287-BR.
        if entity_code:
            code_key = entity_code.strip().upper()
            if "-" in code_key:
                suffix = code_key.split("-")[-1]
                if len(suffix) == 2 and suffix in COUNTRY_CENTROIDS:
                    return COUNTRY_CENTROIDS[suffix]

        # Parse entity names like "PARTNER-AS -- Israel".
        if "--" in key:
            tail = key.split("--")[-1].strip()
            country_name_map = {
                "UNITED STATES": "US",
                "RUSSIAN FEDERATION": "RU",
                "IRAN (ISLAMIC REPUBLIC OF)": "IR",
                "SOUTH AFRICA": "ZA",
                "HONG KONG": "HK",
                "TAIWAN PROVINCE OF CHINA": "TW",
                "PALESTINIAN TERRITORIES": "PS",
            }
            # Handle clean 2-letter names in tail first.
            if len(tail) == 2 and tail in COUNTRY_CENTROIDS:
                return COUNTRY_CENTROIDS[tail]
            if tail in country_name_map and country_name_map[tail] in COUNTRY_CENTROIDS:
                return COUNTRY_CENTROIDS[country_name_map[tail]]

            # If tail ends with 2-letter token in parenthesis or free text.
            m = re.search(r"\b([A-Z]{2})\b$", tail)
            if m and m.group(1) in COUNTRY_CENTROIDS:
                return COUNTRY_CENTROIDS[m.group(1)]

        if key in COUNTRY_CENTROIDS:
            return COUNTRY_CENTROIDS[key]
        # Handle values like "country:US" or "US-AS1234"
        for splitter in (":", "-", "_"):
            if splitter in key:
                maybe_cc = key.split(splitter)[-1]
                if maybe_cc in COUNTRY_CENTROIDS:
                    return COUNTRY_CENTROIDS[maybe_cc]
        if len(key) == 2 and key in COUNTRY_CENTROIDS:
            return COUNTRY_CENTROIDS[key]
        return None
