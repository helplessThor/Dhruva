"""Dhruva — Market Data Fetcher.

Fetches major global stock index data from Yahoo Finance API.
Runs as a background task, updating every 2 minutes.
Provides a REST endpoint at /api/market-data.
"""

import asyncio
import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("dhruva.market")

# ── Global stock indexes ───────────────────────────────────────────
# (yahoo_symbol, display_name, flag_emoji)
INDEXES = [
    ("^GSPC", "S&P 500", "🇺🇸"),
    ("^DJI", "DOW JONES", "🇺🇸"),
    ("^IXIC", "NASDAQ", "🇺🇸"),
    ("^FTSE", "FTSE 100", "🇬🇧"),
    ("^GDAXI", "DAX", "🇩🇪"),
    ("^FCHI", "CAC 40", "🇫🇷"),
    ("^N225", "NIKKEI 225", "🇯🇵"),
    ("^HSI", "HANG SENG", "🇭🇰"),
    ("000001.SS", "SSE COMP", "🇨🇳"),
    ("^BSESN", "SENSEX", "🇮🇳"),
    ("^NSEI", "NIFTY 50", "🇮🇳"),
    ("^AXJO", "ASX 200", "🇦🇺"),
    ("^KS11", "KOSPI", "🇰🇷"),
    ("^TWII", "TAIEX", "🇹🇼"),
    ("^STOXX50E", "EURO STOXX 50", "🇪🇺"),
]

# Yahoo Finance chart API (no key required)
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

# In-memory store for latest market data
market_data: list[dict] = []
_fetch_lock = asyncio.Lock()


async def fetch_index(client: httpx.AsyncClient, symbol: str, name: str, flag: str) -> dict | None:
    """Fetch a single index quote from Yahoo Finance."""
    try:
        resp = await client.get(
            YAHOO_CHART_URL.format(symbol=symbol),
            params={"range": "1d", "interval": "1d"},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        result = data.get("chart", {}).get("result", [])
        if not result:
            return None

        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice", 0)
        prev_close = meta.get("chartPreviousClose") or meta.get("previousClose", 0)

        if not price or not prev_close:
            return None

        change = price - prev_close
        change_pct = (change / prev_close) * 100 if prev_close else 0

        return {
            "symbol": symbol,
            "name": name,
            "flag": flag,
            "price": round(price, 2),
            "change": round(change, 2),
            "changePct": round(change_pct, 2),
            "prevClose": round(prev_close, 2),
            "currency": meta.get("currency", "USD"),
            "exchange": meta.get("exchangeName", ""),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.debug("[market] Failed to fetch %s: %s", symbol, e)
        return None


async def fetch_all_indexes():
    """Fetch all global index data."""
    global market_data

    async with _fetch_lock:
        async with httpx.AsyncClient(timeout=15.0) as client:
            tasks = [
                fetch_index(client, sym, name, flag)
                for sym, name, flag in INDEXES
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        valid = [r for r in results if isinstance(r, dict)]
        if valid:
            market_data = valid
            logger.info("[market] Updated %d/%d indexes", len(valid), len(INDEXES))
        else:
            logger.warning("[market] No index data received")


async def market_data_loop(interval: int = 120):
    """Background loop: fetch market data every `interval` seconds."""
    logger.info("[market] Starting market data fetcher (interval=%ds)", interval)
    while True:
        try:
            await fetch_all_indexes()
        except Exception as e:
            logger.error("[market] Fetch error: %s", e)
        await asyncio.sleep(interval)


def get_market_data() -> list[dict]:
    """Return the latest market data snapshot."""
    return market_data
