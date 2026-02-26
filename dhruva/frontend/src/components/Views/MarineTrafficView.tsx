import React, { useMemo } from 'react';
import type { OsintEvent } from '../../types/events';

interface MarineTrafficViewProps {
    events: OsintEvent[];
    onClose: () => void;
}

const MarineTrafficView: React.FC<MarineTrafficViewProps> = ({ events, onClose }) => {
    const marineEvents = useMemo(
        () => events.filter(e => e.type === 'marine'),
        [events]
    );

    return (
        <div className="overlay-view">
            <div className="overlay-header">
                <h2>🚢 GLOBAL MARINE TRAFFIC</h2>
                <span className="overlay-count">{marineEvents.length} vessels tracked</span>
                <button className="overlay-close" onClick={onClose}>✕ CLOSE</button>
            </div>
            <div className="overlay-grid">
                {marineEvents.map(event => (
                    <div key={event.id} className="overlay-card marine-card">
                        <div className="card-header">
                            <span className="card-callsign">{event.title}</span>
                            <span className="card-source">{event.metadata.vessel_type}</span>
                        </div>
                        <div className="card-body">
                            <div className="card-row">
                                <span>Speed</span>
                                <span>{event.metadata.speed_knots} knots</span>
                            </div>
                            <div className="card-row">
                                <span>Heading</span>
                                <span>{event.metadata.heading}°</span>
                            </div>
                            <div className="card-row">
                                <span>MMSI</span>
                                <span>{event.metadata.mmsi}</span>
                            </div>
                            <div className="card-row">
                                <span>Lane</span>
                                <span>{event.metadata.lane}</span>
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default MarineTrafficView;
