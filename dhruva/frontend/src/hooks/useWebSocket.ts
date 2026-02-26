import { useEffect, useRef, useState } from 'react';
import type { OsintEvent, RiskLevel, WebSocketMessage } from '../types/events';

const WS_URL = `ws://${window.location.hostname}:8000/ws`;
const RECONNECT_DELAY = 3000;

interface UseWebSocketReturn {
    events: Record<string, OsintEvent[]>;
    risk: RiskLevel | null;
    connected: boolean;
}

export function useWebSocket(): UseWebSocketReturn {
    const [events, setEvents] = useState<Record<string, OsintEvent[]>>({});
    const [risk, setRisk] = useState<RiskLevel | null>(null);
    const [connected, setConnected] = useState(false);
    const wsRef = useRef<WebSocket | null>(null);
    const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
    const mountedRef = useRef(false);

    useEffect(() => {
        mountedRef.current = true;

        function connect() {
            // Don't connect if unmounted (handles StrictMode cleanup)
            if (!mountedRef.current) return;
            // Don't create duplicate connections
            if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

            const ws = new WebSocket(WS_URL);
            wsRef.current = ws;

            ws.onopen = () => {
                if (!mountedRef.current) { ws.close(); return; }
                setConnected(true);
                console.log('[Dhruva WS] Connected');
            };

            ws.onmessage = (e) => {
                if (!mountedRef.current) return;
                try {
                    const msg: WebSocketMessage = JSON.parse(e.data);

                    if (msg.action === 'initial_state') {
                        const grouped: Record<string, OsintEvent[]> = {};
                        for (const event of msg.data) {
                            if (!grouped[event.type]) grouped[event.type] = [];
                            grouped[event.type].push(event);
                        }
                        setEvents(grouped);
                        if (msg.risk) setRisk(msg.risk);
                    }

                    if (msg.action === 'event_batch' && msg.layer) {
                        setEvents(prev => ({
                            ...prev,
                            [msg.layer!]: msg.data,
                        }));
                        if (msg.risk) setRisk(msg.risk);
                    }
                } catch (err) {
                    console.error('[Dhruva WS] Parse error:', err);
                }
            };

            ws.onclose = () => {
                if (!mountedRef.current) return; // Don't reconnect after unmount
                setConnected(false);
                console.log('[Dhruva WS] Disconnected, reconnecting...');
                reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY);
            };

            ws.onerror = () => {
                ws.close();
            };
        }

        connect();

        return () => {
            mountedRef.current = false;
            clearTimeout(reconnectTimer.current);
            const ws = wsRef.current;
            if (ws) {
                ws.onopen = null;
                ws.onmessage = null;
                ws.onerror = null;
                ws.onclose = null;
                // Only close if already OPEN — closing a CONNECTING socket causes the browser warning
                if (ws.readyState === WebSocket.OPEN) {
                    ws.close();
                }
                wsRef.current = null;
            }
        };
    }, []);

    return { events, risk, connected };
}

