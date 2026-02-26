# Dhruva — OSINT Global Situational Awareness Dashboard

**Palantir-style intelligence dashboard** visualizing real-time OSINT data on an interactive 3D globe with a dark military theme.

![Architecture](https://img.shields.io/badge/Architecture-FastAPI%20+%20React%20+%20CesiumJS-blue)
![License](https://img.shields.io/badge/License-MIT-green)

---

## Quick Start

### Prerequisites
- **Python 3.11+**
- **Node.js 18+** / npm
- Redis *(optional — app works without it)*

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

### 3. Environment Variables (Optional)

Create `dhruva/backend/.env`:

```env
DHRUVA_USE_REDIS=false
DHRUVA_CESIUM_ION_TOKEN=your_cesium_ion_token
DHRUVA_ACLED_API_KEY=your_acled_key
```

Create `dhruva/frontend/.env`:

```env
VITE_CESIUM_ION_TOKEN=your_cesium_ion_token
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    DHRUVA ARCHITECTURE                    │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌──────────────┐ │
│  │ Earthquake   │    │ Fire        │    │ Conflict     │ │
│  │ (USGS)       │    │ (NASA FIRMS)│    │ (ACLED)      │ │
│  └──────┬───────┘    └──────┬──────┘    └──────┬───────┘ │
│         │                   │                   │        │
│         ▼                   ▼                   ▼        │
│  ┌──────────────────────────────────────────────────┐    │
│  │           Fusion Engine (Normalizer)              │    │
│  │           Risk Calculator (DEFCON)                │    │
│  └──────────────────────┬───────────────────────────┘    │
│                         │                                │
│                         ▼                                │
│  ┌──────────────────────────────────────────────────┐    │
│  │     Redis Streams / In-Memory Fallback            │    │
│  └──────────────────────┬───────────────────────────┘    │
│                         │                                │
│              ┌──────────┴──────────┐                     │
│              │                     │                     │
│              ▼                     ▼                     │
│  ┌───────────────────┐  ┌─────────────────┐             │
│  │  REST API (HTTP)   │  │  WebSocket (WS)  │             │
│  │  /api/events       │  │  /ws              │             │
│  └───────────────────┘  └─────────────────┘             │
│              │                     │                     │
│              └──────────┬──────────┘                     │
│                         │                                │
│                         ▼                                │
│  ┌──────────────────────────────────────────────────┐    │
│  │          React + TypeScript + CesiumJS            │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────────┐  │    │
│  │  │ 3D Globe │ │ Sidebar  │ │ DEFCON Indicator │  │    │
│  │  └──────────┘ └──────────┘ └──────────────────┘  │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

---

## Data Layers

| Layer | Source | Data Type | Update Interval |
|-------|--------|-----------|----------------|
| 🌍 Earthquakes | USGS GeoJSON | Real-time | 60s |
| 🔥 Active Fires | NASA FIRMS | Simulated | 120s |
| ⚔️ Conflicts | ACLED/UCDP | Simulated | 300s |
| ✈️ Aircraft | OpenSky Network | Real + Fallback | 15s |
| 🚢 Marine Traffic | AIS | Simulated | 30s |
| 💻 Cyber Attacks | OSINT-TI | Simulated | 60s |
| 📡 Internet Outages | NetBlocks | Simulated | 120s |
| 📈 Economic Indices | Market Data | Simulated | 300s |

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Server status |
| GET | `/api/events` | All events across layers |
| GET | `/api/events/{layer}` | Events for specific layer |
| GET | `/api/risk` | Current DEFCON risk level |
| GET | `/api/layers` | Available layers + counts |
| WS | `/ws` | Real-time event stream |

---

## Project Structure

```
dhruva/
├── backend/
│   ├── main.py              # FastAPI application
│   ├── config.py            # Environment-based settings
│   ├── models.py            # Pydantic schemas
│   ├── redis_manager.py     # Redis/in-memory stream
│   ├── websocket_manager.py # WS connection manager
│   └── requirements.txt
├── collectors/
│   ├── base_collector.py    # Abstract base class
│   ├── earthquake_collector.py  # ← Real USGS data
│   ├── fire_collector.py
│   ├── conflict_collector.py
│   ├── aircraft_collector.py    # ← Real OpenSky data
│   ├── marine_collector.py
│   ├── cyber_collector.py
│   ├── outage_collector.py
│   └── economic_collector.py
├── fusion_engine/
│   ├── normalizer.py        # Event validation
│   └── risk_calculator.py   # DEFCON risk scoring
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── Globe/DhruvaGlobe.tsx
│   │   │   ├── Sidebar/EventSidebar.tsx
│   │   │   ├── Controls/LayerToggles.tsx
│   │   │   ├── RiskIndicator/DefconIndicator.tsx
│   │   │   └── Views/{Air,Marine,Cyber}View.tsx
│   │   ├── hooks/useWebSocket.ts
│   │   ├── types/events.ts
│   │   └── styles/index.css
│   └── vite.config.ts
├── config/
│   └── settings.yaml
└── README.md
```

---

## Extending with New Collectors

1. Create `collectors/your_collector.py` extending `BaseCollector`
2. Implement the `collect()` method returning `list[dict]`
3. Register it in `backend/main.py` collectors list
4. Add the layer type to `EventType` enum in `models.py`
5. Add layer config in `frontend/src/types/events.ts`

---

## License

MIT
