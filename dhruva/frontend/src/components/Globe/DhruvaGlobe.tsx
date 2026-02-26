import React, { useMemo, useEffect } from 'react';
import {
    Viewer,
    Entity,
    BillboardGraphics,
    useCesium,
} from 'resium';
import {
    Cartesian3,
    NearFarScalar,
    VerticalOrigin,
    UrlTemplateImageryProvider,
} from 'cesium';
import type { OsintEvent, EventType } from '../../types/events';
import { SEVERITY_COLORS, LAYER_CONFIGS } from '../../types/events';
import LayerIcon from '../shared/LayerIcon';

interface DhruvaGlobeProps {
    events: Record<string, OsintEvent[]>;
    enabledLayers: Set<EventType>;
    onEventSelect: (event: OsintEvent) => void;
}

/* ═══════════════════════════════════════════════════════════════════
   Professional SVG Marker System
   - Each type has a unique COLOR + SHAPE for instant recognition
   - Severity controls glow intensity and marker size
   - White symbol on colored halo background
   ═══════════════════════════════════════════════════════════════════ */

/** Each event type: unique halo color + clean SVG symbol path */
const MARKER_DEFS: Record<EventType, { color: string; symbol: string; filled: boolean }> = {
    earthquake: {
        color: '#ff6600',
        symbol: '<circle cx="16" cy="16" r="4" fill="#fff"/><circle cx="16" cy="16" r="8" fill="none" stroke="#fff" stroke-width="1.5" opacity="0.8"/><circle cx="16" cy="16" r="12" fill="none" stroke="#fff" stroke-width="1.2" opacity="0.5"/>',
        filled: false,
    },
    fire: {
        color: '#ff2d20',
        symbol: '<path d="M16 5C16 5 10 12 10 18c0 3.3 2.7 6 6 6s6-2.7 6-6C22 12 16 5 16 5z" fill="#fff"/>',
        filled: true,
    },
    conflict: {
        color: '#ff0055',
        symbol: '<circle cx="16" cy="16" r="6" fill="none" stroke="#fff" stroke-width="1.8"/><circle cx="16" cy="16" r="2" fill="#fff"/><line x1="16" y1="4" x2="16" y2="10" stroke="#fff" stroke-width="1.8"/><line x1="16" y1="22" x2="16" y2="28" stroke="#fff" stroke-width="1.8"/><line x1="4" y1="16" x2="10" y2="16" stroke="#fff" stroke-width="1.8"/><line x1="22" y1="16" x2="28" y2="16" stroke="#fff" stroke-width="1.8"/>',
        filled: false,
    },
    aircraft: {
        color: '#00bfff',
        symbol: '<path d="M16 4 L18 13 L27 16 L18 18 L19 26 L16 24 L13 26 L14 18 L5 16 L14 13 Z" fill="#fff"/>',
        filled: true,
    },
    marine: {
        color: '#00aaff',
        symbol: '<circle cx="16" cy="9" r="3" fill="none" stroke="#fff" stroke-width="1.8"/><line x1="16" y1="12" x2="16" y2="25" stroke="#fff" stroke-width="1.8"/><path d="M10 22 C10 26 16 28 16 28 C16 28 22 26 22 22" fill="none" stroke="#fff" stroke-width="1.8"/><line x1="12" y1="16" x2="20" y2="16" stroke="#fff" stroke-width="1.8"/>',
        filled: false,
    },
    cyber: {
        color: '#9333ea',
        symbol: '<path d="M16 4 L26 9 L26 17 C26 23 21 27 16 29 C11 27 6 23 6 17 L6 9 Z" fill="none" stroke="#fff" stroke-width="1.6"/><rect x="13" y="15" width="6" height="5" rx="1" fill="#fff"/><path d="M14 15 V13 C14 11 18 11 18 13 V15" fill="none" stroke="#fff" stroke-width="1.5"/>',
        filled: false,
    },
    outage: {
        color: '#f59e0b',
        symbol: '<path d="M18 4 L10 17 L15 17 L14 28 L22 15 L17 15 Z" fill="#fff"/>',
        filled: true,
    },
    economic: {
        color: '#10b981',
        symbol: '<polyline points="6,24 12,16 18,20 26,8" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><polyline points="22,8 26,8 26,12" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
        filled: false,
    },
    military: {
        color: '#4ade80',
        symbol: '<path d="M16 3 L24 8 L24 18 C24 23 20 27 16 29 C12 27 8 23 8 18 L8 8 Z" fill="none" stroke="#fff" stroke-width="1.6"/><line x1="16" y1="11" x2="16" y2="21" stroke="#fff" stroke-width="1.5"/><line x1="11" y1="16" x2="21" y2="16" stroke="#fff" stroke-width="1.5"/>',
        filled: false,
    },
    military_aircraft: {
        color: '#a3e635',
        // Delta-wing fighter jet: swept wings, pointed fuselage, tail fins
        symbol: '<line x1="16" y1="4" x2="16" y2="26" stroke="#fff" stroke-width="2.5" stroke-linecap="round"/><path d="M16 8 L3 23 L10 20 L16 26 L22 20 L29 23 Z" fill="#fff" opacity="0.9"/><path d="M16 11 L11 15 L14 14 L16 16 L18 14 L21 15 Z" fill="#fff"/><line x1="13" y1="22" x2="10" y2="28" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><line x1="19" y1="22" x2="22" y2="28" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/>',
        filled: true,
    },

    ucdp: {
        color: '#e11d48',
        symbol: '<polygon points="16,4 19,12 28,12 21,18 23,26 16,22 9,26 11,18 4,12 13,12" fill="#fff" fill-opacity="0.9"/>',
        filled: true,
    },
    acled: {
        color: '#f97316',
        symbol: '<circle cx="16" cy="16" r="7" fill="none" stroke="#fff" stroke-width="1.6"/><circle cx="16" cy="16" r="3" fill="none" stroke="#fff" stroke-width="1.2"/><circle cx="16" cy="16" r="1.5" fill="#fff"/><line x1="16" y1="5" x2="16" y2="9" stroke="#fff" stroke-width="1.3"/><line x1="16" y1="23" x2="16" y2="27" stroke="#fff" stroke-width="1.3"/>',
        filled: false,
    },
    intel_hotspot: {
        color: '#fbbf24',
        symbol: '<path d="M16 6 L19 13 L26 13 L20 18 L22 25 L16 21 L10 25 L12 18 L6 13 L13 13 Z" fill="#fff" fill-opacity="0.85"/><circle cx="16" cy="16" r="13" fill="none" stroke="#fff" stroke-width="1" opacity="0.4"/><circle cx="16" cy="16" r="10" fill="none" stroke="#fff" stroke-width="0.8" opacity="0.6"/>',
        filled: false,
    },
};

/** Severity → glow strength (opacity multiplier for the halo) */
const SEVERITY_GLOW: Record<number, number> = {
    1: 0.50,
    2: 0.45,
    3: 0.55,
    4: 0.70,
    5: 0.90,
};

/** Builds a professional marker SVG: colored halo + white symbol */
function buildMarkerSvg(type: EventType, severity: number): string {
    const def = MARKER_DEFS[type];
    const size = 40 + severity * 4; // 44–60px
    const glow = SEVERITY_GLOW[severity] || 0.4;
    const sevColor = SEVERITY_COLORS[severity] || def.color;
    const gradId = `h-${type}-${severity}`;

    const svg = [
        `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 32 32">`,
        `<defs><radialGradient id="${gradId}">`,
        `<stop offset="0%" stop-color="${def.color}" stop-opacity="${glow}"/>`,
        `<stop offset="60%" stop-color="${def.color}" stop-opacity="${(glow * 0.4).toFixed(2)}"/>`,
        `<stop offset="100%" stop-color="${def.color}" stop-opacity="0"/>`,
        `</radialGradient></defs>`,
        `<circle cx="16" cy="16" r="15" fill="url(#${gradId})"/>`,
        `<circle cx="16" cy="16" r="11" fill="${def.color}" fill-opacity="0.25" stroke="${sevColor}" stroke-width="1" stroke-opacity="0.6"/>`,
        def.symbol,
        `</svg>`,
    ].join('');

    return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

/** Cache marker images */
const markerCache = new Map<string, string>();

function getMarkerImage(type: EventType, severity: number): string {
    const key = `${type}-${severity}`;
    if (!markerCache.has(key)) {
        markerCache.set(key, buildMarkerSvg(type, severity));
    }
    return markerCache.get(key)!;
}

/* ── Dark basemap ───────────────────────────────────────────────── */

const DarkBasemap: React.FC = () => {
    const { viewer } = useCesium();

    useEffect(() => {
        if (!viewer) return;
        viewer.imageryLayers.removeAll();
        const provider = new UrlTemplateImageryProvider({
            url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
            subdomains: ['a', 'b', 'c', 'd'],
            minimumLevel: 0,
            maximumLevel: 18,
            credit: '© CartoDB © OpenStreetMap contributors',
        });
        viewer.imageryLayers.addImageryProvider(provider);
    }, [viewer]);

    return null;
};

/* ── Professional Legend overlay ─────────────────────────────────── */

const GlobeLegend: React.FC<{ enabledLayers: Set<EventType> }> = ({ enabledLayers }) => {
    const activeLayers = LAYER_CONFIGS.filter(l => enabledLayers.has(l.id));

    const SEVERITY_LABELS = ['Low', 'Moderate', 'High', 'Critical', 'Catastrophic'];

    return (
        <div className="globe-legend">
            <div className="legend-section">
                <div className="legend-title">ACTIVE LAYERS</div>
                {activeLayers.map(layer => {
                    const def = MARKER_DEFS[layer.id];
                    return (
                        <div key={layer.id} className="legend-item">
                            <div
                                className="legend-icon-wrap"
                                style={{
                                    borderColor: `${def.color}66`,
                                    background: `${def.color}18`,
                                }}
                            >
                                <LayerIcon type={layer.id} color={def.color} size={14} />
                            </div>
                            <span className="legend-label">{layer.label}</span>
                            <span
                                className="legend-dot-indicator"
                                style={{
                                    background: def.color,
                                    boxShadow: `0 0 5px ${def.color}`,
                                }}
                            />
                        </div>
                    );
                })}
            </div>
            <div className="legend-divider" />
            <div className="legend-section">
                <div className="legend-title">THREAT LEVEL</div>
                <div className="severity-gradient-bar">
                    <div className="severity-track">
                        {[1, 2, 3, 4, 5].map(level => (
                            <div
                                key={level}
                                className="severity-segment"
                                style={{
                                    background: SEVERITY_COLORS[level],
                                }}
                            />
                        ))}
                    </div>
                    <div className="severity-labels">
                        <span>{SEVERITY_LABELS[0]}</span>
                        <span>{SEVERITY_LABELS[2]}</span>
                        <span>{SEVERITY_LABELS[4]}</span>
                    </div>
                </div>
            </div>
        </div>
    );
};

/* ── Main globe component ───────────────────────────────────────── */

const DhruvaGlobe: React.FC<DhruvaGlobeProps> = ({ events, enabledLayers, onEventSelect }) => {
    const flatEvents = useMemo(() => {
        const result: OsintEvent[] = [];
        for (const [type, layerEvents] of Object.entries(events)) {
            if (enabledLayers.has(type as EventType)) {
                result.push(...layerEvents);
            }
        }
        return result;
    }, [events, enabledLayers]);

    return (
        <div style={{ position: 'relative', width: '100%', height: '100%' }}>
            <Viewer
                full
                animation={false}
                baseLayerPicker={false}
                fullscreenButton={false}
                geocoder={false}
                homeButton={false}
                infoBox={false}
                sceneModePicker={false}
                selectionIndicator={false}
                timeline={false}
                navigationHelpButton={false}
                scene3DOnly={true}
                className="dhruva-globe"
            >
                <DarkBasemap />

                {flatEvents.map((event) => {
                    // For aircraft and military_aircraft, rotate icon to match heading
                    const headingDeg = (event.type === 'aircraft' || event.type === 'military_aircraft')
                        ? (event.metadata?.heading ?? 0)
                        : 0;
                    const rotation = (event.type === 'aircraft' || event.type === 'military_aircraft')
                        ? -headingDeg * (Math.PI / 180)
                        : 0;

                    return (
                        <Entity
                            key={event.id}
                            position={Cartesian3.fromDegrees(event.longitude, event.latitude)}
                            name={event.title}
                            description={event.description}
                            onClick={() => onEventSelect(event)}
                        >
                            <BillboardGraphics
                                image={getMarkerImage(event.type, event.severity)}
                                verticalOrigin={VerticalOrigin.CENTER}
                                scaleByDistance={new NearFarScalar(1.5e2, 2.0, 1.5e7, 0.5)}
                                rotation={rotation}
                                alignedAxis={Cartesian3.ZERO}
                            />
                        </Entity>
                    );
                })}
            </Viewer>

            <GlobeLegend enabledLayers={enabledLayers} />
        </div>
    );
};

export default DhruvaGlobe;
