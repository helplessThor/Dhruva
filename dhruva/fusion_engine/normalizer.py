"""Dhruva — Event Normalizer."""

from datetime import datetime, timezone
from backend.models import OsintEvent, EventType


def normalize_event(raw: dict) -> OsintEvent:
    """Validate and normalize a raw collector event dict into an OsintEvent."""
    return OsintEvent(
        id=raw.get("id", ""),
        type=EventType(raw["type"]),
        latitude=float(raw["latitude"]),
        longitude=float(raw["longitude"]),
        severity=max(1, min(5, int(raw.get("severity", 1)))),
        timestamp=raw.get("timestamp", datetime.now(timezone.utc).isoformat()),
        source=raw.get("source", "unknown"),
        title=raw.get("title", ""),
        description=raw.get("description", ""),
        metadata=raw.get("metadata", {}),
    )


def normalize_batch(raw_events: list[dict]) -> list[dict]:
    """Normalize a batch of events, skipping invalid ones."""
    results = []
    for raw in raw_events:
        try:
            event = normalize_event(raw)
            results.append(event.model_dump(mode="json"))
        except Exception as e:
            import logging
            logging.getLogger("dhruva.normalizer").error(f"Failed to normalize event: {e}, raw: {raw.get('title')}")
            continue
    return results
