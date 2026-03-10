# Satellite Imagery Feasibility, OSINT Early Warning Sources, and Production Deployment Plan

## 1) Feasibility: live/near-real-time satellite view on map zoom

## Current project baseline
- The frontend globe already uses a satellite imagery basemap (ArcGIS World Imagery) loaded in Cesium/Resium.
- The backend already has a `satellite` event layer, but that collector currently tracks orbital satellite positions via N2YO, not Earth observation image tiles.
- Real-time delivery is already implemented through FastAPI WebSocket (`/ws`) for event layers.

## What this means
Adding **live/near-real-time Earth observation imagery when users zoom into an area is feasible**, but it should be implemented as a **new imagery layer pipeline**, separate from the existing N2YO orbital tracker.

## Practical constraints to expect
- **Not truly “live video”**: open Sentinel/Landsat style products are revisit-based and cloud-constrained.
- **Latency**: depending on source and processing level, freshness can range from hours to days.
- **Coverage and resolution tradeoffs**: frequent updates usually mean lower resolution, or vice versa.
- **Cost/performance**: dynamic tile requests for every zoom/pan can increase egress and render load.

## Recommended implementation approach in this codebase
1. **Frontend (Cesium) imagery provider switching by zoom level / layer toggle**
   - Keep current ArcGIS base layer as default.
   - Add optional “EO Live Layer” toggle.
   - At high zoom levels, switch/add WMS/WMTS/TMS imagery from open EO backends.
2. **Backend metadata service**
   - Add endpoints such as `/api/imagery/availability?bbox=...&time=...` and `/api/imagery/tile-url?...`.
   - Cache scene metadata and short-lived signed tile templates where needed.
3. **Collector model extension**
   - Keep `satellite_collector.py` for orbital tracks.
   - Add a separate EO imagery collector/indexer (e.g., `eo_imagery_collector.py`) for scene indexing and freshness metadata.
4. **UX details**
   - Show “captured at” timestamp, cloud cover, and source attribution for each imagery request.
   - Add fallback: if no recent cloud-free scene, continue displaying base imagery.

## Suggested free/open imagery sources (defensive, public)
- **Copernicus Sentinel Hub ecosystem / STAC mirrors** (Sentinel-1/2, etc.).
- **AWS Open Data Landsat/Sentinel mirrors**.
- **NASA FIRMS** (already used here for fire events, not full optical imagery browsing).
- **ESA/USGS catalogs via STAC-compatible services**.

---

## 2) OSINT satellite sources for early warning (e.g., missile-launch indicators)

## Short answer
There are **free/public data sources useful for broad early-warning signals**, but they generally provide **indirect indicators** (heat anomalies, NOTAMs, seismic/infrasound proxies, social/news reports), not guaranteed direct launch detection.

## Public sources worth integrating at high level
- **NASA FIRMS thermal anomalies**: can support detection of unusual heat signatures and active burns.
- **NOTAM feeds**: temporary flight restrictions and hazard zones can be correlated with other signals.
- **Earthquake/seismic feeds** (already present in project): can provide contextual anomaly signals.
- **Open conflict/event feeds (ACLED/UCDP/news OSINT)**: useful for context and corroboration.

## Reliability and policy caveats
- High-confidence missile early warning normally requires military-grade sensors and classified pipelines.
- Public OSINT should be treated as **triage and situational awareness**, not deterministic launch confirmation.
- Implement confidence scoring and multi-source corroboration to reduce false positives.

## Recommended signal-fusion logic
- Trigger “early warning candidate” only when multiple independent signals align in space-time, e.g.:
  - thermal anomaly spike + NOTAM change + corroborating incident/news reports.
- Add severity weighting and confidence bands (low/medium/high confidence).
- Keep human-in-the-loop validation for critical alerts.

---

## 3) Production deployment with your current stack (GCP VM + Vercel + Cloudflare)

## Best-fit architecture for this repo
- **Frontend (React/Vite/Cesium) on Vercel**.
- **Backend (FastAPI + collectors + WebSocket) on existing GCP VM** using `uvicorn` behind `nginx` + `systemd`.
- **Cloudflare DNS/Proxy** routing:
  - `app.yourdomain.com` -> Vercel frontend
  - `api.yourdomain.com` -> GCP VM backend (HTTP + WebSocket)

This matches the project’s separation of frontend and backend and its persistent collector workloads.

## Required production adjustments specific to current code
1. **WebSocket URL in frontend is currently hardcoded to `ws://<hostname>:8000/ws`**.
   - In production this should use an env-based URL (e.g., `wss://api.yourdomain.com/ws`) to avoid mixed content and blocked websocket issues.
2. **CORS defaults currently include only localhost origins**.
   - Add your Vercel domain(s) and Cloudflare-served origin to backend env config.
3. **Disable reload mode in production launch**.
   - The current `uvicorn.run(..., reload=True)` path is dev-oriented; production should run from process manager command.
4. **Secrets management**.
   - Move API keys/tokens from local files into environment variables on VM/Vercel.

## Minimal deployment checklist
1. Build and deploy frontend to Vercel.
2. Deploy backend service on GCP VM (systemd service + nginx reverse proxy).
3. Expose `/api/*` and `/ws` from `api.yourdomain.com`.
4. Configure Cloudflare DNS/proxy and SSL mode; ensure WebSockets enabled.
5. Set environment variables:
   - Backend: `DHRUVA_*` keys, CORS origins, optional Redis URL/use flag.
   - Frontend: Cesium token + API/WS base URLs.
6. Run health checks:
   - `/` and `/api/layers` over HTTPS
   - WebSocket handshake at `wss://api.yourdomain.com/ws`
7. Add observability:
   - collector error logs, process restarts, API latency, WS client counts.

## Suggested rollout strategy
- Stage first on subdomains (e.g., `staging-app`, `staging-api`).
- Validate collector behavior and WS reconnection under load.
- Promote DNS after confirming map + overlays + ticker + CCTV + WS stability.

---

## Bottom line
- **Imagery-on-zoom integration: feasible and strong fit**, but should be implemented as a dedicated EO imagery subsystem rather than extending N2YO orbital tracking.
- **Free OSINT early warning: feasible for probabilistic signals**, not guaranteed direct launch confirmation; use multi-source confidence fusion.
- **Production deployment: straightforward with your current GCP + Vercel + Cloudflare setup**, with key code/config updates around WS URL, CORS, and production process management.
