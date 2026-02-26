import React from 'react';
import type { RiskLevel } from '../../types/events';

interface DefconIndicatorProps {
    risk: RiskLevel | null;
    totalEvents: number;
    connected: boolean;
}

const DefconIndicator: React.FC<DefconIndicatorProps> = ({ risk, totalEvents, connected }) => {
    const level = risk?.level ?? 1;
    const label = risk?.label ?? 'NOMINAL';
    const color = risk?.color ?? '#00ff88';

    return (
        <div className="defcon-indicator">
            <div className="defcon-status-bar">
                <div className={`connection-dot ${connected ? 'online' : 'offline'}`}></div>
                <span className="connection-label">
                    {connected ? 'LIVE' : 'OFFLINE'}
                </span>
            </div>

            <div className="defcon-badge" style={{ borderColor: color, boxShadow: `0 0 20px ${color}40` }}>
                <div className="defcon-level" style={{ color }}>
                    {level}
                </div>
                <div className="defcon-label" style={{ color }}>
                    {label}
                </div>
            </div>

            <div className="defcon-scale">
                {[1, 2, 3, 4, 5].map((l) => (
                    <div
                        key={l}
                        className={`scale-segment ${l <= level ? 'active' : ''}`}
                        style={{
                            backgroundColor: l <= level ? color : '#1a1f2e',
                            opacity: l <= level ? 1 : 0.3,
                        }}
                    ></div>
                ))}
            </div>

            <div className="defcon-stats">
                <div className="stat-item">
                    <span className="stat-value">{totalEvents}</span>
                    <span className="stat-label">EVENTS</span>
                </div>
                {risk?.score !== undefined && (
                    <div className="stat-item">
                        <span className="stat-value">{risk.score}</span>
                        <span className="stat-label">THREAT</span>
                    </div>
                )}
            </div>
        </div>
    );
};

export default DefconIndicator;
