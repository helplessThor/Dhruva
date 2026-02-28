# Dhruva — OSINT Global Situational Awareness Dashboard

**Palantir-style intelligence dashboard** visualizing real-time OSINT data on an interactive 3D globe with a dark military theme. Dhruva merges official institutional APIs with dynamic AI-verified OSINT scrapers to detect global events, multi-domain intelligence hotspots, and geographic convergence.

![Architecture](https://img.shields.io/badge/Architecture-FastAPI%20+%20React%20+%20CesiumJS-blue)
![AI Verification](https://img.shields.io/badge/OSINT-Groq%20LLM%20Verification-orange)
![License](https://img.shields.io/badge/License-MIT-green)

---

## Quick Start

### Prerequisites
- **Python 3.11+**
- **Node.js 18+** / npm
- Redis *(optional — app works natively with in-memory fallback)*

### 1. Backend

```bash
cd dhruva/backend

# Create virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Start the server
python main.py
```

Backend runs at **http://localhost:8000**

### 2. Frontend

```bash
cd dhruva/frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```

Frontend runs at **http://localhost:5173**

### 3. Environment Variables (Optional but Recommended)

Create `dhruva/backend/.env` for external API and AI integration:

```env
DHRUVA_USE_REDIS=false
DHRUVA_GROQ_API_KEY=your_groq_api_key                # OSINT Text scraping & verification
DHRUVA_ACLED_API_KEY=your_acled_key                  # ACLED Conflict Data
DHRUVA_ACLED_EMAIL=your_email                        # ACLED Email
DHRUVA_UCDP_API_TOKEN=your_ucdp_token                # UCDP Conflict Data
DHRUVA_FLIGHTAWARE_API_KEY=your_flightaware_key      # Aircraft & Military Flight Tracking
DHRUVA_POSITION_API_TOKEN=your_marine_token          # Marine / Navy Tracking
DHRUVA_N2YO_API_KEY=your_n2yo_key                    # Live Satellite Tracking
```

Create `dhruva/frontend/.env`:

```env
VITE_CESIUM_ION_TOKEN=your_cesium_ion_token          # 3D Globe Rendering
```

---

## Architecture

Dhruva utilizes a decoupled architecture where Python Async Collectors constantly pull data from 15+ sources. Official API data is then automatically merged with OSINT news scraping verified by an intelligent Groq LLM fallback cycle.

```
┌──────────────────────────────────────────────────────────────────────┐
│                        DHRUVA ARCHITECTURE                           │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌────────────┐  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │ Earthquake │  │ Marine/Navy │  │ Satellites   │  │ UCDP/ACLED  │  │
│  │ (USGS+OSINT)  │ (OpenSeaAPI)│  │ (N2YO API)   │  │ (APIs+OSINT)│  │
│  └──────┬─────┘  └──────┬──────┘  └──────┬───────┘  └──────┬──────┘  │
│         │               │                │                 │         │
│         ▼               ▼                ▼                 ▼         │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                 Fusion Engine (Normalizer)                     │  │
│  │    LLM Deduplication, OSINT Verification & Geocoding Fallback  │  │
│  └──────────────────────────────┬─────────────────────────────────┘  │
│                                 ▼                                    │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │            Intel Hotspot & Convergence Calculator              │  │
│  └──────────────────────────────┬─────────────────────────────────┘  │
│                                 ▼                                    │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                 REST API (HTTP) / WebSocket (WS)               │  │
│  └──────────────────────────────┬─────────────────────────────────┘  │
│                                 ▼                                    │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                  React + TypeScript + CesiumJS                 │  │
│  │        (3D Globe | Active Sidebar | DEFCON Risk Dashboard)     │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Data Layers & Collectors

Dhruva boasts 15 highly tuned tracking layers. OSINT scraping feeds intelligently overlap against official reporting.

| Layer | Source Engine | Data Integration |
|-------|--------------|------------------|
| 🌍 **Earthquakes** | USGS GeoJSON + Google RSS | Official API merged with AI-verified breaking OSINT |
| ⚔️ **UCDP Conflicts**| UCDP Official API + RSS | Military clashes and casualties verified via LLM deduplication |
| 🛡 **ACLED & CAST**| ACLED / CAST Datasets | Predictive Heatmaps & Real-time alert vectors |
| ✈️ **Aircraft** | OpenSky / FlightAware | Dedicated High-Value Military Aircraft sorting and 3D rotation |
| 🚢 **Marine / Naval** | PositionAPI / AIS | Dedicated High-Value Military, Carrier, & Oil Tanker visibility |
| 📡 **Outages** | IODA + nominatim OSM | Global tracking with intelligent dynamic OpenStreetMap geocoder |
| 💻 **Cyber Attacks**| OSINT-TI | Real-time tracking of DDOS and network infiltration operations |
| 🔥 **Active Fires** | NASA FIRMS | Forest fires & heat-anomalies |
| 🛰 **Satellites** | N2YO API | Tracks all 57 orbit categories with automated rate-limit recovery |
| 📈 **Economic** | Yahoo Finance / RSS | Market instability & critical commodity alerts |
| 🎯 **Hotspots** | Fusion Engine | Spatial algorithm detecting heavy volume in a 1°×1° grid |
| 🚨 **Convergence** | Fusion Engine | **Multi-Domain Intelligence** (Detects when 3+ different alert types happen in the exact same location) |

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Server status |
| GET | `/api/events` | All events across active layers |
| GET | `/api/events/{layer}` | Events for specific layer |
| GET | `/api/risk` | Current DEFCON global risk level |
| GET | `/api/layers` | Available layers + current event counts |
| WS | `/ws` | Real-time multiplexed WebSocket stream |

---

## Extending with New Collectors

1. Create `collectors/your_collector.py` extending `BaseCollector`
2. Implement the `collect()` method returning `list[dict]`
3. Register it in `backend/main.py`'s active collectors array
4. Add the layer type to `EventType` enum in `backend/models.py`
5. Add the respective layer toggle and SVG icon in `frontend/src/types/events.ts` and `LayerIcon.tsx`

---

## License

MIT
