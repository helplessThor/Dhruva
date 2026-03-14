import { useEffect, useState } from 'react';
import { ShieldAlert, RefreshCw } from 'lucide-react';

interface CCTVFeed {
    country: string;
    iso2: string;
    city: string;
    video_id: string;
    is_fallback: boolean;
    actual_country_iso?: string;
    subtitle?: string;
    cii_score: number;
    cii_label: string;
    cii_color: string;
    war_severity?: number;
}

export function CCTVGrid() {
    const [feeds, setFeeds] = useState<CCTVFeed[]>([]);
    const [loading, setLoading] = useState(true);
    const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

    const fetchFeeds = async () => {
        setLoading(true);
        try {
            const resp = await fetch('http://localhost:8000/api/cctv');
            if (resp.ok) {
                const data = await resp.json();
                setFeeds(data);
                setLastUpdated(new Date());
            }
        } catch (error) {
            console.error("Failed to fetch CCTV feeds", error);
        } finally {
            setLoading(false);
        }
    };

    // Fetch immediately and poll every 60 seconds (since CII updates frequently)
    useEffect(() => {
        fetchFeeds();
        const interval = setInterval(fetchFeeds, 60000);
        return () => clearInterval(interval);
    }, []);

    return (
        <div className="w-full bg-[#0a0a0a] border-t border-slate-800 p-2 flex flex-col gap-2 relative mt-4">

            {/* Top Widget Header */}
            <div className="flex items-center justify-between gap-3 mb-2 px-2 border-b border-slate-800 pb-2">
                <div className="flex items-center gap-3">
                    <h2 className="text-white font-mono font-bold tracking-widest flex items-center gap-2 uppercase text-lg">
                        LIVE WARZONE CAM
                    </h2>
                    <div className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-full bg-red-600 animate-pulse shadow-[0_0_8px_rgba(220,38,38,0.8)]"></span>
                        <span className="text-red-500 font-mono font-bold">LIVE</span>
                    </div>
                </div>
                
                <div className="text-[10px] text-slate-500 flex items-center gap-1 font-mono uppercase">
                    <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin text-red-500' : ''}`} />
                    {lastUpdated.toLocaleTimeString()}
                </div>
            </div>

            {/* Grid Canvas - Single Large Feed */}
            <div className="w-full mt-1">
                {feeds.map((feed, idx) => (
                    <div
                        key={`${feed.iso2}-${idx}`}
                        className="relative bg-black border-2 border-slate-800 shadow-[0_0_30px_rgba(0,0,0,0.8)] flex flex-col group overflow-hidden rounded-sm w-full"
                        style={{ height: '600px' }} // Make it massive
                    >
                        {/* Status Dot Top Left */}
                        <div className="absolute top-4 left-4 z-20 flex items-center gap-2">
                            <div className="w-3 h-3 rounded-full bg-red-600 border-2 border-red-400 animate-pulse shadow-[0_0_12px_rgba(220,38,38,0.9)]"></div>
                        </div>

                        {/* Overlay Header */}
                        <div className="absolute top-4 left-10 z-10 flex justify-between items-start pointer-events-none">
                            <div>
                                <h3 className="text-white font-mono font-bold tracking-widest text-xl drop-shadow-[0_2px_4px_rgba(0,0,0,1)] uppercase">
                                    {feed.city}
                                </h3>
                                {feed.is_fallback && feed.subtitle && (
                                    <p className="text-orange-400 text-[10px] mt-0.5 font-mono uppercase bg-black/60 px-1 inline-block">
                                        ⚠️ {feed.subtitle}
                                    </p>
                                )}
                            </div>
                        </div>

                        {/* CII Override specific overlay to show country status */}
                        {feed.war_severity ? (
                            <div className="absolute top-4 right-4 z-10 px-3 py-1 bg-black/80 border border-red-500 text-sm text-red-500 font-mono font-bold flex items-center gap-2 shadow-[0_0_15px_rgba(220,38,38,0.3)]">
                                WAR SEVERITY: {feed.war_severity}/5
                            </div>
                        ) : (
                            <div className="absolute top-4 right-4 z-10 px-3 py-1 bg-black/80 text-sm text-[#00ff88] font-mono border border-[#00ff88]/30">
                                THREAT: {feed.cii_score.toFixed(0)}
                            </div>
                        )}

                        {/* Video Player */}
                        <div className="relative w-full aspect-video bg-[#050505] flex items-center justify-center">
                            {feed.video_id ? (
                                <iframe
                                    className="absolute inset-0 w-full h-full pointer-events-none" // pointer-events-none prevents scrolling issues
                                    src={`${feed.video_id}&controls=0&showinfo=0&rel=0`}
                                    title={`${feed.city} Live CCTV`}
                                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                                    allowFullScreen
                                ></iframe>
                            ) : (
                                <div className="flex flex-col items-center text-slate-600 font-mono">
                                    <ShieldAlert className="w-10 h-10 mb-2 opacity-50" />
                                    <p>FEED_OFFLINE</p>
                                    <p className="text-xs mt-1 text-slate-700">NO SATCOM LINK ESTABLISHED</p>
                                </div>
                            )}
                        </div>

                    </div>
                ))}

                {loading && feeds.length === 0 && (
                    <div className="w-full h-[600px] bg-slate-900 rounded-sm animate-pulse border border-slate-800 flex items-center justify-center flex-col text-slate-600 font-mono">
                         <ShieldAlert className="w-12 h-12 mb-4 opacity-50 animate-pulse" />
                         <p>ESTABLISHING SATCOM LINK...</p>
                    </div>
                )}
            </div>
        </div>
    );
}
