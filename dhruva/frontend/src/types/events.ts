/** Unified OSINT Event — mirrors backend OsintEvent schema */
export interface OsintEvent {
    id: string;
    type: EventType;
    latitude: number;
    longitude: number;
    severity: number; // 1–5
    timestamp: string;
    source: string;
    title: string;
    description: string;
    metadata: Record<string, any>;
}

export type EventType =
    | 'earthquake'
    | 'fire'
    | 'aircraft'
    | 'marine'
    | 'cyber'
    | 'outage'
    | 'economic'
    | 'military'
    | 'military_aircraft'
    | 'ucdp'
    | 'acled'
    | 'acled_cast'
    | 'naval'
    | 'intel_hotspot'
    | 'satellite';

export interface RiskLevel {
    level: number; // 1–5
    label: string;
    color: string;
    event_counts: Record<string, number>;
    score?: number;
    updated_at: string;
}

export interface LayerConfig {
    id: EventType;
    label: string;
    icon: string;
    color: string;
    enabled: boolean;
}

export interface WebSocketMessage {
    action: 'event_batch' | 'risk_update' | 'initial_state';
    data: OsintEvent[];
    risk?: RiskLevel;
    layer?: string;
    layers?: string[];
}

/** Severity → color mapping */
export const SEVERITY_COLORS: Record<number, string> = {
    1: '#00ff88',  // Low – green
    2: '#44ccff',  // Moderate – cyan
    3: '#ffcc00',  // High – amber
    4: '#ff6600',  // Critical – orange
    5: '#ff0033',  // Catastrophic – red
};

/** Layer metadata */
export const LAYER_CONFIGS: LayerConfig[] = [
    { id: 'earthquake', label: 'Earthquakes', icon: 'earthquake', color: '#ff6600', enabled: true },
    { id: 'fire', label: 'Active Fires', icon: 'fire', color: '#ff2d20', enabled: false },
    { id: 'aircraft', label: 'Aircraft', icon: 'aircraft', color: '#00bfff', enabled: false },
    { id: 'marine', label: 'Marine', icon: 'marine', color: '#0077cc', enabled: false },
    { id: 'cyber', label: 'Cyber Attacks', icon: 'cyber', color: '#9333ea', enabled: false },
    { id: 'outage', label: 'Outages', icon: 'outage', color: '#f59e0b', enabled: true },
    { id: 'economic', label: 'Economic', icon: 'economic', color: '#10b981', enabled: false },
    { id: 'military', label: 'Military Zones', icon: 'military', color: '#4ade80', enabled: false },
    { id: 'military_aircraft', label: 'Military Aircraft', icon: 'military_aircraft', color: '#a3e635', enabled: true },
    { id: 'ucdp', label: 'UCDP (Conflicts)', icon: 'ucdp', color: '#e11d48', enabled: true },
    { id: 'acled', label: 'ACLED Events', icon: 'acled', color: '#f97316', enabled: true },
    { id: 'acled_cast', label: 'Predicted Conflict Alert', icon: 'acled', color: '#fbbf24', enabled: true },
    { id: 'naval', label: 'Naval Deployments', icon: 'marine', color: '#3b82f6', enabled: true },
    { id: 'intel_hotspot', label: 'Intel Hotspots', icon: 'intel_hotspot', color: '#fbbf24', enabled: true },
    { id: 'satellite', label: 'Live Satellites', icon: 'satellite', color: '#cbd5e1', enabled: false },
];
