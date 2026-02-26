import React, { useMemo } from 'react';
import type { OsintEvent } from '../../types/events';
import { SEVERITY_COLORS } from '../../types/events';

interface AirTrafficViewProps {
    events: OsintEvent[];
    onClose: () => void;
}

const AirTrafficView: React.FC<AirTrafficViewProps> = ({ events, onClose }) => {
    const aircraftEvents = useMemo(
        () => events.filter(e => e.type === 'aircraft'),
        [events]
    );

    return (
        <div className="overlay-view">
            <div className="overlay-header">
                <h2>✈️ GLOBAL AIR TRAFFIC</h2>
                <span className="overlay-count">{aircraftEvents.length} aircraft tracked</span>
                <button className="overlay-close" onClick={onClose}>✕ CLOSE</button>
            </div>
            <div className="overlay-grid">
                {aircraftEvents.map(event => (
                    <div key={event.id} className="overlay-card">
                        <div className="card-header">
                            <span className="card-callsign">{event.title}</span>
                            <span className="card-source">{event.metadata.origin_country}</span>
                        </div>
                        <div className="card-body">
                            <div className="card-row">
                                <span>Altitude</span>
                                <span>{event.metadata.altitude_m?.toLocaleString() || '—'} m</span>
                            </div>
                            <div className="card-row">
                                <span>Speed</span>
                                <span>{event.metadata.velocity_ms || '—'} m/s</span>
                            </div>
                            <div className="card-row">
                                <span>Position</span>
                                <span>{event.latitude.toFixed(2)}°, {event.longitude.toFixed(2)}°</span>
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default AirTrafficView;
