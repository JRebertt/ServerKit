import { useState, useMemo } from 'react';
import { Search } from 'lucide-react';

const GIB = 1024 ** 3;

// "8 vCPU · 32 GB" — whichever halves the agent has actually reported.
function capacityLabel(server) {
    const parts = [];
    if (server.cpu_cores) parts.push(`${server.cpu_cores} vCPU`);
    if (server.total_memory) parts.push(`${Math.round(server.total_memory / GIB)} GB`);
    return parts.join(' · ');
}

// Radio list of deploy targets showing each one's capacity, so placing a
// service on a second box is a visible choice rather than a hidden default.
// Gains a filter box once the fleet outgrows a glanceable list.
export default function ServerPicker({ servers, value, onChange, filterThreshold = 6 }) {
    const [query, setQuery] = useState('');

    const list = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q) return servers;
        return servers.filter((s) =>
            (s.name || '').toLowerCase().includes(q)
            || (s.group_name || '').toLowerCase().includes(q)
            || (s.os_type || '').toLowerCase().includes(q)
        );
    }, [servers, query]);

    return (
        <div className="sk-srvpick">
            {servers.length > filterThreshold && (
                <div className="sk-srvpick__find">
                    <Search size={14} />
                    <input
                        type="search"
                        placeholder="Find a server…"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        aria-label="Filter servers"
                    />
                </div>
            )}
            <div className="sk-srvpick__list" role="radiogroup" aria-label="Deploy to server">
                {list.map((server) => {
                    const capacity = capacityLabel(server);
                    const selected = value === server.id;
                    return (
                        <button
                            type="button"
                            role="radio"
                            aria-checked={selected}
                            key={server.id}
                            className={`sk-srvpick__row${selected ? ' is-selected' : ''}`}
                            onClick={() => onChange(server.id)}
                        >
                            <span className="sk-srvpick__radio" />
                            <span className="sk-srvpick__meta">
                                <span className="sk-srvpick__name">{server.name}</span>
                                <span className="sk-srvpick__sub">
                                    {server.is_local ? 'this panel' : (server.group_name || 'remote')}
                                    {server.os_type ? ` · ${server.os_type}` : ''}
                                </span>
                            </span>
                            {capacity && <span className="sk-srvpick__tag">{capacity}</span>}
                        </button>
                    );
                })}
                {list.length === 0 && (
                    <div className="sk-srvpick__empty">No servers match.</div>
                )}
            </div>
        </div>
    );
}
