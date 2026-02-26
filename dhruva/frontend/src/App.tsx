import { useState, useCallback, useMemo } from 'react';
import DhruvaGlobe from './components/Globe/DhruvaGlobe';
import EventSidebar from './components/Sidebar/EventSidebar';
import LayerToggles from './components/Controls/LayerToggles';
import DefconIndicator from './components/RiskIndicator/DefconIndicator';
import AirTrafficView from './components/Views/AirTrafficView';
import MarineTrafficView from './components/Views/MarineTrafficView';
import CyberAttackView from './components/Views/CyberAttackView';
import MarketTicker from './components/Ticker/MarketTicker';
import { useWebSocket } from './hooks/useWebSocket';
import type { OsintEvent, EventType } from './types/events';
import { LAYER_CONFIGS } from './types/events';
import './styles/index.css';

type OverlayView = 'air' | 'marine' | 'cyber' | null;

function App() {
  const { events, risk, connected } = useWebSocket();
  const [selectedEvent, setSelectedEvent] = useState<OsintEvent | null>(null);
  const [enabledLayers, setEnabledLayers] = useState<Set<EventType>>(
    new Set(LAYER_CONFIGS.filter(l => l.enabled).map(l => l.id))
  );
  const [activeOverlay, setActiveOverlay] = useState<OverlayView>(null);

  const handleToggleLayer = useCallback((layerId: EventType) => {
    setEnabledLayers(prev => {
      const next = new Set(prev);
      if (next.has(layerId)) {
        next.delete(layerId);
      } else {
        next.add(layerId);
      }
      return next;
    });
  }, []);

  const eventCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const [type, layerEvents] of Object.entries(events)) {
      counts[type] = layerEvents.length;
    }
    return counts;
  }, [events]);

  const totalEvents = useMemo(() => {
    return Object.values(events).reduce((sum, arr) => sum + arr.length, 0);
  }, [events]);

  const allEventsFlat = useMemo(() => {
    return Object.values(events).flat();
  }, [events]);

  return (
    <div className="dhruva-app">
      {/* ─── Header ─── */}
      <header className="dhruva-header">
        <div className="header-brand">
          <div className="brand-icon">◆</div>
          <h1>DHRUVA</h1>
          <span className="header-subtitle">OSINT SITUATIONAL AWARENESS</span>
        </div>
        <div className="header-actions">
        </div>
      </header>

      {/* ─── Main Layout ─── */}
      <div className="dhruva-main">
        {/* Left Panel — Layer Toggles */}
        <aside className="left-panel">
          <LayerToggles
            enabledLayers={enabledLayers}
            eventCounts={eventCounts}
            onToggle={handleToggleLayer}
          />
        </aside>

        {/* Center — 3D Globe */}
        <main className="globe-container">
          <DhruvaGlobe
            events={events}
            enabledLayers={enabledLayers}
            onEventSelect={setSelectedEvent}
          />
        </main>

        {/* Right Panel — Risk Indicator */}
        <aside className="right-panel">
          <DefconIndicator
            risk={risk}
            totalEvents={totalEvents}
            connected={connected}
          />
        </aside>
      </div>

      {/* ─── Event Sidebar ─── */}
      <EventSidebar
        event={selectedEvent}
        onClose={() => setSelectedEvent(null)}
      />

      {/* ─── Overlay Views (on-demand) ─── */}
      {activeOverlay === 'air' && (
        <AirTrafficView
          events={allEventsFlat}
          onClose={() => setActiveOverlay(null)}
        />
      )}
      {activeOverlay === 'marine' && (
        <MarineTrafficView
          events={allEventsFlat}
          onClose={() => setActiveOverlay(null)}
        />
      )}
      {activeOverlay === 'cyber' && (
        <CyberAttackView
          events={allEventsFlat}
          onClose={() => setActiveOverlay(null)}
        />
      )}

      {/* ─── Market Ticker Bar ─── */}
      <MarketTicker />
    </div>
  );
}

export default App;
