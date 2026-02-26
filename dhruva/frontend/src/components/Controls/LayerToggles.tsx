import React from 'react';
import type { EventType, LayerConfig } from '../../types/events';
import { LAYER_CONFIGS } from '../../types/events';
import LayerIcon from '../shared/LayerIcon';

interface LayerTogglesProps {
    enabledLayers: Set<EventType>;
    eventCounts: Record<string, number>;
    onToggle: (layerId: EventType) => void;
}

const LayerToggles: React.FC<LayerTogglesProps> = ({ enabledLayers, eventCounts, onToggle }) => {
    return (
        <div className="layer-toggles">
            <div className="panel-header">
                <span className="panel-icon">◈</span>
                <h3>DATA LAYERS</h3>
            </div>
            <div className="toggle-list">
                {LAYER_CONFIGS.map((layer) => {
                    const enabled = enabledLayers.has(layer.id);
                    const count = eventCounts[layer.id] || 0;

                    return (
                        <div
                            key={layer.id}
                            className={`toggle-item ${enabled ? 'active' : ''}`}
                            onClick={() => onToggle(layer.id)}
                        >
                            <div className="toggle-switch">
                                <div className={`switch-track ${enabled ? 'on' : ''}`}>
                                    <div className="switch-thumb"></div>
                                </div>
                            </div>
                            <LayerIcon
                                type={layer.id}
                                color={enabled ? layer.color : '#555'}
                                size={16}
                                className="toggle-icon-svg"
                            />
                            <span className="toggle-label">{layer.label}</span>
                            <span className="toggle-count" style={{ color: enabled ? layer.color : '#555' }}>
                                {count}
                            </span>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export default LayerToggles;
