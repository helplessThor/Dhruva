"""Dhruva — DEFCON-style Global Risk Calculator."""

from collections import Counter
from datetime import datetime, timezone


# Severity weights by event type
TYPE_WEIGHTS = {
    "earthquake": 1.5,
    "fire": 1.0,
    "conflict": 2.0,
    "aircraft": 0.2,
    "marine": 0.2,
    "cyber": 1.5,
    "outage": 1.2,
    "economic": 0.8,
    "military": 2.5,
    "ucdp": 2.0,
    "acled": 2.0,
    "intel_hotspot": 0.5,
}

RISK_LEVELS = {
    1: {"label": "NOMINAL", "color": "#00ff88"},
    2: {"label": "GUARDED", "color": "#44ccff"},
    3: {"label": "ELEVATED", "color": "#ffcc00"},
    4: {"label": "HIGH", "color": "#ff6600"},
    5: {"label": "CRITICAL", "color": "#ff0033"},
}


def calculate_risk(events: list[dict]) -> dict:
    """Calculate a DEFCON-style global risk level from current events.

    Risk is derived from:
    - Total weighted severity across all event types
    - Number of high-severity events (>=4)
    - Diversity of threat types
    """
    if not events:
        return {
            "level": 1,
            **RISK_LEVELS[1],
            "event_counts": {},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    type_counts = Counter()
    weighted_score = 0.0
    high_severity_count = 0

    for event in events:
        etype = event.get("type", "unknown")
        severity = event.get("severity", 1)

        type_counts[etype] += 1
        weight = TYPE_WEIGHTS.get(etype, 1.0)
        weighted_score += severity * weight

        if severity >= 4:
            high_severity_count += 1

    # Normalize score
    avg_weighted = weighted_score / len(events) if events else 0

    # Factor in diversity of threat types (more types = higher risk)
    diversity_bonus = min(len(type_counts) * 0.15, 1.0)

    # Factor in count of critical events
    critical_bonus = min(high_severity_count * 0.1, 1.5)

    composite = avg_weighted + diversity_bonus + critical_bonus

    # Map composite score to risk level
    if composite >= 6.0:
        level = 5
    elif composite >= 4.5:
        level = 4
    elif composite >= 3.0:
        level = 3
    elif composite >= 1.5:
        level = 2
    else:
        level = 1

    return {
        "level": level,
        **RISK_LEVELS[level],
        "event_counts": dict(type_counts),
        "score": round(composite, 2),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
