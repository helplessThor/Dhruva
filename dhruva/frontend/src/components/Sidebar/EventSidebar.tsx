import React from 'react';
import type { OsintEvent } from '../../types/events';
import { SEVERITY_COLORS } from '../../types/events';

interface EventSidebarProps {
    event: OsintEvent | null;
    onClose: () => void;
}

const EventSidebar: React.FC<EventSidebarProps> = ({ event, onClose }) => {
    if (!event) return null;

    const severityColor = SEVERITY_COLORS[event.severity] || '#44ccff';
    const severityLabels = ['', 'LOW', 'MODERATE', 'HIGH', 'CRITICAL', 'CATASTROPHIC'];
    const isAircraft = event.type === 'aircraft';
    const meta = event.metadata || {};

    return (
        <div className="event-sidebar">
            <div className="sidebar-header">
                <h3 className="sidebar-title">{event.title}</h3>
                <button className="sidebar-close" onClick={onClose}>✕</button>
            </div>

            <div className="sidebar-content">
                <div className="sidebar-severity" style={{ borderColor: severityColor }}>
                    <span className="severity-dot" style={{ backgroundColor: severityColor }}></span>
                    <span className="severity-label" style={{ color: severityColor }}>
                        {severityLabels[event.severity]}
                    </span>
                </div>

                {/* ── Aircraft Route Card ── */}
                {isAircraft && meta.origin && meta.origin !== '—' && (
                    <div className="flight-route-card">
                        <div className="route-header">
                            <span className="route-airline">{meta.airline || 'Unknown Airline'}</span>
                            <span className="route-callsign">{meta.callsign}</span>
                        </div>
                        <div className="route-visual">
                            <div className="route-airport">
                                <span className="airport-code">{meta.origin}</span>
                                <span className="airport-label">ORIGIN</span>
                            </div>
                            <div className="route-line">
                                <div className="route-line-track" />
                                <span className="route-plane-icon">✈</span>
                            </div>
                            <div className="route-airport">
                                <span className="airport-code">{meta.destination}</span>
                                <span className="airport-label">DEST</span>
                            </div>
                        </div>
                        {meta.altitude_ft != null && (
                            <div className="flight-stats">
                                <div className="flight-stat">
                                    <span className="flight-stat-value">
                                        {meta.altitude_ft > 18000
                                            ? `FL${Math.floor(meta.altitude_ft / 100).toString().padStart(3, '0')}`
                                            : `${meta.altitude_ft.toLocaleString()}ft`
                                        }
                                    </span>
                                    <span className="flight-stat-label">ALT</span>
                                </div>
                                <div className="flight-stat">
                                    <span className="flight-stat-value">{meta.speed_knots}kts</span>
                                    <span className="flight-stat-label">GS</span>
                                </div>
                                <div className="flight-stat">
                                    <span className="flight-stat-value">{meta.heading?.toFixed(0)}°</span>
                                    <span className="flight-stat-label">HDG</span>
                                </div>
                                {meta.vertical_rate_fpm != null && meta.vertical_rate_fpm !== 0 && (
                                    <div className="flight-stat">
                                        <span className="flight-stat-value">
                                            {meta.vertical_rate_fpm > 0 ? '↑' : '↓'}
                                            {Math.abs(meta.vertical_rate_fpm).toFixed(0)}
                                        </span>
                                        <span className="flight-stat-label">FPM</span>
                                    </div>
                                )}
                            </div>
                        )}
                        {meta.squawk && (
                            <div className={`squawk-tag ${['7500', '7600', '7700'].includes(meta.squawk) ? 'squawk-emergency' : ''}`}>
                                SQUAWK {meta.squawk}
                            </div>
                        )}
                    </div>
                )}

                <div className="sidebar-meta">
                    <div className="meta-row">
                        <span className="meta-label">Type</span>
                        <span className="meta-value">{event.type.toUpperCase()}</span>
                    </div>
                    <div className="meta-row">
                        <span className="meta-label">Source</span>
                        <span className="meta-value">{event.source}</span>
                    </div>
                    <div className="meta-row">
                        <span className="meta-label">Coordinates</span>
                        <span className="meta-value">
                            {event.latitude.toFixed(4)}°, {event.longitude.toFixed(4)}°
                        </span>
                    </div>
                    <div className="meta-row">
                        <span className="meta-label">Time</span>
                        <span className="meta-value">
                            {new Date(event.timestamp).toLocaleString()}
                        </span>
                    </div>
                    {isAircraft && meta.icao24 && (
                        <div className="meta-row">
                            <span className="meta-label">ICAO24</span>
                            <span className="meta-value">{meta.icao24.toUpperCase()}</span>
                        </div>
                    )}
                    {isAircraft && meta.origin_country && (
                        <div className="meta-row">
                            <span className="meta-label">Registry</span>
                            <span className="meta-value">{meta.origin_country}</span>
                        </div>
                    )}
                </div>

                <p className="sidebar-description">{event.description}</p>

                {/* Generic metadata for non-aircraft events */}
                {!isAircraft && Object.keys(meta).length > 0 && (
                    <div className="sidebar-metadata">
                        <h4>Intelligence Data</h4>
                        {Object.entries(meta).map(([key, value]) => (
                            value != null && (
                                <div className="meta-row" key={key}>
                                    <span className="meta-label">{key.replace(/_/g, ' ')}</span>
                                    <span className="meta-value">
                                        {typeof value === 'number' ? value.toLocaleString() : String(value)}
                                    </span>
                                </div>
                            )
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};

export default EventSidebar;
