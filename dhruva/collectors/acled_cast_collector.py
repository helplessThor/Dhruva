"""Dhruva — ACLED CAST (Conflict Alert System) Collector.

Uses the ACLED API v3 CAST endpoint to fetch conflict forecasts.
"""

import logging
from datetime import datetime, timezone

from collectors.base_collector import BaseCollector

# Load credentials directly from config to avoid cross-module import races
try:
    from backend.config import settings
    ACLED_EMAIL = getattr(settings, "acled_email", "") or ""
    ACLED_PASSWORD = getattr(settings, "acled_password", "") or ""
except Exception:
    ACLED_EMAIL = ""
    ACLED_PASSWORD = ""

logger = logging.getLogger("dhruva.collector")

# A simple mapping of country names to approximate center coordinates
# Expand as needed for countries covered by ACLED CAST
COUNTRY_COORDS = {
    "Afghanistan": (33.9391, 67.7099),
    "Albania": (41.1533, 20.1683),
    "Algeria": (28.0339, 1.6596),
    "Angola": (-11.2027, 17.8739),
    "Argentina": (-38.4161, -63.6167),
    "Armenia": (40.0691, 45.0382),
    "Australia": (-25.2744, 133.7751),
    "Austria": (47.5162, 14.5501),
    "Azerbaijan": (40.1431, 47.5769),
    "Bahrain": (26.0667, 50.5577),
    "Bangladesh": (23.6850, 90.3563),
    "Belarus": (53.7098, 27.9534),
    "Belgium": (50.5039, 4.4699),
    "Benin": (9.3077, 2.3158),
    "Bhutan": (27.5142, 90.4336),
    "Bolivia": (-16.2902, -63.5887),
    "Bosnia and Herzegovina": (43.9159, 17.6791),
    "Botswana": (-22.3285, 24.6849),
    "Brazil": (-14.2350, -51.9253),
    "Bulgaria": (42.7339, 25.4858),
    "Burkina Faso": (12.2383, -1.5616),
    "Burundi": (-3.3731, 29.9189),
    "Cambodia": (12.5657, 104.9910),
    "Cameroon": (7.3697, 12.3547),
    "Canada": (56.1304, -106.3468),
    "Central African Republic": (6.6111, 20.9394),
    "Chad": (15.4542, 18.7322),
    "Chile": (-35.6751, -71.5430),
    "China": (35.8617, 104.1954),
    "Colombia": (4.5709, -74.2973),
    "Costa Rica": (9.7489, -83.7534),
    "Croatia": (45.1000, 15.2000),
    "Cuba": (21.5218, -77.7812),
    "Cyprus": (35.1264, 33.4299),
    "Czech Republic": (49.8175, 15.4730),
    "Democratic Republic of Congo": (-4.0383, 21.7587),
    "Denmark": (56.2639, 9.5018),
    "Djibouti": (11.8251, 42.5903),
    "Dominican Republic": (18.7357, -70.1627),
    "Ecuador": (-1.8312, -78.1834),
    "Egypt": (26.8206, 30.8025),
    "El Salvador": (13.7942, -88.8965),
    "Equatorial Guinea": (1.6508, 10.2679),
    "Eritrea": (15.1794, 39.7823),
    "Estonia": (58.5953, 25.0136),
    "Ethiopia": (9.1450, 40.4897),
    "Fiji": (-17.7134, 178.0650),
    "Finland": (61.9241, 25.7482),
    "France": (46.2276, 2.2137),
    "Gabon": (-0.8037, 11.6094),
    "Gambia": (13.4432, -15.3101),
    "Georgia": (42.3154, 43.3569),
    "Germany": (51.1657, 10.4515),
    "Ghana": (7.9465, -1.0232),
    "Greece": (39.0742, 21.8243),
    "Guatemala": (15.7835, -90.2308),
    "Guinea": (9.9456, -9.6966),
    "Guinea-Bissau": (11.8037, -15.1804),
    "Haiti": (18.9712, -72.2852),
    "Honduras": (15.2000, -86.2419),
    "Hungary": (47.1625, 19.5033),
    "Iceland": (64.9631, -19.0208),
    "India": (20.5937, 78.9629),
    "Indonesia": (-0.7893, 113.9213),
    "Iran": (32.4279, 53.6880),
    "Iraq": (33.2232, 43.6793),
    "Ireland": (53.1424, -7.6921),
    "Israel": (31.0461, 34.8516),
    "Italy": (41.8719, 12.5674),
    "Ivory Coast": (7.5400, -5.5471),
    "Jamaica": (18.1096, -77.2975),
    "Japan": (36.2048, 138.2529),
    "Jordan": (31.2400, 36.5126),
    "Kazakhstan": (48.0196, 66.9237),
    "Kenya": (-0.0236, 37.9062),
    "Kuwait": (29.3117, 47.4818),
    "Kyrgyzstan": (41.2044, 74.7661),
    "Laos": (19.8563, 102.4955),
    "Latvia": (56.8796, 24.6032),
    "Lebanon": (33.8547, 35.8623),
    "Lesotho": (-29.6100, 28.2336),
    "Liberia": (6.4281, -9.4295),
    "Libya": (26.3351, 17.2283),
    "Lithuania": (55.1694, 23.8813),
    "Luxembourg": (49.8153, 6.1296),
    "Madagascar": (-18.7669, 46.8691),
    "Malawi": (-13.2543, 34.3015),
    "Malaysia": (4.2105, 101.9758),
    "Mali": (17.5707, -3.9962),
    "Mauritania": (21.0079, -10.9408),
    "Mauritius": (-20.3484, 57.5522),
    "Mexico": (23.6345, -102.5528),
    "Moldova": (47.4116, 28.3699),
    "Mongolia": (46.8625, 103.8467),
    "Montenegro": (42.7087, 19.3744),
    "Morocco": (31.7917, -7.0926),
    "Mozambique": (-18.6657, 35.5296),
    "Myanmar": (21.9162, 95.9560),
    "Namibia": (-22.9576, 18.4904),
    "Nepal": (28.3949, 84.1240),
    "Netherlands": (52.1326, 5.2913),
    "New Zealand": (-40.9006, 174.8860),
    "Nicaragua": (12.8654, -85.2072),
    "Niger": (17.6078, 8.0817),
    "Nigeria": (9.0820, 8.6753),
    "North Korea": (40.3399, 127.5101),
    "North Macedonia": (41.6086, 21.7453),
    "Norway": (60.4720, 8.4689),
    "Oman": (21.5126, 55.9233),
    "Pakistan": (30.3753, 69.3451),
    "Palestine": (31.9522, 35.2332),
    "Panama": (8.5380, -80.7821),
    "Papua New Guinea": (-5.6816, 144.2489),
    "Paraguay": (-23.4425, -58.4438),
    "Peru": (-9.1900, -75.0152),
    "Philippines": (12.8797, 121.7740),
    "Poland": (51.9194, 19.1451),
    "Portugal": (39.3999, -8.2245),
    "Qatar": (25.3548, 51.1839),
    "Republic of Congo": (-0.2280, 15.8277),
    "Romania": (45.9432, 24.9668),
    "Russia": (61.5240, 105.3188),
    "Rwanda": (-1.9403, 29.8739),
    "Saudi Arabia": (23.8859, 45.0792),
    "Senegal": (14.4974, -14.4524),
    "Serbia": (44.0165, 21.0059),
    "Sierra Leone": (8.4606, -11.7799),
    "Singapore": (1.3521, 103.8198),
    "Slovakia": (48.6690, 19.6990),
    "Slovenia": (46.1512, 14.9955),
    "Somalia": (5.1521, 46.1996),
    "South Africa": (-30.5595, 22.9375),
    "South Korea": (35.9078, 127.7669),
    "South Sudan": (6.8770, 31.3070),
    "Spain": (40.4637, -3.7492),
    "Sri Lanka": (7.8731, 80.7718),
    "Sudan": (12.8628, 30.2176),
    "Suriname": (3.9193, -56.0278),
    "Sweden": (60.1282, 18.6435),
    "Switzerland": (46.8182, 8.2275),
    "Syria": (34.8021, 38.9968),
    "Taiwan": (23.6978, 120.9605),
    "Tajikistan": (38.8610, 71.2761),
    "Tanzania": (-6.3690, 34.8888),
    "Thailand": (15.8700, 100.9925),
    "Togo": (8.6195, 0.8248),
    "Trinidad and Tobago": (10.6918, -61.2225),
    "Tunisia": (33.8869, 9.5375),
    "Turkey": (38.9637, 35.2433),
    "Turkmenistan": (38.9697, 59.5563),
    "Uganda": (1.3733, 32.2903),
    "Ukraine": (48.3794, 31.1656),
    "United Arab Emirates": (23.4241, 53.8478),
    "United Kingdom": (55.3781, -3.4360),
    "United States": (37.0902, -95.7129),
    "Uruguay": (-32.5228, -55.7658),
    "Uzbekistan": (41.3775, 64.5853),
    "Venezuela": (6.4238, -66.5897),
    "Vietnam": (14.0583, 108.2772),
    "Yemen": (15.5527, 48.5164),
    "Zambia": (-13.1339, 27.8493),
    "Zimbabwe": (-19.0154, 29.1549),
}


class ACLEDCastCollector(BaseCollector):
    """Fetches predictive conflict alerts from the ACLED CAST API."""

    def __init__(self, interval: int = 21600):  # Every 6 hours
        super().__init__(name="acled_cast", interval=interval)
        self._configured = bool(ACLED_EMAIL and ACLED_PASSWORD)
        self._logged_in = False

        if not self._configured:
            logger.warning(
                "[acled-cast] ACLED email or password not configured."
            )

    async def _login(self) -> bool:
        """Authenticate with ACLED API via email/password."""
        login_url = "https://acleddata.com/user/login?_format=json"
        payload = {
            "name": ACLED_EMAIL,
            "pass": ACLED_PASSWORD
        }
        
        if not self._http_client:
            import httpx
            self._http_client = httpx.AsyncClient(timeout=30.0)
            
        try:
            resp = await self._http_client.post(login_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "csrf_token" in data:
                self._logged_in = True
                logger.info("[acled-cast] Successfully authenticated with ACLED API")
                return True
            return False
        except Exception as e:
            logger.error("[acled-cast] Login failed: %s", e)
            return False

    async def collect(self) -> list[dict]:
        """Fetch CAST predictions for current month/year."""
        logger.info("[acled-cast] Starting collection cycle...")
        
        # Verify credentials at runtime to avoid module load races
        if not self._configured:
            from backend.config import settings
            email = getattr(settings, "acled_email", "") or ""
            pwd = getattr(settings, "acled_password", "") or ""
            if email and pwd:
                global ACLED_EMAIL, ACLED_PASSWORD
                ACLED_EMAIL = email
                ACLED_PASSWORD = pwd
                self._configured = True
        
        if not self._configured:
            logger.warning("[acled-cast] Cannot collect: credentials missing.")
            return []

        if not self._logged_in:
            logger.info("[acled-cast] Logging in...")
            success = await self._login()
            if not success:
                logger.error("[acled-cast] Login completely failed. Aborting collect.")
                return []

        now = datetime.now(timezone.utc)
        current_year = now.year
        current_month = now.strftime("%B")  # Full month name (e.g. "February")

        params = {
            "year": current_year,
            "month": current_month,
            "limit": 500,
        }

        try:
            data = await self.fetch_json("https://acleddata.com/api/cast/read", params=params)
            results = data.get("data", [])
            
            if not results:
                logger.info("[acled-cast] No forecast data returned")
                return []

            events = []
            for record in results:
                event = self._parse_cast_record(record, current_year, current_month)
                if event:
                    events.append(event)

            logger.info("[acled-cast] Generated %d predictive alerts", len(events))
            return events

        except Exception as e:
            logger.error("[acled-cast] Fetch failed: %s", e)
            self._logged_in = False
            return []

    def _parse_cast_record(self, record: dict, year: int, month: str) -> dict | None:
        country = record.get("country", "")
        admin1 = record.get("admin1", "")
        
        try:
            total_forecast = int(record.get("total_forecast", 0))
        except (ValueError, TypeError):
            total_forecast = 0

        # Only care about regions with notable forecasted activity
        if total_forecast < 5:
            return None

        # Geocode using our basic country map
        coords = COUNTRY_COORDS.get(country)
        if not coords:
            return None
            
        lat, lon = coords
        
        # Add slight jitter so multiple admin1 alerts for same country dont perfectly overlap
        import random
        lat += random.uniform(-0.5, 0.5)
        lon += random.uniform(-0.5, 0.5)

        battles = int(record.get("battles_forecast", 0))
        vac = int(record.get("vac_forecast", 0))

        severity = 2
        if total_forecast > 10 or battles > 2:
            severity = 3
        if total_forecast > 20 or battles > 5:
            severity = 4

        desc = f"CAST Forecast for {admin1}, {country}: {total_forecast} events expected this month."
        if battles > 0:
            desc += f" Battles: {battles}."
        if vac > 0:
            desc += f" Violence Against Civilians: {vac}."

        return {
            "id": f"acled-cast-{country}-{admin1}-{year}-{month}".replace(" ", "-").lower(),
            "type": "acled_cast",
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "severity": severity,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "ACLED CAST",
            "title": f"Predicted Conflict Alert — {admin1}",
            "description": desc,
            "metadata": {
                "country": country,
                "admin1": admin1,
                "total_forecast": total_forecast,
                "battles_forecast": battles,
                "vac_forecast": vac,
                "forecast_period": f"{month} {year}",
                "is_predictive": True
            },
        }
