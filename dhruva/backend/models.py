"""Dhruva — Unified Event Schema & Data Models."""

from pydantic import BaseModel, Field
from typing import Optional, Any
from enum import Enum
from datetime import datetime
import uuid


class EventType(str, Enum):
    """Types of OSINT events."""
    EARTHQUAKE = "earthquake"
    FIRE = "fire"
    CONFLICT = "conflict"       # Legacy — kept for migration
    AIRCRAFT = "aircraft"
    MARINE = "marine"
    CYBER = "cyber"
    OUTAGE = "outage"
    ECONOMIC = "economic"
    MILITARY = "military"
    MILITARY_AIRCRAFT = "military_aircraft"
    UCDP = "ucdp"
    ACLED = "acled"
    INTEL_HOTSPOT = "intel_hotspot"


class Severity(int, Enum):
    """Event severity levels."""
    LOW = 1
    MODERATE = 2
    HIGH = 3
    CRITICAL = 4
    CATASTROPHIC = 5


class OsintEvent(BaseModel):
    """Unified OSINT event schema — all collectors normalize to this."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: EventType
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    severity: int = Field(ge=1, le=5)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: str
    title: str = ""
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiskLevel(BaseModel):
    """Global DEFCON-style risk assessment."""
    level: int = Field(ge=1, le=5, description="1=Nominal, 5=Critical")
    label: str
    color: str
    event_counts: dict[str, int] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class LayerState(BaseModel):
    """Tracks which layers are active."""
    earthquake: bool = True
    fire: bool = True
    conflict: bool = True
    aircraft: bool = True
    marine: bool = True
    cyber: bool = True
    outage: bool = True
    economic: bool = True
    military: bool = True
    military_aircraft: bool = True
    ucdp: bool = True
    acled: bool = True
    intel_hotspot: bool = True



class WebSocketMessage(BaseModel):
    """WebSocket message envelope."""
    action: str  # "event_batch", "risk_update", "layer_data"
    data: Any
    timestamp: datetime = Field(default_factory=datetime.utcnow)
