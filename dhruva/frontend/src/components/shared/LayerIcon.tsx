import React from 'react';
import type { EventType } from '../../types/events';

/**
 * Clean SVG icons for each layer type — used in sidebar toggles & legend.
 * Each icon is a 16×16 viewBox with strokes/fills matching the layer color.
 */

const ICON_PATHS: Record<EventType, (c: string) => React.ReactNode> = {
    // Earthquake: seismic waves radiating from a fault line epicenter
    earthquake: (c) => (
        <>
            <path d="M2 8h3l2-4 2 8 2-4h3" fill="none" stroke={c} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="8" cy="8" r="7" fill="none" stroke={c} strokeWidth="1" opacity="0.4" />
        </>
    ),
    // Fire: clean modern flame silhouette
    fire: (c) => (
        <path
            d="M8.5 2c0 0-3.5 1.5-3.5 4.5 0 2 1 3.5 1 3.5s.5-1.5 1-2.5c0 0 4.5 1 4.5 5 0 2-1.5 3.5-3.5 3.5-2.5 0-4.5-2-4.5-4.5 0-2 1-3.5 1.5-4-.5.5-1 1.5-1 3 0 0-2 1.5-2 3.5C2 13.5 4.5 16 8 16s6-2.5 6-6c0-4-3-6-5.5-8z"
            fill={c}
            opacity="0.9"
        />
    ),
    // Conflict: crossed swords / battle marker
    conflict: (c) => (
        <>
            <path d="M4 12l8-8M12 12L4 4" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" />
            <circle cx="8" cy="8" r="7" fill="none" stroke={c} strokeWidth="1.5" opacity="0.5" />
        </>
    ),
    // Aircraft: commercial plane silhouette from above
    aircraft: (c) => (
        <path
            d="M13.5 8c0-.8-.7-1.5-1.5-1.5H9L6 2H4.5l1.5 4.5H3L2 5H1l1 3-1 3h1l1-1.5h3L4.5 14H6l3-4.5h3c.8 0 1.5-.7 1.5-1.5z"
            fill={c}
        />
    ),
    // Marine: cargo ship / vessel side profile riding a wave
    marine: (c) => (
        <>
            <path d="M2 10l1-5h8l2 5z" fill={c} opacity="0.8" />
            <path d="M4 5V3h4v2" fill="none" stroke={c} strokeWidth="1.5" />
            <path d="M1 12c2 1 4-1 6 0s4 1 6 0 2-1 2-1" fill="none" stroke={c} strokeWidth="1.5" strokeLinecap="round" />
        </>
    ),
    // Cyber Attack: shield with a digital strike / bug
    cyber: (c) => (
        <>
            <path d="M8 1.5l5 2v4c0 4-5 6.5-5 6.5S3 11.5 3 7.5v-4z" fill="none" stroke={c} strokeWidth="1.5" />
            <path d="M6 7l1.5 2L10.5 5.5" fill="none" stroke={c} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </>
    ),
    // Outage: severed plug / broken connection
    outage: (c) => (
        <>
            <path d="M8 2v4M8 10v4M6 6h4v4H6z" fill="none" stroke={c} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M3 8l3-3m4 0l3 3" fill="none" stroke={c} strokeWidth="1.5" strokeLinecap="round" opacity="0.6" />
        </>
    ),
    // Economic: bold trending chart arrow
    economic: (c) => (
        <>
            <path d="M2 13h12" fill="none" stroke={c} strokeWidth="1.5" strokeLinecap="round" />
            <path d="M3 10l3-3 2 2 4-4" fill="none" stroke={c} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M9 5h3v3" fill="none" stroke={c} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </>
    ),
    // Military: bold target reticle / crosshairs
    military: (c) => (
        <>
            <circle cx="8" cy="8" r="6" fill="none" stroke={c} strokeWidth="1.5" />
            <circle cx="8" cy="8" r="2" fill={c} />
            <path d="M8 1v2M8 13v2M1 8h2M13 8h2" fill="none" stroke={c} strokeWidth="1.5" strokeLinecap="round" />
        </>
    ),
    // Military Aircraft: stealth fighter / jet from above
    military_aircraft: (c) => (
        <path
            d="M8 1l1.5 4h-3zM8 4l4 6v2h-2L8 10l-2 2H4v-2z"
            fill={c}
            stroke={c}
            strokeWidth="1"
            strokeLinejoin="round"
        />
    ),
    // UCDP / General Conflict: warning alert triangle
    ucdp: (c) => (
        <>
            <path d="M8 2l6.5 11H1.5z" fill="none" stroke={c} strokeWidth="1.5" strokeLinejoin="round" />
            <path d="M8 6v3M8 11.5v.5" fill="none" stroke={c} strokeWidth="1.5" strokeLinecap="round" />
        </>
    ),
    // ACLED: map marker / POI pin
    acled: (c) => (
        <>
            <path d="M8 1C5.5 1 3.5 3 3.5 5.5c0 3 4.5 9.5 4.5 9.5s4.5-6.5 4.5-9.5C12.5 3 10.5 1 8 1z" fill="none" stroke={c} strokeWidth="1.5" strokeLinejoin="round" />
            <circle cx="8" cy="5.5" r="2" fill={c} />
        </>
    ),
    // Intel Hotspot: glowing radar blip or scanning eye
    intel_hotspot: (c) => (
        <>
            <path d="M2 8c0 0 3-4 6-4s6 4 6 4-3 4-6 4-6-4-6-4z" fill="none" stroke={c} strokeWidth="1.5" strokeLinejoin="round" />
            <circle cx="8" cy="8" r="2.5" fill={c} />
            <path d="M8 2v1M8 13v1M2 8H1M15 8h-1" fill="none" stroke={c} strokeWidth="1.5" opacity="0.4" strokeLinecap="round" />
        </>
    ),
};

interface LayerIconProps {
    type: EventType;
    color: string;
    size?: number;
    className?: string;
}

const LayerIcon: React.FC<LayerIconProps> = ({ type, color, size = 16, className }) => (
    <svg
        width={size}
        height={size}
        viewBox="0 0 16 16"
        fill="none"
        className={className}
        style={{ flexShrink: 0 }}
    >
        {ICON_PATHS[type]?.(color)}
    </svg>
);

export default LayerIcon;
