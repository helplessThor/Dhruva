import { useEffect, useState } from 'react';
import { ShieldAlert, RefreshCw, Radio, Search, Loader2 } from 'lucide-react';

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
}

export function CCTVGrid() {
    const [feeds, setFeeds] = useState<CCTVFeed[]>([]);
    const [loading, setLoading] = useState(true);
    const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

    // Search Override State
    const [searchQuery, setSearchQuery] = useState("");
    const [searchLoading, setSearchLoading] = useState(false);

    const handleSearch = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!searchQuery.trim()) return;

        setSearchLoading(true);
        try {
            const resp = await fetch(`http://localhost:8000/api/cctv/search?query=${encodeURIComponent(searchQuery)}`);
            if (resp.ok) {
                const data = await resp.json();
                if (data.success) {
                    setFeeds(prev => {
                        const newFeeds = [...prev];
                        if (newFeeds.length > 0) {
                            newFeeds[0] = {
                                ...newFeeds[0],
                                country: data.country || "Custom",
                                city: data.city || searchQuery,
                                video_id: data.video_id,
                                is_fallback: true,
                                subtitle: "MANUAL OVERRIDE",
                                cii_label: "OVERRIDE",
                                cii_color: "#f59e0b" // Amber lock
                            };
                        }
                        return newFeeds;
                    });
                    setSearchQuery("");
                } else {
                    alert("No live public webcam found for that location. Try another city.");
                }
            }
        } catch (error) {
            console.error("Search failed", error);
        } finally {
            setSearchLoading(false);
        }
    };

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
        <div className="w-full bg-slate-900 border-t border-slate-700/50 p-6 flex flex-col gap-4 mt-8">
            {/* Header and Controls */}
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-800 pb-4">
                <div>
                    <h2 className="text-xl font-bold text-white flex items-center gap-2">
                        <Radio className="w-5 h-5 text-red-500 animate-pulse" />
                        Live Global Threat Monitoring
                    </h2>
                    <p className="text-slate-400 text-sm mt-1">
                        Real-time optical feeds from the Top 4 most unstable regions, driven natively by the Country Instability Index (CII).
                    </p>
                </div>

                <div className="flex flex-col md:flex-row items-center gap-3">
                    {/* Search Form */}
                    <form onSubmit={handleSearch} className="relative flex items-center">
                        <input
                            type="text"
                            className="bg-slate-800 border border-slate-700 text-slate-200 text-sm rounded-l px-3 py-1.5 focus:outline-none focus:border-cyan-500 w-48 transition-colors"
                            placeholder="Override city (e.g. Taipei)"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            disabled={searchLoading}
                        />
                        <button
                            type="submit"
                            disabled={searchLoading || !searchQuery.trim()}
                            className="bg-slate-700 hover:bg-slate-600 border border-l-0 border-slate-700 rounded-r px-3 py-1.5 flex items-center justify-center transition-colors disabled:opacity-50"
                        >
                            {searchLoading ? <Loader2 className="w-4 h-4 text-cyan-400 justify-center animate-spin" /> : <Search className="w-4 h-4 text-slate-300" />}
                        </button>
                    </form>

                    <div className="text-xs text-slate-500 flex items-center gap-1 font-mono bg-slate-800/50 rounded px-2 py-1.5 border border-slate-700">
                        <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
                        {lastUpdated.toLocaleTimeString()}
                    </div>
                    <button
                        onClick={fetchFeeds}
                        disabled={loading}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-600 rounded text-sm text-slate-300 transition-colors disabled:opacity-50"
                    >
                        Auto-Rotate
                    </button>
                </div>
            </div>

            {/* Grid Canvas */}
            <div
                className="gap-4 w-full mt-4"
                style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}
            >
                {feeds.map((feed, idx) => (
                    <div
                        key={`${feed.iso2}-${idx}`}
                        className="relative bg-black rounded-lg overflow-hidden border-2 shadow-lg flex flex-col"
                        style={{
                            borderColor: feed.cii_color,
                            boxShadow: feed.cii_score > 50 ? `0 0 15px ${feed.cii_color}40` : 'none'
                        }}
                    >
                        {/* Overlay Header */}
                        <div className="absolute top-0 left-0 right-0 z-10 bg-gradient-to-b from-black/90 to-transparent p-3 flex justify-between items-start pointer-events-none">
                            <div>
                                <div className="flex items-center gap-2">
                                    <img
                                        src={`https://flagcdn.com/24x18/${feed.iso2.toLowerCase()}.png`}
                                        alt={feed.country}
                                        className="rounded-sm opacity-90"
                                    />
                                    <h3 className="text-white font-mono font-bold tracking-wider drop-shadow-md">
                                        {feed.city.toUpperCase()}, {feed.country.toUpperCase()}
                                    </h3>
                                </div>
                                {feed.is_fallback && feed.subtitle && (
                                    <p className="text-orange-400 text-xs mt-1 font-mono uppercase bg-black/50 px-1 rounded inline-block">
                                        ⚠️ {feed.subtitle}
                                    </p>
                                )}
                            </div>

                            <div
                                className="px-2 py-1 rounded text-xs font-bold font-mono border backdrop-blur-sm shadow-sm"
                                style={{
                                    backgroundColor: `${feed.cii_color}20`,
                                    borderColor: feed.cii_color,
                                    color: feed.cii_color
                                }}
                            >
                                CII: {feed.cii_score.toFixed(1)} [{feed.cii_label}]
                            </div>
                        </div>

                        {/* Sub-Header for override (placeholder for now) */}
                        <div className="absolute bottom-0 left-0 right-0 z-10 bg-gradient-to-t from-black/90 to-transparent p-3 pt-8 pb-2 pointer-events-none flex justify-between items-end">
                            <div className="flex items-center gap-1.5 text-red-500 font-mono text-[10px] uppercase font-bold tracking-widest bg-black/50 px-1.5 py-0.5 rounded">
                                <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"></span>
                                LIVE REC.
                            </div>
                            <div className="text-slate-500 font-mono text-[10px] tracking-widest">
                                CAM-{idx + 1}-SATCOM
                            </div>
                        </div>

                        {/* Video Player */}
                        <div className="relative w-full aspect-video bg-slate-900 flex items-center justify-center">
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
                    // Skeletons
                    [1, 2, 3, 4].map(i => (
                        <div key={i} className="w-full aspect-video bg-slate-800 rounded-lg animate-pulse border border-slate-700"></div>
                    ))
                )}
            </div>
        </div>
    );
}
