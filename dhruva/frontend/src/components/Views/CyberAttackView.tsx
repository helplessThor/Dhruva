import React, { useMemo } from 'react';
import type { OsintEvent } from '../../types/events';
import { SEVERITY_COLORS } from '../../types/events';

interface CyberAttackViewProps {
    events: OsintEvent[];
    onClose: () => void;
}

const CyberAttackView: React.FC<CyberAttackViewProps> = ({ events, onClose }) => {
    const cyberEvents = useMemo(
        () => events.filter(e => e.type === 'cyber'),
        [events]
    );

    return (
        <div className="overlay-view cyber-view">
            <div className="overlay-header">
                <h2>💻 CYBER THREAT VISUALIZATION</h2>
                <span className="overlay-count">{cyberEvents.length} active threats</span>
                <button className="overlay-close" onClick={onClose}>✕ CLOSE</button>
            </div>
            <div className="overlay-grid">
                {cyberEvents.map(event => {
                    const color = SEVERITY_COLORS[event.severity];
                    return (
                        <div key={event.id} className="overlay-card cyber-card" style={{ borderColor: color }}>
                            <div className="card-header">
                                <span className="card-callsign" style={{ color }}>
                                    {event.metadata.attack_type}
                                </span>
                                <span
                                    className="card-severity-badge"
                                    style={{ backgroundColor: color }}
                                >
                                    SEV-{event.severity}
                                </span>
                            </div>
                            <div className="card-body">
                                <div className="card-row">
                                    <span>Target</span>
                                    <span>{event.metadata.target}</span>
                                </div>
                                <div className="card-row">
                                    <span>Origin</span>
                                    <span>{event.metadata.origin}</span>
                                </div>
                                {event.metadata.packets_per_sec && (
                                    <div className="card-row">
                                        <span>Volume</span>
                                        <span>{event.metadata.packets_per_sec.toLocaleString()} pps</span>
                                    </div>
                                )}
                                <div className="card-row">
                                    <span>Time</span>
                                    <span>{new Date(event.timestamp).toLocaleTimeString()}</span>
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export default CyberAttackView;
