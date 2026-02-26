"""Dhruva — Conflict Events Collector (retired mock).

Real conflict data is now sourced from:
  - GDELTCollector  -> 'gdelt_conflict' layer (CAMEO codes 19*, 20*)
  - ACLEDCollector  -> 'acled' layer  (when API key is available)
  - UCDPCollector   -> 'ucdp' layer   (when auth token is available)

This collector intentionally returns an empty list to avoid polluting
the intelligence hotspot engine with synthetic data.
"""

import logging
from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")


class ConflictCollector(BaseCollector):
    """Retired mock conflict collector — replaced by GDELT/ACLED/UCDP real sources."""

    def __init__(self, interval: int = 300):
        super().__init__(name="conflict", interval=interval)

    async def collect(self) -> list[dict]:
        logger.debug(
            "[conflict] Mock collector disabled — real conflict data comes from "
            "gdelt_conflict, acled, and ucdp layers."
        )
        return []
