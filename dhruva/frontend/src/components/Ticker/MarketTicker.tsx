import { useEffect, useState, useRef } from 'react';

interface MarketIndex {
    symbol: string;
    name: string;
    flag: string;
    price: number;
    change: number;
    changePct: number;
    currency: string;
    exchange: string;
    updatedAt: string;
}

const BACKEND_URL = `http://${window.location.hostname}:8000`;
const POLL_INTERVAL = 120_000; // 2 minutes

const MarketTicker: React.FC = () => {
    const [indexes, setIndexes] = useState<MarketIndex[]>([]);
    const [lastUpdate, setLastUpdate] = useState<string>('');
    const tickerRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const res = await fetch(`${BACKEND_URL}/api/market-data`);
                const data = await res.json();
                if (data.indexes?.length) {
                    setIndexes(data.indexes);
                    setLastUpdate(new Date().toLocaleTimeString());
                }
            } catch {
                // Will retry on next interval
            }
        };

        fetchData();
        const timer = setInterval(fetchData, POLL_INTERVAL);
        return () => clearInterval(timer);
    }, []);

    if (!indexes.length) {
        return (
            <div className="market-ticker">
                <div className="ticker-loading">Loading market data...</div>
            </div>
        );
    }

    // Duplicate items for seamless infinite scroll
    const tickerItems = [...indexes, ...indexes];

    return (
        <div className="market-ticker">
            <div className="ticker-label">
                <span className="ticker-dot" />
                MARKETS
            </div>
            <div className="ticker-track" ref={tickerRef}>
                <div className="ticker-scroll">
                    {tickerItems.map((idx, i) => {
                        const isUp = idx.change >= 0;
                        return (
                            <div key={`${idx.symbol}-${i}`} className="ticker-item">
                                <span className="ticker-flag">{idx.flag}</span>
                                <span className="ticker-name">{idx.name}</span>
                                <span className="ticker-price">
                                    {idx.price.toLocaleString(undefined, {
                                        minimumFractionDigits: 2,
                                        maximumFractionDigits: 2,
                                    })}
                                </span>
                                <span className={`ticker-change ${isUp ? 'up' : 'down'}`}>
                                    {isUp ? '▲' : '▼'}{' '}
                                    {Math.abs(idx.changePct).toFixed(2)}%
                                </span>
                            </div>
                        );
                    })}
                </div>
            </div>
            {lastUpdate && (
                <div className="ticker-updated" title={`Last update: ${lastUpdate}`}>
                    {lastUpdate}
                </div>
            )}
        </div>
    );
};

export default MarketTicker;
