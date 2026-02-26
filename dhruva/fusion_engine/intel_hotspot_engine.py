"""Dhruva — Intelligence Hotspot Engine.

Spatial clustering of REAL events from multiple layers to identify
areas of converging activity. Uses grid-cell aggregation only on
actual incoming data — no synthetic scoring.

Hotspot determination:
  - Divides the globe into 1° × 1° grid cells
  - Counts real events per cell from: military, ucdp, acled, conflict,
    earthquake, fire, protest, gdelt_conflict, military_marine
  - Cells with events from ≥2 different source types become hotspots
  - Severity reflects the number of contributing sources and event count

Convergence alerts:
  - When 3+ distinct event types converge in a 1°×1° cell within 24h
  - Score = n_types × 25 + min(n_events × 2, 50)  (max 100)
  - Broadcast as 'convergence' layer
"""

import logging
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger("dhruva.fusion")

# Which event types contribute to intelligence hotspots
HOTSPOT_SOURCE_TYPES = {
    "military", "ucdp", "acled", "conflict", "earthquake", "fire",
    "protest", "gdelt_conflict", "military_marine",
}

# Grid resolution in degrees (1° ≈ 111 km at equator)
GRID_RESOLUTION = 1.0

# Minimum number of distinct source types in a cell to qualify as hotspot
MIN_SOURCE_TYPES = 2

# Minimum total events in a cell to qualify
MIN_EVENTS = 3

# Minimum distinct source types to emit a convergence alert (higher bar)
MIN_CONVERGENCE_TYPES = 3


def compute_hotspots(event_store: dict[str, list[dict]]) -> list[dict]:
    """Compute intelligence hotspots from real event data.

    Args:
        event_store: The full event store dict, keyed by event type.

    Returns:
        List of intel_hotspot events with real source attribution.
    """
    grid: dict[tuple[int, int], dict] = defaultdict(lambda: {
        "source_types": set(),
        "events": [],
        "total_severity": 0,
        "lat_sum": 0.0,
        "lon_sum": 0.0,
        "count": 0,
    })

    for etype, events in event_store.items():
        if etype not in HOTSPOT_SOURCE_TYPES:
            continue

        for event in events:
            lat = event.get("latitude")
            lon = event.get("longitude")
            if lat is None or lon is None:
                continue

            grid_lat = int(lat // GRID_RESOLUTION)
            grid_lon = int(lon // GRID_RESOLUTION)
            cell = grid[(grid_lat, grid_lon)]

            cell["source_types"].add(etype)
            cell["events"].append({
                "id": event.get("id", ""),
                "type": etype,
                "title": event.get("title", ""),
                "source": event.get("source", ""),
                "severity": event.get("severity", 1),
            })
            cell["total_severity"] += event.get("severity", 1)
            cell["lat_sum"] += lat
            cell["lon_sum"] += lon
            cell["count"] += 1

    hotspots = []
    now = datetime.now(timezone.utc).isoformat()

    for (grid_lat, grid_lon), cell in grid.items():
        n_types = len(cell["source_types"])
        n_events = cell["count"]

        if n_types < MIN_SOURCE_TYPES or n_events < MIN_EVENTS:
            continue

        center_lat = cell["lat_sum"] / n_events
        center_lon = cell["lon_sum"] / n_events

        if n_types >= 4:
            severity = 5
        elif n_types >= 3:
            severity = 4
        elif n_events >= 10:
            severity = 4
        elif n_events >= 5:
            severity = 3
        else:
            severity = 2

        source_list = sorted(cell["source_types"])
        contributing_events = cell["events"][:10]

        title = f"Intel Hotspot — {n_types} converging source types"

        type_counts = defaultdict(int)
        for ev in cell["events"]:
            type_counts[ev["type"]] += 1
        desc_parts = [f"{t}: {c}" for t, c in sorted(type_counts.items(), key=lambda x: -x[1])]

        hotspots.append({
            "id": f"hotspot-{grid_lat}-{grid_lon}",
            "type": "intel_hotspot",
            "latitude": round(center_lat, 4),
            "longitude": round(center_lon, 4),
            "severity": severity,
            "timestamp": now,
            "source": f"Dhruva Fusion ({', '.join(source_list)})",
            "title": title,
            "description": f"{n_events} events from {n_types} sources: " + ", ".join(desc_parts),
            "metadata": {
                "source_types": source_list,
                "source_type_count": n_types,
                "total_events": n_events,
                "type_breakdown": dict(type_counts),
                "contributing_events": contributing_events,
                "grid_lat": grid_lat,
                "grid_lon": grid_lon,
            },
        })

    hotspots.sort(key=lambda h: h["severity"], reverse=True)
    logger.info("[intel_hotspot] Computed %d hotspots from real data", len(hotspots))
    return hotspots


def compute_convergence_alerts(event_store: dict[str, list[dict]]) -> list[dict]:
    """Detect geographic convergence of 3+ distinct event types in 1°×1° cells.

    Score formula:
        score = n_types * 25 + min(n_events * 2, 50)   (max 100)

    Returns:
        List of convergence events sorted by score descending.
    """
    CONVERGENCE_SOURCE_TYPES = HOTSPOT_SOURCE_TYPES | {"cyber", "outage"}

    grid: dict[tuple[int, int], dict] = defaultdict(lambda: {
        "source_types": set(),
        "events": [],
        "lat_sum": 0.0,
        "lon_sum": 0.0,
        "count": 0,
        "max_severity": 1,
        "country": "",
    })

    for etype, events in event_store.items():
        if etype not in CONVERGENCE_SOURCE_TYPES:
            continue

        for event in events:
            lat = event.get("latitude")
            lon = event.get("longitude")
            if lat is None or lon is None:
                continue

            grid_lat = int(lat // GRID_RESOLUTION)
            grid_lon = int(lon // GRID_RESOLUTION)
            cell = grid[(grid_lat, grid_lon)]

            cell["source_types"].add(etype)
            cell["events"].append({"type": etype, "title": event.get("title", "")})
            cell["lat_sum"] += lat
            cell["lon_sum"] += lon
            cell["count"] += 1
            cell["max_severity"] = max(cell["max_severity"], event.get("severity", 1))

            meta = event.get("metadata", {})
            if not cell["country"]:
                cell["country"] = (
                    meta.get("country_code")
                    or meta.get("country")
                    or meta.get("region")
                    or ""
                )

    alerts = []
    now = datetime.now(timezone.utc).isoformat()

    for (grid_lat, grid_lon), cell in grid.items():
        n_types = len(cell["source_types"])
        n_events = cell["count"]

        if n_types < MIN_CONVERGENCE_TYPES:
            continue

        score = min(100, n_types * 25 + min(n_events * 2, 50))

        if score >= 90:
            severity = 5
        elif score >= 70:
            severity = 4
        elif score >= 50:
            severity = 3
        elif score >= 30:
            severity = 2
        else:
            severity = 1

        center_lat = cell["lat_sum"] / n_events
        center_lon = cell["lon_sum"] / n_events

        source_list = sorted(cell["source_types"])
        country_label = cell["country"] or f"{center_lat:.1f}°, {center_lon:.1f}°"

        type_counts: dict[str, int] = defaultdict(int)
        for ev in cell["events"]:
            type_counts[ev["type"]] += 1
        breakdown = ", ".join(
            f"{t}:{c}" for t, c in sorted(type_counts.items(), key=lambda x: -x[1])
        )

        alerts.append({
            "id": f"convergence-{grid_lat}-{grid_lon}",
            "type": "convergence",
            "latitude": round(center_lat, 4),
            "longitude": round(center_lon, 4),
            "severity": severity,
            "timestamp": now,
            "source": "Dhruva Convergence Engine",
            "title": f"Multi-Domain Convergence — {n_types} signal types",
            "description": (
                f"{n_events} events ({breakdown}) converging near {country_label}. "
                f"Convergence score: {score}/100"
            ),
            "metadata": {
                "source_types": source_list,
                "n_types": n_types,
                "n_events": n_events,
                "score": score,
                "type_breakdown": dict(type_counts),
                "grid_lat": grid_lat,
                "grid_lon": grid_lon,
                "region_label": country_label,
            },
        })

    alerts.sort(key=lambda a: a["metadata"]["score"], reverse=True)
    logger.info(
        "[convergence] Found %d convergence alerts (%d+ signal types)",
        len(alerts), MIN_CONVERGENCE_TYPES,
    )
    return alerts
