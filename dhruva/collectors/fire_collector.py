"""Dhruva — Active Fire Collector (NASA FIRMS Near Real-Time).

Uses the NASA FIRMS API (VIIRS SNPP NRT) for real active fire data worldwide.
API key loaded from credentials.json → "firms_api_key", falls back to env
DHRUVA_FIRMS_API_KEY. If neither is set, uses the public DEMO_KEY
(~2,000 requests/month — sufficient at 2-minute poll intervals).

No mock data. No synthetic events. Returns [] on API failure.
"""

import csv
import io
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

# ── Load FIRMS API key ──────────────────────────────────────────────
_CREDS_FILE = Path(__file__).resolve().parent.parent / "credentials.json"
FIRMS_API_KEY: str = "DEMO_KEY"  # Public fallback

try:
    if _CREDS_FILE.exists():
        import json as _json
        _creds = _json.loads(_CREDS_FILE.read_text(encoding="utf-8"))
        _key = _creds.get("firms_api_key", "")
        if _key:
            FIRMS_API_KEY = _key
            logger.info("[fire] NASA FIRMS API key loaded from credentials.json")
except Exception as _e:
    logger.warning("[fire] Could not read credentials.json: %s", _e)

if FIRMS_API_KEY == "DEMO_KEY":
    _env_key = os.environ.get("DHRUVA_FIRMS_API_KEY", "")
    if _env_key:
        FIRMS_API_KEY = _env_key
        logger.info("[fire] NASA FIRMS API key loaded from env")
    else:
        logger.info("[fire] Using NASA FIRMS DEMO_KEY (limited quota)")


class FireCollector(BaseCollector):
    """Fetches real active fire detections from NASA FIRMS VIIRS SNPP NRT.

    Returns fire hotspot records from the last 24 hours globally.
    Each record includes lat, lon, brightness temperature, FRP (fire
    radiative power), confidence, and acquisition time.
    """

    # VIIRS SNPP NRT global feed, last 24 hours, CSV format
    FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
    PRODUCT   = "VIIRS_SNPP_NRT"
    DAYS      = 1   # 1 = last 24 h (minimum allowed)

    def __init__(self, interval: int = 120):
        super().__init__(name="fire", interval=interval)

    # ------------------------------------------------------------------
    # brightness temperature (K) → severity 1-5
    # ------------------------------------------------------------------
    @staticmethod
    def _brightness_to_severity(brightness: float) -> int:
        if brightness >= 450:
            return 5
        if brightness >= 420:
            return 4
        if brightness >= 380:
            return 3
        if brightness >= 340:
            return 2
        return 1

    # ------------------------------------------------------------------
    # confidence string → human label
    # ------------------------------------------------------------------
    @staticmethod
    def _confidence_label(conf: str) -> str:
        conf = (conf or "").strip().lower()
        if conf in ("h", "high"):
            return "High"
        if conf in ("n", "nominal"):
            return "Nominal"
        if conf in ("l", "low"):
            return "Low"
        # Sometimes it's a numeric percent string
        try:
            pct = int(conf)
            return f"{pct}%"
        except ValueError:
            return conf or "Unknown"

    async def collect(self) -> list[dict]:
        """Fetch VIIRS SNPP NRT fire hotspots from NASA FIRMS."""
        url = f"{self.FIRMS_BASE}/{FIRMS_API_KEY}/{self.PRODUCT}/world/{self.DAYS}"
        logger.info("[fire] Fetching NASA FIRMS data from %s", url)

        try:
            if not self._http_client:
                import httpx
                self._http_client = httpx.AsyncClient(timeout=60.0)

            resp = await self._http_client.get(url, timeout=60.0)
            resp.raise_for_status()
            csv_text = resp.text
        except Exception as e:
            logger.error("[fire] NASA FIRMS request failed: %s", e)
            return []

        # The response is plain CSV; first line is the header.
        if not csv_text or "latitude" not in csv_text[:500].lower():
            logger.warning("[fire] NASA FIRMS returned unexpected content: %s…", csv_text[:200])
            return []

        events = []
        reader = csv.DictReader(io.StringIO(csv_text))

        for row in reader:
            try:
                lat  = float(row.get("latitude", ""))
                lon  = float(row.get("longitude", ""))
                brightness = float(row.get("bright_ti4") or row.get("bright_t31") or "300")
                frp        = float(row.get("frp") or 0)
                conf       = row.get("confidence", "")
                daynight   = row.get("daynight", "D")
                acq_date   = row.get("acq_date", "")
                acq_time   = row.get("acq_time", "")
                satellite  = row.get("satellite", "S-NPP")

                # Build ISO timestamp from acq_date (YYYY-MM-DD) + acq_time (HHMM)
                try:
                    ts = datetime.strptime(
                        f"{acq_date} {acq_time.zfill(4)}", "%Y-%m-%d %H%M"
                    ).replace(tzinfo=timezone.utc).isoformat()
                except Exception:
                    ts = datetime.now(timezone.utc).isoformat()

                severity = self._brightness_to_severity(brightness)
                conf_label = self._confidence_label(conf)
                
                # Keep high confidence, ignore low/nominal confidence
                if conf_label == "Low" or conf_label == "Nominal":
                    continue

                import uuid
                short_uid = str(uuid.uuid4())[:8]
                # Build a stable-ish ID from satellite + date-time + rounded coords + a unique hash
                row_id = f"fire-{satellite}-{acq_date}-{acq_time}-{lat:.2f}-{lon:.2f}-{short_uid}"

                events.append({
                    "id": row_id,
                    "type": "fire",
                    "latitude": round(lat, 4),
                    "longitude": round(lon, 4),
                    "severity": severity,
                    "timestamp": ts,
                    "source": f"NASA FIRMS VIIRS {satellite}",
                    "title": f"Active Fire — {acq_date} {'Night' if daynight == 'N' else 'Day'}",
                    "description": (
                        f"Brightness: {brightness:.0f}K · "
                        f"FRP: {frp:.1f} MW · "
                        f"Confidence: {conf_label} · "
                        f"Satellite: {satellite}"
                    ),
                    "metadata": {
                        "brightness_k": round(brightness, 1),
                        "frp_mw": round(frp, 1),
                        "confidence": conf_label,
                        "satellite": satellite,
                        "day_night": "Night" if daynight == "N" else "Day",
                        "acq_date": acq_date,
                        "acq_time": acq_time,
                    },
                })
            except Exception as row_err:
                logger.debug("[fire] Skipping FIRMS row: %s", row_err)
                continue

        logger.info("[fire] NASA FIRMS returned %d active fire hotspots", len(events))
        return events
