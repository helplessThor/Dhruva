import React from 'react';
import type { EventType } from '../../types/events';

/**
 * Clean SVG icons for each layer type — used in sidebar toggles & legend.
 * Each icon is a 16×16 viewBox with strokes/fills matching the layer color.
 */

const ICON_PATHS: Record<EventType, (c: string) => React.ReactNode> = {
    earthquake: (c) => (
        <>
            <circle cx="8" cy="8" r="2.5" fill={c} />
            <circle cx="8" cy="8" r="5" fill="none" stroke={c} strokeWidth="1.2" opacity="0.7" />
            <circle cx="8" cy="8" r="7" fill="none" stroke={c} strokeWidth="0.8" opacity="0.4" />
        </>
    ),
    fire: (c) => (
        <path
            d="M8 2C8 2 4.5 6.5 4.5 9.5C4.5 11.4 5.6 13 8 13S11.5 11.4 11.5 9.5C11.5 6.5 8 2 8 2Z"
            fill={c}
            opacity="0.9"
        />
    ),
    conflict: (c) => (
        <>
            <circle cx="8" cy="8" r="3.5" fill="none" stroke={c} strokeWidth="1.3" />
            <circle cx="8" cy="8" r="1.2" fill={c} />
            <line x1="8" y1="1.5" x2="8" y2="4.5" stroke={c} strokeWidth="1.3" />
            <line x1="8" y1="11.5" x2="8" y2="14.5" stroke={c} strokeWidth="1.3" />
            <line x1="1.5" y1="8" x2="4.5" y2="8" stroke={c} strokeWidth="1.3" />
            <line x1="11.5" y1="8" x2="14.5" y2="8" stroke={c} strokeWidth="1.3" />
        </>
    ),
    aircraft: (c) => (
        <path
            d="M8 2 L9.2 6.5 L14 8 L9.2 9.2 L9.8 13 L8 12 L6.2 13 L6.8 9.2 L2 8 L6.8 6.5 Z"
            fill={c}
        />
    ),
    marine: (c) => (
        <>
            <path d="M4 11 Q6 13 8 11 Q10 13 12 11" fill="none" stroke={c} strokeWidth="1.3" strokeLinecap="round" />
            <path d="M4 13 Q6 15 8 13 Q10 15 12 13" fill="none" stroke={c} strokeWidth="1.3" strokeLinecap="round" opacity="0.5" />
            <polygon points="8,2 9.5,8 8,7.5 6.5,8" fill={c} opacity="0.9" />
            <line x1="8" y1="2" x2="8" y2="11" stroke={c} strokeWidth="1.2" />
        </>
    ),
    cyber: (c) => (
        <>
            <path
                d="M8 1.5 L13 4 L13 8.5 C13 11.5 10.5 13.5 8 14.5 C5.5 13.5 3 11.5 3 8.5 L3 4 Z"
                fill="none"
                stroke={c}
                strokeWidth="1.2"
            />
            <rect x="6.5" y="7.5" width="3" height="2.5" rx="0.5" fill={c} />
            <path d="M7 7.5 V6.5 C7 5.5 9 5.5 9 6.5 V7.5" fill="none" stroke={c} strokeWidth="1" />
        </>
    ),
    outage: (c) => (
        <path
            d="M9.5 2 L5 8.5 L7.5 8.5 L6.5 14 L11 7.5 L8.5 7.5 Z"
            fill={c}
        />
    ),
    economic: (c) => (
        <>
            <polyline
                points="2,12 5.5,7.5 9,9.5 14,3.5"
                fill="none"
                stroke={c}
                strokeWidth="1.4"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
            <polyline
                points="11.5,3.5 14,3.5 14,6"
                fill="none"
                stroke={c}
                strokeWidth="1.4"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
        </>
    ),
    military: (c) => (
        <>
            <path
                d="M8 1.5 L13 4 L13 9 C13 12 10.5 14 8 15 C5.5 14 3 12 3 9 L3 4 Z"
                fill="none"
                stroke={c}
                strokeWidth="1.2"
            />
            <line x1="8" y1="5.5" x2="8" y2="11" stroke={c} strokeWidth="1.2" />
            <line x1="5.5" y1="8" x2="10.5" y2="8" stroke={c} strokeWidth="1.2" />
        </>
    ),
    military_aircraft: (c) => (
        <>
            {/* Fuselage — pointed nose to tail */}
            <line x1="8" y1="1.5" x2="8" y2="13" stroke={c} strokeWidth="1.5" strokeLinecap="round" />
            {/* Swept delta wings */}
            <path d="M8 4 L1.5 11.5 L5 10 L8 13 L11 10 L14.5 11.5 Z" fill={c} opacity="0.9" />
            {/* Canards (small forward wings) */}
            <path d="M8 5.5 L5.5 7.5 L7 7 L8 8 L9 7 L10.5 7.5 Z" fill={c} />
            {/* Tail fins */}
            <line x1="6.5" y1="11.5" x2="5" y2="14" stroke={c} strokeWidth="1" strokeLinecap="round" />
            <line x1="9.5" y1="11.5" x2="11" y2="14" stroke={c} strokeWidth="1" strokeLinecap="round" />
        </>
    ),
    ucdp: (c) => (
        <polygon
            points="8,1.5 9.5,5.5 14,5.5 10.5,8.5 11.5,13 8,10.5 4.5,13 5.5,8.5 2,5.5 6.5,5.5"
            fill={c}
            opacity="0.9"
        />
    ),
    acled: (c) => (
        <>
            <circle cx="8" cy="8" r="4" fill="none" stroke={c} strokeWidth="1.3" />
            <circle cx="8" cy="8" r="1.8" fill="none" stroke={c} strokeWidth="1" />
            <circle cx="8" cy="8" r="0.8" fill={c} />
            <line x1="8" y1="2" x2="8" y2="4" stroke={c} strokeWidth="1.2" />
            <line x1="8" y1="12" x2="8" y2="14" stroke={c} strokeWidth="1.2" />
        </>
    ),
    intel_hotspot: (c) => (
        <>
            <path
                d="M8 2 L9.5 6 L14 6 L10.5 9 L11.5 13 L8 10.5 L4.5 13 L5.5 9 L2 6 L6.5 6 Z"
                fill={c}
                opacity="0.85"
            />
            <circle cx="8" cy="8" r="7" fill="none" stroke={c} strokeWidth="0.7" opacity="0.4" />
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
