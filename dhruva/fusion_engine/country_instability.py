"""Dhruva — Country Instability Index (CII).

Computes a 0-100 instability score for monitored countries by
aggregating real event signals from all active data layers.

Signal Weights:
  - Active conflict nearby (acled + ucdp):                          30%
  - Military aircraft + vessel activity:                    20%
  - Fire / disaster events:                                 15%
  - Protest events:                                         20%
  - Cyber events:                                           15%

Country-floor pins ensure historically volatile states have a
minimum baseline instability even during quiet periods:
  Ukraine >= 55, Syria >= 50, Yemen >= 45, Gaza >= 60, Sudan >= 45

Endpoint: GET /api/cii
"""

import logging
import math
from datetime import datetime, timezone

logger = logging.getLogger("dhruva.fusion")

from .global_countries import GLOBAL_COUNTRIES

# Monitored countries with their ISO2 codes and center coordinates
MONITORED_COUNTRIES = GLOBAL_COUNTRIES

# Minimum instability floors (historically volatile states) - no longer applied per previous edits
COUNTRY_FLOORS = {}

# Radius within which events count toward a country's score (degrees ~111km)
EVENT_RADIUS_DEG = 5.0

# Weight configuration (must sum to 1.0)
WEIGHTS = {
    "conflict":  0.30,   # conflict + ucdp
    "military":  0.25,   # military + military_aircraft + military_marine
    "protest":   0.20,   # protest
    "cyber":     0.10,   # cyber
    "outage":    0.10,   # outage
    "notam":     0.05,   # notam
}

# Event types contributing to each signal bucket
SIGNAL_BUCKETS = {
    "conflict":  {"conflict", "ucdp"},
    "military":  {"military", "military_aircraft", "military_marine"},
    "protest":   {"protest"},
    "cyber":     {"cyber"},
    "outage":    {"outage"},
    "notam":     {"notam"},
}


def _distance_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Euclidean approximation of distance in degrees (fast)."""
    return math.sqrt((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2)


def _signal_score(events_in_radius: list[dict], bucket: str, max_cap: int = 30) -> float:
    """Compute a 0–100 sub-score from nearby events for a given signal bucket.

    Uses log scaling so that 1 event = low score, many events = high score,
    saturating around max_cap events.
    """
    n = min(len(events_in_radius), max_cap)
    if n == 0:
        return 0.0
    # log1p(n) / log1p(max_cap) → 0..1 → * 100
    raw = math.log1p(n) / math.log1p(max_cap) * 100
    # Boost by average severity (severity 1-5 → factor 0.8–1.4)
    avg_sev = sum(e.get("severity", 1) for e in events_in_radius) / n
    sev_factor = 0.6 + (avg_sev / 5) * 0.8
    return min(100.0, raw * sev_factor)


def compute_cii(event_store: dict[str, list[dict]]) -> list[dict]:
    """Compute Country Instability Index for all monitored countries.

    Args:
        event_store: Full event store keyed by event type.

    Returns:
        List of CII records sorted by score descending.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Flatten all events by bucket (pre-group for efficiency)
    bucket_events: dict[str, list[dict]] = {b: [] for b in SIGNAL_BUCKETS}
    for etype, events in event_store.items():
        for bucket, type_set in SIGNAL_BUCKETS.items():
            if etype in type_set:
                bucket_events[bucket].extend(events)

    results = []
    for country, info in MONITORED_COUNTRIES.items():
        clat, clon = info["lat"], info["lon"]
        iso2 = info["iso2"]

        # For each signal bucket, find nearby events and score them
        bucket_scores: dict[str, float] = {}
        for bucket, events in bucket_events.items():
            nearby = [
                e for e in events
                if e.get("latitude") is not None and e.get("longitude") is not None
                and _distance_deg(clat, clon, e["latitude"], e["longitude"]) <= EVENT_RADIUS_DEG
            ]
            bucket_scores[bucket] = _signal_score(nearby, bucket)

        # Weighted composite score
        raw_score = sum(
            bucket_scores[bucket] * weight
            for bucket, weight in WEIGHTS.items()
        )
        raw_score = round(raw_score, 1)

        # Strictly based on real data now (no floors)
        score = min(raw_score, 100.0)

        # Determine label
        if score >= 75:
            label = "CRITICAL"
            color = "#ff2244"
        elif score >= 50:
            label = "HIGH"
            color = "#ff8800"
        elif score >= 30:
            label = "ELEVATED"
            color = "#ffcc00"
        elif score >= 15:
            label = "MODERATE"
            color = "#88cc00"
        else:
            label = "LOW"
            color = "#00cc88"

        results.append({
            "country": country,
            "iso2": iso2,
            "lat": clat,
            "lon": clon,
            "score": score,
            "raw_score": raw_score,
            "floor_applied": score > raw_score,
            "label": label,
            "color": color,
            "signals": {b: round(v, 1) for b, v in bucket_scores.items()},
            "timestamp": now,
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    logger.info("[cii] Computed instability index for %d countries (top: %s = %.0f)",
                len(results), results[0]["country"] if results else "?",
                results[0]["score"] if results else 0)
    return results
