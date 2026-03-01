import { useMemo } from 'react';
import type { OsintEvent } from '../../types/events';
import './LiveNewsTicker.css';

interface LiveNewsTickerProps {
    events: OsintEvent[];
}

/**
 * Maps an internal event type to a UI-friendly label and color class.
 */
const getSourceFormat = (type: string): { label: string; className: string } => {
    switch (type) {
        case 'news':
            return { label: 'GLOBAL NEWS', className: 'source-intel' };
        default:
            return { label: 'ALERT', className: 'source-intel' };
    }
};

/**
 * LiveNewsTicker component displays a pulsating "LIVE" badge alongside an animated
 * scrolling marquee of the most recent, high-priority global events.
 */
const LiveNewsTicker = ({ events }: LiveNewsTickerProps) => {
    const tickerItems = useMemo(() => {
        if (!events || events.length === 0) return [];

        // The backend now provides a dedicated 'news' layer with 
        // exactly 10 deduplicated headlines via RSS parsing.
        return events.filter(e => e.type === 'news');
    }, [events]);

    if (tickerItems.length === 0) {
        return (
            <div className="live-news-ticker-container">
                <div className="ticker-badge">
                    <div className="pulse-dot"></div>
                    LIVE
                </div>
                <div className="ticker-track">
                    <div className="ticker-content" style={{ animation: 'none', paddingLeft: '16px' }}>
                        <span style={{ color: '#555' }}>Awaiting incoming intelligence signals...</span>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="live-news-ticker-container">
            <div className="ticker-badge">
                <div className="pulse-dot"></div>
                LIVE
            </div>
            <div className="ticker-track">
                {/* We render the content twice to create a seamless infinite loop effect if needed, 
            but a single long span with linear 100% translation is standard */}
                <div className="ticker-content">
                    {tickerItems.map((item, index) => {
                        const timeStr = new Date(item.timestamp).toLocaleTimeString([], {
                            hour: '2-digit',
                            minute: '2-digit',
                            hour12: false
                        });
                        const fmt = getSourceFormat(item.type);

                        return (
                            <div key={`${item.id}-${index}`} className="ticker-item">
                                <span className="item-time">[{timeStr}z]</span>
                                <span className={`item-source ${fmt.className}`}>{item.source || fmt.label}</span>
                                <span className="item-title">{item.title}</span>
                                {index < tickerItems.length - 1 && (
                                    <span className="item-separator">///</span>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
};

export default LiveNewsTicker;
