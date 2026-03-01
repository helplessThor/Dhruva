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

def deduplicate_osint_batch(events: list[dict]) -> list[dict]:
    """Robust local deduplication using spatial-temporal proximity.
    Combines duplicate OSINT events and merges their source URLs."""
    if not events:
        return []
        
    unique_events = []
    
    for incoming in events:
        is_duplicate = False
        in_lat = incoming.get("latitude", 0.0)
        in_lon = incoming.get("longitude", 0.0)
        
        try:
            in_time = datetime.fromisoformat(incoming.get("timestamp", "").replace("Z", "+00:00"))
        except Exception:
            in_time = datetime.now(timezone.utc)
            
        for existing in unique_events:
            if existing.get("type") != incoming.get("type"):
                continue
                
            ex_lat = existing.get("latitude", 0.0)
            ex_lon = existing.get("longitude", 0.0)
            
            try:
                ex_time = datetime.fromisoformat(existing.get("timestamp", "").replace("Z", "+00:00"))
            except Exception:
                ex_time = datetime.now(timezone.utc)
                
            # Distance logic (Approximate 1 degree ~ 111 km)
            # If within ~100km (1 degree combined squared) and within 36 hours
            dist_sq = (in_lat - ex_lat)**2 + (in_lon - ex_lon)**2
            time_diff_hours = abs((in_time - ex_time).total_seconds()) / 3600.0
            
            # Condition for duplicate: Same location (< 50km) and time (< 48 hrs)
            if (dist_sq < 0.25 and time_diff_hours < 48):
                is_duplicate = True
                
                # Merge metadata URLs if present
                in_urls = incoming.get("metadata", {}).get("urls", [])
                if in_urls:
                    ex_urls = existing.setdefault("metadata", {}).setdefault("urls", [])
                    existing["metadata"]["urls"] = list(set(ex_urls + in_urls))
                    
                # Merge descriptions if AI vs Fallback
                if "[Pending AI Verification]" in existing.get("title", "") and "[AI Verified]" in incoming.get("title", ""):
                    # Upgrade the existing event to the incoming one since incoming has AI
                    existing["title"] = incoming["title"]
                    existing["description"] = incoming["description"]
                    existing["severity"] = incoming["severity"]
                    existing["metadata"]["groq_verification"] = incoming.get("metadata", {}).get("groq_verification", "")
                
                break
                
        if not is_duplicate:
            unique_events.append(incoming)
            
    return unique_events
