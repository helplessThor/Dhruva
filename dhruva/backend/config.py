"""Dhruva — Application Configuration."""

import json
import logging
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional

_cfg_logger = logging.getLogger("dhruva.config")


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Server
    app_name: str = "Dhruva"
    app_version: str = "1.0.0"
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_stream_key: str = "dhruva:events"
    use_redis: bool = False  # Set True when Redis is available

    # Cesium
    cesium_ion_token: str = ""

    # Collector intervals (seconds)
    earthquake_interval: int = 60
    fire_interval: int = 120
    conflict_interval: int = 300
    aircraft_interval: int = 15
    marine_interval: int = 30
    cyber_interval: int = 60
    outage_interval: int = 120
    economic_interval: int = 300
    military_interval: int = 120
    ucdp_interval: int = 600
    acled_interval: int = 600
    gdelt_interval: int = 300

    # API Keys (optional — collectors use public APIs or mock data)
    acled_api_key: Optional[str] = None
    acled_email: Optional[str] = None
    adsb_api_key: Optional[str] = None

    # OpenSky Network OAuth2 credentials
    opensky_client_id: str = ""
    opensky_client_secret: str = ""

    model_config = {"env_file": ".env", "env_prefix": "DHRUVA_"}


def _load_settings() -> Settings:
    """Load settings, supplementing with credentials.json for OpenSky keys."""
    s = Settings()

    # Auto-load credentials from credentials.json if not set via env
    creds_path = Path(__file__).resolve().parent.parent / "credentials.json"
    if creds_path.exists():
        try:
            creds = json.loads(creds_path.read_text(encoding="utf-8"))

            # OpenSky OAuth2
            if not s.opensky_client_id:
                s.opensky_client_id = creds.get("clientId", "")
                s.opensky_client_secret = creds.get("clientSecret", "")
                if s.opensky_client_id:
                    _cfg_logger.info("OpenSky credentials loaded from %s", creds_path.name)

            # ACLED API
            if not s.acled_api_key:
                s.acled_api_key = creds.get("acled_api_key", "")
                s.acled_email = creds.get("acled_email", "")
                if s.acled_api_key:
                    _cfg_logger.info("ACLED credentials loaded from %s", creds_path.name)
        except Exception as e:
            _cfg_logger.warning("Failed to read credentials.json: %s", e)

    return s


settings = _load_settings()
