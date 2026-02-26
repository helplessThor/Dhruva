"""
Dhruva — Main FastAPI Application
OSINT Global Situational Awareness Dashboard Backend
"""

import asyncio
import logging
import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.redis_manager import RedisStreamManager
from backend.websocket_manager import ConnectionManager
from datetime import datetime, timezone

from fusion_engine.normalizer import normalize_batch
from fusion_engine.risk_calculator import calculate_risk
from fusion_engine.intel_hotspot_engine import compute_hotspots, compute_convergence_alerts
from fusion_engine.country_instability import compute_cii
from backend.market_data import market_data_loop, get_market_data

from collectors.earthquake_collector import EarthquakeCollector
from collectors.fire_collector import FireCollector
from collectors.conflict_collector import ConflictCollector
from collectors.aircraft_collector import AircraftCollector
from collectors.marine_collector import MarineCollector
from collectors.cyber_collector import CyberCollector
from collectors.outage_collector import OutageCollector
from collectors.economic_collector import EconomicCollector
from collectors.military_activity_collector import MilitaryActivityCollector, infer_military_aircraft
from collectors.ucdp_collector import UCDPCollector
from collectors.acled_collector import ACLEDCollector
from collectors.naval_collector import NavalCollector

# ─── Logging ───────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-20s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dhruva.main")

# ─── Globals ───────────────────────────────────────
stream_manager = RedisStreamManager(
    redis_url=settings.redis_url,
    stream_key=settings.redis_stream_key,
    use_redis=settings.use_redis,
)
ws_manager = ConnectionManager()

# Event store (in-memory buffer for REST API)
event_store: dict[str, list[dict]] = {
    "earthquake": [],
    "fire": [],
    "conflict": [],
    "aircraft": [],
    "marine": [],
    "military_marine": [],
    "cyber": [],
    "outage": [],
    "economic": [],
    "military": [],
    "military_aircraft": [],
    "ucdp": [],
    "acled": [],
    "naval": [],
    "protest": [],
    "gdelt_conflict": [],
    "intel_hotspot": [],
    "convergence": [],
    "cii": [],
}
current_risk: dict = {"level": 1, "label": "NOMINAL", "color": "#00ff88"}

# Data freshness tracker — records last successful fetch per layer
data_freshness: dict[str, str] = {}

# Cached CII (refreshed periodically alongside hotspots)
_cii_cache: list[dict] = []

# Collectors
collectors = [
    EarthquakeCollector(interval=settings.earthquake_interval),
    FireCollector(interval=settings.fire_interval),
    ConflictCollector(interval=settings.conflict_interval),
    AircraftCollector(interval=settings.aircraft_interval),
    MarineCollector(interval=settings.marine_interval),
    CyberCollector(interval=settings.cyber_interval),
    OutageCollector(interval=settings.outage_interval),
    EconomicCollector(interval=settings.economic_interval),
    MilitaryActivityCollector(interval=settings.military_interval),
    UCDPCollector(interval=settings.ucdp_interval),
    ACLEDCollector(interval=settings.acled_interval),
    NavalCollector(interval=settings.naval_interval),
]

# Layer types that trigger hotspot / convergence recompute
HOTSPOT_TRIGGER_LAYERS = {
    "military", "ucdp", "acled", "conflict",
    "earthquake", "fire", "protest", "gdelt_conflict",
    "military_marine", "cyber", "outage",
}


def _recompute_fusion():
    """Recompute hotspots, convergence alerts, and CII from current event_store."""
    global _cii_cache

    # ── Intel Hotspots ──────────────────────────────
    try:
        hotspots = compute_hotspots(event_store)
        hotspot_normalized = normalize_batch(hotspots)
        event_store["intel_hotspot"] = hotspot_normalized
        if hotspots:
            data_freshness["intel_hotspot"] = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        logger.debug("Hotspot computation error: %s", e)

    # ── Convergence Alerts ──────────────────────────
    try:
        convergence = compute_convergence_alerts(event_store)
        conv_normalized = normalize_batch(convergence)
        event_store["convergence"] = conv_normalized
        if convergence:
            data_freshness["convergence"] = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        logger.debug("Convergence computation error: %s", e)

    # ── Country Instability Index ───────────────────
    try:
        cii = compute_cii(event_store)
        _cii_cache = cii
    except Exception as e:
        logger.debug("CII computation error: %s", e)


async def run_collector(collector):
    """Run a single collector and feed events into the system."""
    global current_risk
    async for events in collector.start():
        if not events:
            continue

        etype = collector.name

        # ── GDELT: split into sub-layers ───────────────────────────
        if etype == "gdelt":
            protests = [e for e in events if e.get("type") == "protest"]
            gdelt_conflicts = [e for e in events if e.get("type") == "gdelt_conflict"]

            if protests:
                norm_protests = normalize_batch(protests)
                event_store["protest"] = norm_protests
                data_freshness["protest"] = datetime.now(timezone.utc).isoformat()
                await ws_manager.broadcast({
                    "action": "event_batch",
                    "layer": "protest",
                    "data": norm_protests,
                    "risk": current_risk,
                })

            if gdelt_conflicts:
                norm_gc = normalize_batch(gdelt_conflicts)
                event_store["gdelt_conflict"] = norm_gc
                data_freshness["gdelt_conflict"] = datetime.now(timezone.utc).isoformat()
                await ws_manager.broadcast({
                    "action": "event_batch",
                    "layer": "gdelt_conflict",
                    "data": norm_gc,
                    "risk": current_risk,
                })

            # Recompute fusion for GDELT data
            _recompute_fusion()
            await ws_manager.broadcast({
                "action": "event_batch",
                "layer": "intel_hotspot",
                "data": event_store.get("intel_hotspot", []),
                "risk": current_risk,
            })
            await ws_manager.broadcast({
                "action": "event_batch",
                "layer": "convergence",
                "data": event_store.get("convergence", []),
                "risk": current_risk,
            })
            continue  # Skip generic processing below for gdelt

        # ── Marine: split military_marine from marine ────────────────
        if etype == "marine":
            normalized_all = normalize_batch(events)
            marine_events = [e for e in normalized_all if e.get("type") == "marine"]
            mil_marine_events = [e for e in normalized_all if e.get("type") == "military_marine"]

            event_store["marine"] = marine_events
            data_freshness["marine"] = datetime.now(timezone.utc).isoformat()

            if mil_marine_events:
                event_store["military_marine"] = mil_marine_events
                data_freshness["military_marine"] = datetime.now(timezone.utc).isoformat()
                await ws_manager.broadcast({
                    "action": "event_batch",
                    "layer": "military_marine",
                    "data": mil_marine_events,
                    "risk": current_risk,
                })

            # Recalculate risk
            all_events = []
            for ev_list in event_store.values():
                if isinstance(ev_list, list):
                    all_events.extend(ev_list)
            current_risk = calculate_risk(all_events)

            await ws_manager.broadcast({
                "action": "event_batch",
                "layer": "marine",
                "data": marine_events,
                "risk": current_risk,
            })
            continue  # Skip generic processing below for marine

        # ── ACLED: merge into main conflict layer ────────────────────
        if etype == "acled":
            normalized_acled = normalize_batch(events)
            
            # Store in both the raw 'acled' layer and the generic 'conflict' layer
            event_store["acled"] = normalized_acled
            data_freshness["acled"] = datetime.now(timezone.utc).isoformat()
            
            # Overwrite the empty conflict layer with the rich ACLED data
            # NOTE: We merge UCDP and Naval into this later if they run
            event_store["conflict"] = normalized_acled
            data_freshness["conflict"] = datetime.now(timezone.utc).isoformat()
            
            # Recalculate risk
            all_events = []
            for ev_list in event_store.values():
                if isinstance(ev_list, list):
                    all_events.extend(ev_list)
            current_risk = calculate_risk(all_events)

            await ws_manager.broadcast({
                "action": "event_batch",
                "layer": "acled",
                "data": normalized_acled,
                "risk": current_risk,
            })
            await ws_manager.broadcast({
                "action": "event_batch",
                "layer": "conflict",
                "data": event_store["conflict"],
                "risk": current_risk,
            })
            
            # Recompute fusion since conflict data just arrived
            _recompute_fusion()
            await ws_manager.broadcast({
                "action": "event_batch",
                "layer": "intel_hotspot",
                "data": event_store.get("intel_hotspot", []),
                "risk": current_risk,
            })
            continue  # Skip generic processing
            
        # ── Naval & UCDP Scrapers: Merge into main conflict layer ────
        if etype in ["ucdp", "naval"]:
            normalized_osint = normalize_batch(events)
            
            event_store[etype] = normalized_osint
            data_freshness[etype] = datetime.now(timezone.utc).isoformat()
            
            # Append to conflict layer
            if "conflict" not in event_store:
                event_store["conflict"] = []
            
            # Remove old OSINT of the same type to prevent infinite growth before appending new
            event_store["conflict"] = [e for e in event_store["conflict"] if e.get("type") != etype]
            event_store["conflict"].extend(normalized_osint)
            data_freshness["conflict"] = datetime.now(timezone.utc).isoformat()
            
            # Recalculate risk
            all_events = []
            for ev_list in event_store.values():
                if isinstance(ev_list, list):
                    all_events.extend(ev_list)
            current_risk = calculate_risk(all_events)
            
            await ws_manager.broadcast({
                "action": "event_batch",
                "layer": etype,
                "data": normalized_osint,
                "risk": current_risk,
            })
            await ws_manager.broadcast({
                "action": "event_batch",
                "layer": "conflict",
                "data": event_store["conflict"],
                "risk": current_risk,
            })
            
            _recompute_fusion()
            await ws_manager.broadcast({
                "action": "event_batch",
                "layer": "intel_hotspot",
                "data": event_store.get("intel_hotspot", []),
                "risk": current_risk,
            })
            continue  # Skip generic processing

        # ── Generic processing ───────────────────────────────────────
        normalized = normalize_batch(events)
        event_store[etype] = normalized
        data_freshness[etype] = datetime.now(timezone.utc).isoformat()

        # Post-processing: infer military aircraft from ADS-B data
        if etype == "aircraft":
            try:
                mil_aircraft = await infer_military_aircraft(normalized)
                if mil_aircraft:
                    mil_normalized = normalize_batch(mil_aircraft)

                    # ── DEDUP: remove military ICAOs from aircraft layer ─────
                    mil_icao_set = {
                        e.get("metadata", {}).get("icao24", "")
                        for e in mil_normalized
                        if e.get("metadata", {}).get("icao24")
                    }
                    event_store["aircraft"] = [
                        e for e in normalized
                        if e.get("metadata", {}).get("icao24", "") not in mil_icao_set
                    ]

                    event_store["military_aircraft"] = mil_normalized
                    data_freshness["military_aircraft"] = datetime.now(timezone.utc).isoformat()
                    await ws_manager.broadcast({
                        "action": "event_batch",
                        "layer": "military_aircraft",
                        "data": mil_normalized,
                        "risk": current_risk,
                    })
            except Exception as e:
                logger.debug("Military aircraft inference error: %s", e)

        # Recompute fusion after qualifying layer updates
        if etype in HOTSPOT_TRIGGER_LAYERS:
            _recompute_fusion()
            await ws_manager.broadcast({
                "action": "event_batch",
                "layer": "intel_hotspot",
                "data": event_store.get("intel_hotspot", []),
                "risk": current_risk,
            })
            await ws_manager.broadcast({
                "action": "event_batch",
                "layer": "convergence",
                "data": event_store.get("convergence", []),
                "risk": current_risk,
            })

        # Publish to stream
        await stream_manager.publish_batch(normalized)

        # Recalculate risk
        all_events = []
        for ev_list in event_store.values():
            if isinstance(ev_list, list):
                all_events.extend(ev_list)
        current_risk = calculate_risk(all_events)

        # Broadcast to WebSocket clients
        await ws_manager.broadcast({
            "action": "event_batch",
            "layer": etype,
            "data": normalized,
            "risk": current_risk,
        })


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: start collectors on startup, stop on shutdown."""
    logger.info("═══════════════════════════════════════════════")
    logger.info("  DHRUVA — OSINT Situational Awareness Engine  ")
    logger.info("  Version %s", settings.app_version)
    logger.info("═══════════════════════════════════════════════")

    await stream_manager.connect()

    # Start all collectors as background tasks
    tasks = []
    for collector in collectors:
        task = asyncio.create_task(run_collector(collector))
        tasks.append(task)
        logger.info("Started collector: %s", collector.name)

    # Start market data fetcher (every 2 minutes)
    market_task = asyncio.create_task(market_data_loop(interval=120))
    tasks.append(market_task)
    logger.info("Started market data fetcher")

    yield

    # Shutdown
    logger.info("Shutting down Dhruva...")
    for collector in collectors:
        await collector.stop()
    for task in tasks:
        task.cancel()
    await stream_manager.close()


# ─── FastAPI App ───────────────────────────────────
app = FastAPI(
    title="Dhruva",
    description="OSINT Global Situational Awareness Dashboard",
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── REST Endpoints ───────────────────────────────
@app.get("/")
async def root():
    return {
        "name": "Dhruva",
        "version": settings.app_version,
        "status": "operational",
        "ws_clients": ws_manager.connection_count,
    }


@app.get("/api/events")
async def get_all_events():
    """Get all current events across all layers."""
    all_events = []
    for layer, events in event_store.items():
        if isinstance(events, list):
            all_events.extend(events)
    return {
        "total": len(all_events),
        "events": all_events,
        "risk": current_risk,
    }


@app.get("/api/events/{layer}")
async def get_layer_events(layer: str):
    """Get events for a specific layer."""
    if layer not in event_store:
        return {"error": f"Unknown layer: {layer}", "available": list(event_store.keys())}
    return {
        "layer": layer,
        "count": len(event_store[layer]),
        "events": event_store[layer],
    }


@app.get("/api/risk")
async def get_risk():
    """Get current global risk assessment."""
    return current_risk


@app.get("/api/layers")
async def get_layers():
    """Get available layers and their event counts."""
    return {
        layer: {"count": len(events), "active": True}
        for layer, events in event_store.items()
        if isinstance(events, list)
    }


@app.get("/api/market-data")
async def get_market():
    """Get current global stock index data."""
    data = get_market_data()
    return {"indexes": data, "count": len(data)}


@app.get("/api/data-freshness")
async def get_data_freshness():
    """Get last-update timestamp per data layer."""
    return {
        "layers": {
            layer: {
                "count": len(events),
                "last_updated": data_freshness.get(layer),
                "active": len(events) > 0,
            }
            for layer, events in event_store.items()
            if isinstance(events, list)
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/cii")
async def get_cii():
    """Get Country Instability Index scores for monitored countries."""
    if not _cii_cache:
        # Compute on demand if not yet cached
        try:
            cii = compute_cii(event_store)
        except Exception:
            cii = []
    else:
        cii = _cii_cache

    return {
        "count": len(cii),
        "countries": cii,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── WebSocket Endpoint ───────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time event streaming."""
    await ws_manager.connect(websocket)

    # Send initial state
    all_events = []
    for events in event_store.values():
        if isinstance(events, list):
            all_events.extend(events)

    await ws_manager.send_to(websocket, {
        "action": "initial_state",
        "data": all_events,
        "risk": current_risk,
        "layers": list(event_store.keys()),
    })

    try:
        while True:
            data = await websocket.receive_text()
            logger.debug("Client message: %s", data)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# ─── Run ───────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
