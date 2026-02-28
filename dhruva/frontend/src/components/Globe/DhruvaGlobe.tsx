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
const MARKER_DEFS: Record<EventType, { color: string; symbol: string; scale: number }> = {
    earthquake: {
        color: '#ff6600',
        symbol: '<path d="M2 8h3l2-4 2 8 2-4h3" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /><circle cx="8" cy="8" r="7" fill="none" stroke="#fff" stroke-width="1" opacity="0.4" />',
        scale: 1,
    },
    fire: {
        color: '#ff2d20',
        symbol: '<path d="M8.5 2c0 0-3.5 1.5-3.5 4.5 0 2 1 3.5 1 3.5s.5-1.5 1-2.5c0 0 4.5 1 4.5 5 0 2-1.5 3.5-3.5 3.5-2.5 0-4.5-2-4.5-4.5 0-2 1-3.5 1.5-4-.5.5-1 1.5-1 3 0 0-2 1.5-2 3.5C2 13.5 4.5 16 8 16s6-2.5 6-6c0-4-3-6-5.5-8z" fill="#fff" opacity="0.9" />',
        scale: 1.1,
    },

    aircraft: {
        color: '#00bfff',
        symbol: '<path d="M13.5 8c0-.8-.7-1.5-1.5-1.5H9L6 2H4.5l1.5 4.5H3L2 5H1l1 3-1 3h1l1-1.5h3L4.5 14H6l3-4.5h3c.8 0 1.5-.7 1.5-1.5z" fill="#fff" />',
        scale: 1.2,
    },
    marine: {
        color: '#00aaff',
        symbol: '<path d="M2 10l1-5h8l2 5z" fill="#fff" opacity="0.8" /><path d="M4 5V3h4v2" fill="none" stroke="#fff" stroke-width="1.5" /><path d="M1 12c2 1 4-1 6 0s4 1 6 0 2-1 2-1" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" />',
        scale: 1.1,
    },
    cyber: {
        color: '#9333ea',
        symbol: '<path d="M8 1.5l5 2v4c0 4-5 6.5-5 6.5S3 11.5 3 7.5v-4z" fill="none" stroke="#fff" stroke-width="1.5" /><path d="M6 7l1.5 2L10.5 5.5" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />',
        scale: 1,
    },
    outage: {
        color: '#f59e0b',
        symbol: '<path d="M8 2v4M8 10v4M6 6h4v4H6z" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /><path d="M3 8l3-3m4 0l3 3" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" opacity="0.6" />',
        scale: 1,
    },
    economic: {
        color: '#10b981',
        symbol: '<path d="M2 13h12" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" /><path d="M3 10l3-3 2 2 4-4" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /><path d="M9 5h3v3" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />',
        scale: 1.1,
    },
    military: {
        color: '#4ade80',
        symbol: '<circle cx="8" cy="8" r="6" fill="none" stroke="#fff" stroke-width="1.5" /><circle cx="8" cy="8" r="2" fill="#fff" /><path d="M8 1v2M8 13v2M1 8h2M13 8h2" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" />',
        scale: 1.1,
    },
    military_aircraft: {
        color: '#a3e635',
        symbol: '<path d="M8 1l1.5 4h-3zM8 4l4 6v2h-2L8 10l-2 2H4v-2z" fill="#fff" stroke="#fff" stroke-width="1" stroke-linejoin="round" />',
        scale: 1.2,
    },
    ucdp: {
        color: '#e11d48',
        symbol: '<path d="M8 2l6.5 11H1.5z" fill="none" stroke="#fff" stroke-width="1.5" stroke-linejoin="round" /><path d="M8 6v3M8 11.5v.5" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" />',
        scale: 1,
    },
    acled: {
        color: '#f97316',
        symbol: '<path d="M8 1C5.5 1 3.5 3 3.5 5.5c0 3 4.5 9.5 4.5 9.5s4.5-6.5 4.5-9.5C12.5 3 10.5 1 8 1z" fill="none" stroke="#fff" stroke-width="1.5" stroke-linejoin="round" /><circle cx="8" cy="5.5" r="2" fill="#fff" />',
        scale: 1.1,
    },
    acled_cast: {
        color: '#fbbf24',
        symbol: '<path d="M8 1C5.5 1 3.5 3 3.5 5.5c0 3 4.5 9.5 4.5 9.5s4.5-6.5 4.5-9.5C12.5 3 10.5 1 8 1z" fill="none" stroke="#fff" stroke-width="1.5" stroke-linejoin="round" /><circle cx="8" cy="5.5" r="2" fill="#fff" />',
        scale: 1.1,
    },
    naval: {
        color: '#3b82f6',
        symbol: '<path d="M2 10l1-5h8l2 5z" fill="#fff" opacity="0.8" /><path d="M4 5V3h4v2" fill="none" stroke="#fff" stroke-width="1.5" /><path d="M1 12c2 1 4-1 6 0s4 1 6 0 2-1 2-1" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" />',
        scale: 1.1,
    },
    military_marine: {
        color: '#3b82f6',
        symbol: '<path d="M2 10l1-5h8l2 5z" fill="#fff" opacity="0.8" /><path d="M4 5V3h4v2" fill="none" stroke="#fff" stroke-width="1.5" /><path d="M1 12c2 1 4-1 6 0s4 1 6 0 2-1 2-1" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" />',
        scale: 1.1,
    },
    intel_hotspot: {
        color: '#fbbf24',
        symbol: '<path d="M2 8c0 0 3-4 6-4s6 4 6 4-3 4-6 4-6-4-6-4z" fill="none" stroke="#fff" stroke-width="1.5" stroke-linejoin="round" /><circle cx="8" cy="8" r="2.5" fill="#fff" /><path d="M8 2v1M8 13v1M2 8H1M15 8h-1" fill="none" stroke="#fff" stroke-width="1.5" opacity="0.4" stroke-linecap="round" />',
        scale: 1,
    },
    convergence: {
        color: '#dc2626',
        symbol: '<path d="M8 1.5v3M8 11.5v3M1.5 8h3M11.5 8h3M4 4l1.5 1.5M12 12l-1.5-1.5M12 4L10.5 5.5M4 12l1.5-1.5" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" /><circle cx="8" cy="8" r="2" fill="#fff" />',
        scale: 1.2,
    },
    satellite: {
        color: '#cbd5e1',
        symbol: '<ellipse cx="8" cy="8" rx="6" ry="2" fill="none" stroke="#fff" stroke-width="1.5" transform="rotate(-30 8 8)" /><circle cx="8" cy="8" r="3" fill="#fff" />',
        scale: 1.1,
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

/** Builds a premium professional marker SVG: 3D Jewel + glassmorphic surface + sharp vector symbol */
function buildMarkerSvg(type: EventType, severity: number): string {
    const def = MARKER_DEFS[type];
    // Base size config for crisp SVG rendering at scale
    // Cesium Billboard scaleByDistance handles zooming/scaling down
    const size = 64;
    const baseGlow = SEVERITY_GLOW[severity] || 0.4;
    // Boost glow slightly for the new premium aesthetic
    const glow = Math.min(0.95, baseGlow * 1.3);
    const sevColor = SEVERITY_COLORS[severity] || def.color;

    // Unique IDs for SVG defs to prevent cross-bleeding
    const haloId = `halo-${type}-${severity}`;
    const glassId = `glass-${type}-${severity}`;
    const ringId = `ring-${type}-${severity}`;

    // Scale the 16x16 icon path up to fit nicely inside the glowing halo
    const symbolScale = Math.max(1.8, def.scale * 2.2);
    const symbolOffset = 32 - (8 * symbolScale);

    const svg = [
        `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">`,
        `<defs>`,
        // 1. Glowing Halo behind the marker
        `<radialGradient id="${haloId}">`,
        `<stop offset="0%" stop-color="${def.color}" stop-opacity="${glow}"/>`,
        `<stop offset="40%" stop-color="${def.color}" stop-opacity="${(glow * 0.5).toFixed(2)}"/>`,
        `<stop offset="100%" stop-color="${def.color}" stop-opacity="0"/>`,
        `</radialGradient>`,

        // 2. Glassmorphic / 3D Jewel Body Gradient (Diagonal lighting)
        `<linearGradient id="${glassId}" x1="0%" y1="0%" x2="100%" y2="100%">`,
        `<stop offset="0%" stop-color="${def.color}" stop-opacity="0.9"/>`,
        `<stop offset="50%" stop-color="${def.color}" stop-opacity="0.6"/>`,
        `<stop offset="100%" stop-color="#000000" stop-opacity="0.6"/>`,
        `</linearGradient>`,

        // 3. Crisp Metallic/Neon Edge Ring (Simulates light catching the rim)
        `<linearGradient id="${ringId}" x1="0%" y1="0%" x2="0%" y2="100%">`,
        `<stop offset="0%" stop-color="#ffffff" stop-opacity="0.95"/>`,
        `<stop offset="100%" stop-color="${sevColor}" stop-opacity="0.4"/>`,
        `</linearGradient>`,
        `</defs>`,

        // Render large blurred halo
        `<circle cx="32" cy="32" r="30" fill="url(#${haloId})"/>`,

        // Render 3D Jewel Surface with Metallic Stroke
        `<circle cx="32" cy="32" r="18" fill="url(#${glassId})" stroke="url(#${ringId})" stroke-width="1.5"/>`,

        // Add Top Gloss Rays (Apple-style 3D specular shine)
        `<ellipse cx="32" cy="20" rx="12" ry="5" fill="#ffffff" fill-opacity="0.25"/>`,
        `<ellipse cx="32" cy="17" rx="6" ry="2" fill="#ffffff" fill-opacity="0.4"/>`,

        // Render Symbol
        `<g transform="translate(${symbolOffset}, ${symbolOffset}) scale(${symbolScale})">`,
        def.symbol,
        `</g>`,
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
        const seenIds = new Set<string>();
        const result: OsintEvent[] = [];

        for (const [type, layerEvents] of Object.entries(events)) {
            if (enabledLayers.has(type as EventType)) {
                for (const event of layerEvents) {
                    if (!seenIds.has(event.id)) {
                        seenIds.add(event.id);
                        result.push(event);
                    }
                }
            }
        }

        // Debugging trace for zero-render issues
        console.log(`[DhruvaGlobe] Render cycle: ${result.length} flat events derived from active layers.`);
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
                    // For vehicles with headings, rotate icon to match compass direction.
                    // Note: CesiumJS billboards rotate clockwise in radians natively.
                    const hasHeading = ["aircraft", "military_aircraft", "marine", "military_marine"].includes(event.type);
                    const headingDeg = hasHeading ? (event.metadata?.heading ?? 0) : 0;
                    const rotationObj = hasHeading ? headingDeg * (Math.PI / 180) : 0;

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
                                // A base scale multiplier for Billboard size. Base SVG size is 64x64.
                                // Aircraft needs to be slightly smaller to prevent huge overlapping clusters.
                                scale={(event.type === 'aircraft' || event.type === 'military_aircraft') ? 0.45 : 0.60}
                                // scaleByDistance: [Distance Near, Scale Near, Distance Far, Scale Far]
                                // So at 500km altitude (zoomed in) scale is 1.5 (150% of base scale).
                                // At 15000km altitude (zoomed far out) scale drops linearly to 0.6 (60% of base scale).
                                scaleByDistance={new NearFarScalar(5.0e5, 1.5, 1.5e7, 0.6)}
                                rotation={rotationObj}
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
