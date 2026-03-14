import React, { useEffect, useState } from 'react';
import { AlertTriangle, Clock } from 'lucide-react';

interface PizzaData {
    level: number;
    summary: string;
    updatedAt: string;
}

const PizzaMeterIndicator: React.FC = () => {
    const [data, setData] = useState<PizzaData | null>(null);
    const [loading, setLoading] = useState(true);

    const fetchPizzaData = async () => {
        try {
            const resp = await fetch('http://localhost:8000/api/pizza');
            if (resp.ok) {
                const json = await resp.json();
                setData(json);
            }
        } catch (error) {
            console.error("Failed to fetch Pizza Index", error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchPizzaData();
        const interval = setInterval(fetchPizzaData, 60000 * 5); // poll every 5 mins
        return () => clearInterval(interval);
    }, []);

    const colors = {
        1: "#00ff88", // Normal
        2: "#aaff00", // Elevated
        3: "#ffaa00", // High (Orange)
        4: "#ff3333", // Severe (Red)
        5: "#ff0000", // Extreme (Pulsing Red)
    };

    const level = data?.level || 1;
    const color = colors[level as keyof typeof colors];

    // Determine short badge label based on level
    let label = 'NOMINAL';
    if (level === 2) label = 'ELEVATED';
    if (level > 2) label = 'HIGH';
    if (level === 4) label = 'SEVERE';
    if (level === 5) label = 'CRISIS';

    return (
        <div className="defcon-indicator mt-4">
            <div className="defcon-status-bar flex justify-between w-full relative">
                <div className="flex items-center gap-2">
                     <span className="text-[10px] font-mono tracking-widest text-[#0ea5e9] uppercase font-bold">
                        PENTAGON PIZZA METER
                    </span>
                    {level === 5 && (
                         <div className="flex items-center gap-1 text-[10px] font-mono font-bold animate-pulse text-red-500">
                             <AlertTriangle className="w-3 h-3" />
                         </div>
                    )}
                </div>
            </div>

            <div className="defcon-badge" style={{ borderColor: color, boxShadow: `0 0 20px ${color}40` }}>
                <div className="defcon-level" style={{ color }}>
                    {loading ? '-' : level}
                </div>
                <div className="defcon-label" style={{ color }}>
                    {loading ? 'SYNC' : label}
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

            <div className="defcon-stats w-full mt-2 border-t border-slate-800 pt-3 relative">
                 <div className="absolute top-2 right-0 flex items-center gap-1 text-[10px] text-slate-500 font-mono">
                    <Clock className="w-3 h-3" />
                    {data ? new Date(data.updatedAt).toLocaleTimeString() : '--:--'}
                </div>
                 <div className="flex flex-col gap-1 pr-16 w-full">
                    <span className="text-[9px] font-bold tracking-widest text-slate-500 font-mono uppercase">
                        OSINT INTERCEPT LOG
                    </span>
                    <span className="text-[11px] text-slate-300 font-mono leading-relaxed">
                        {loading ? 'ANALYZING THREAT ENVIRONMENT...' : data?.summary}
                    </span>
                </div>
            </div>
        </div>
    );
};

export default PizzaMeterIndicator;
