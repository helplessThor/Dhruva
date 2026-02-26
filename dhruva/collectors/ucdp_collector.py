"""Dhruva — UCDP Conflict Events Collector (Real Data).

Fetches georeferenced conflict events from the Uppsala Conflict Data Program
(UCDP) GED API.

API: https://ucdpapi.pcr.uu.se/api/gedevents/{version}
Data: Georeferenced individual-level events with coordinates, actors, fatalities.

NOTE: The UCDP API now requires an authentication token for all endpoints.
To obtain a token, contact the UCDP API maintainer at: https://ucdp.uu.se/apidocs/
The collector will gracefully return empty results until a token is configured.
"""

import logging
from datetime import datetime, timezone, timedelta

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

# UCDP GED API
UCDP_API_BASE = "https://ucdpapi.pcr.uu.se/api"
UCDP_GED_VERSION = "25.1"

# Candidate events are more recent (monthly updates for current year)
UCDP_CANDIDATE_VERSION = "25.01.25.12"

# Freshness: UCDP data has inherent lag (academic dataset)
FRESHNESS_WINDOW_DAYS = 365  # Accept events up to 1 year old (dataset updates annually)


class UCDPCollector(BaseCollector):
    """Fetches real conflict events from UCDP Georeferenced Event Dataset API.

    NOTE: UCDP API currently requires authentication. The collector will
    attempt to fetch data and log clear warnings if access is denied (401).
    """

    MAX_EVENTS = 200
    PAGE_SIZE = 100

    # UCDP type_of_violence mapping
    VIOLENCE_TYPES = {
        1: "State-based armed conflict",
        2: "Non-state conflict",
        3: "One-sided violence",
    }

    def __init__(self, interval: int = 300):
        super().__init__(name="ucdp", interval=interval)
        self._last_fetched_at: datetime | None = None
        self._use_candidate = True  # Try candidate (newer) first, fall back to GED
        self._auth_warned = False

    async def collect(self) -> list[dict]:
        """Fetch UCDP conflict events."""
        events = []

        # Try candidate events first (more recent data)
        if self._use_candidate:
            try:
                events = await self._fetch_candidate_events()
                if events:
                    self._last_fetched_at = datetime.now(timezone.utc)
                    return events
            except Exception as e:
                err_str = str(e)
                if "401" in err_str or "Unauthorized" in err_str:
                    if not self._auth_warned:
                        logger.warning(
                            "[ucdp] UCDP API requires authentication (401 Unauthorized). "
                            "To obtain a token, contact: https://ucdp.uu.se/apidocs/ "
                            "— returning empty results until token is configured."
                        )
                        self._auth_warned = True
                    return []
                logger.warning("[ucdp] Candidate events failed, trying GED: %s", e)
                self._use_candidate = False

        # Fall back to GED (main dataset)
        try:
            events = await self._fetch_ged_events()
            self._last_fetched_at = datetime.now(timezone.utc)
        except Exception as e:
            err_str = str(e)
            if "401" in err_str or "Unauthorized" in err_str:
                if not self._auth_warned:
                    logger.warning(
                        "[ucdp] UCDP API requires authentication (401 Unauthorized). "
                        "To obtain a token, contact: https://ucdp.uu.se/apidocs/ "
                        "— returning empty results until token is configured."
                    )
                    self._auth_warned = True
            else:
                logger.error("[ucdp] GED fetch failed: %s", e)

        return events

    async def _fetch_candidate_events(self) -> list[dict]:
        """Fetch from UCDP Candidate Events (monthly updates, most recent)."""
        url = f"{UCDP_API_BASE}/candidateged/{UCDP_CANDIDATE_VERSION}"
        return await self._fetch_ucdp_paginated(url, "candidate")

    async def _fetch_ged_events(self) -> list[dict]:
        """Fetch from UCDP GED (annual release, comprehensive)."""
        url = f"{UCDP_API_BASE}/gedevents/{UCDP_GED_VERSION}"
        return await self._fetch_ucdp_paginated(url, "GED")

    async def _fetch_ucdp_paginated(self, base_url: str, label: str) -> list[dict]:
        """Paginated fetch from any UCDP endpoint."""
        events = []
        page = 0

        while len(events) < self.MAX_EVENTS:
            params = {
                "pagesize": self.PAGE_SIZE,
                "page": page,
            }

            try:
                data = await self.fetch_json(base_url, params=params)
            except Exception as e:
                if page == 0:
                    raise  # Re-raise if first page fails
                logger.warning("[ucdp] Page %d failed: %s", page, e)
                break

            result_list = data.get("Result", [])
            if not result_list:
                break

            for record in result_list:
                try:
                    event = self._parse_ucdp_event(record)
                    if event:
                        events.append(event)
                except Exception as e:
                    logger.debug("[ucdp] Skipping record: %s", e)
                    continue

            # Check if there are more pages
            total_count = data.get("TotalCount", 0)
            if (page + 1) * self.PAGE_SIZE >= total_count:
                break

            page += 1
            if page >= 3:  # Cap at 3 pages to be credit-conscious
                break

        logger.info("[ucdp] %s returned %d conflict events", label, len(events))
        return events

    def _parse_ucdp_event(self, record: dict) -> dict | None:
        """Parse a single UCDP GED record into an OsintEvent."""
        lat = record.get("latitude")
        lon = record.get("longitude")

        if lat is None or lon is None:
            return None

        try:
            lat = float(lat)
            lon = float(lon)
        except (ValueError, TypeError):
            return None

        # Extract fields
        event_id = record.get("id", record.get("event_id", ""))
        date_str = record.get("date_start", record.get("date", ""))
        country = record.get("country", "Unknown")
        region = record.get("region", "")

        # Actors
        side_a = record.get("side_a", "")
        side_b = record.get("side_b", "")

        # Fatalities
        deaths_a = int(record.get("deaths_a", 0) or 0)
        deaths_b = int(record.get("deaths_b", 0) or 0)
        deaths_civilians = int(record.get("deaths_civilians", 0) or 0)
        deaths_unknown = int(record.get("deaths_unknown", 0) or 0)
        best_estimate = int(record.get("best", deaths_a + deaths_b + deaths_civilians + deaths_unknown) or 0)

        # Violence type
        violence_type_id = int(record.get("type_of_violence", 0) or 0)
        violence_type = self.VIOLENCE_TYPES.get(violence_type_id, "Unknown")

        # Event type from UCDP
        event_type = record.get("type_of_event", violence_type)

        # Source info
        source_article = record.get("source_article", "")
        source_original = record.get("source_original", "UCDP")
        where_description = record.get("where_description", "")

        # Freshness check
        if date_str:
            try:
                event_date = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                cutoff = datetime.now(timezone.utc) - timedelta(days=FRESHNESS_WINDOW_DAYS)
                if event_date < cutoff:
                    return None  # Too old
            except ValueError:
                pass

        # Calculate severity from fatalities
        if best_estimate >= 25:
            severity = 5
        elif best_estimate >= 10:
            severity = 4
        elif best_estimate >= 5:
            severity = 3
        elif best_estimate >= 1:
            severity = 2
        else:
            severity = 1

        # Build description
        desc_parts = []
        desc_parts.append(violence_type)
        if where_description:
            desc_parts.append(where_description)
        if best_estimate > 0:
            desc_parts.append(f"Fatalities: {best_estimate}")
        if side_a and side_b:
            desc_parts.append(f"{side_a} vs {side_b}")
        elif side_a:
            desc_parts.append(f"Actor: {side_a}")

        return {
            "id": f"ucdp-{event_id}",
            "type": "ucdp",
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "severity": severity,
            "timestamp": date_str or datetime.now(timezone.utc).isoformat(),
            "source": f"UCDP GED ({source_original})" if source_original else "UCDP GED",
            "title": f"{event_type} — {country}",
            "description": " · ".join(desc_parts),
            "metadata": {
                "event_type": event_type,
                "violence_type": violence_type,
                "violence_type_id": violence_type_id,
                "country": country,
                "region": region,
                "side_a": side_a,
                "side_b": side_b,
                "fatalities_best": best_estimate,
                "fatalities_a": deaths_a,
                "fatalities_b": deaths_b,
                "fatalities_civilians": deaths_civilians,
                "where_description": where_description,
                "source_article": source_article,
                "ucdp_id": str(event_id),
                "date_start": date_str,
            },
        }
