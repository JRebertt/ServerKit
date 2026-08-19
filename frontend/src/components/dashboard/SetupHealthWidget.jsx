import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';
import { Pill, statusKind } from '@/components/ds';
import { ShieldCheck, AlertTriangle, Info, ChevronRight } from 'lucide-react';

// Compact "how set-up is this panel" card for the dashboard (admin-only).
// Reads GET /setup-health and shows the score + the top open items, each
// deep-linking to its fix. Collapses to a slim "all set" line when clean —
// no dead card.

const TOP_N = 3;

// Critical (fail) first, then recommended (warn); ok items never show.
function openItems(items) {
    const rank = { fail: 0, warn: 1 };
    return items
        .filter((i) => i.status !== 'ok')
        .sort((a, b) => (rank[a.status] ?? 9) - (rank[b.status] ?? 9));
}

const SetupHealthWidget = () => {
    const navigate = useNavigate();
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;
        api.getSetupHealth()
            .then((res) => { if (!cancelled) setData(res); })
            .catch(() => { /* non-admin or error — widget stays quiet */ })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, []);

    if (loading || !data || !data.summary) {
        return (
            <div className="setup-health-widget setup-health-widget--loading">
                <div className="setup-health-widget__head">
                    <ShieldCheck size={16} />
                    <span>Setup Health</span>
                </div>
                <p className="setup-health-widget__muted">
                    {loading ? 'Checking…' : 'Unavailable'}
                </p>
            </div>
        );
    }

    const { summary } = data;
    const open = openItems(data.items || []);

    // Clean → slim "all set" line, not a big empty card.
    if (open.length === 0) {
        return (
            <button
                type="button"
                className="setup-health-widget setup-health-widget--clean"
                onClick={() => navigate('/monitoring/doctor')}
            >
                <ShieldCheck size={16} />
                <span className="setup-health-widget__cleanlabel">
                    All set — {summary.score}% setup health
                </span>
                <ChevronRight size={14} />
            </button>
        );
    }

    return (
        <div className="setup-health-widget">
            <div className="setup-health-widget__head">
                <span className="setup-health-widget__title">
                    <ShieldCheck size={16} />
                    Setup Health
                </span>
                <span className="setup-health-widget__score">{summary.score}%</span>
            </div>

            <div className="setup-health-widget__summary">
                {summary.critical_open > 0 && (
                    <Pill kind="red">
                        <AlertTriangle size={12} /> {summary.critical_open} critical
                    </Pill>
                )}
                {summary.recommended_open > 0 && (
                    <Pill kind="amber">
                        <Info size={12} /> {summary.recommended_open} recommended
                    </Pill>
                )}
            </div>

            <ul className="setup-health-widget__list">
                {open.slice(0, TOP_N).map((item) => (
                    <li key={item.key}>
                        <button
                            type="button"
                            className="setup-health-widget__item"
                            onClick={() => item.fix?.to && navigate(item.fix.to)}
                        >
                            <Pill kind={statusKind(item.status)}>{item.status}</Pill>
                            <span className="setup-health-widget__itemtitle">{item.title}</span>
                            <ChevronRight size={14} />
                        </button>
                    </li>
                ))}
            </ul>

            {open.length > TOP_N && (
                <button
                    type="button"
                    className="setup-health-widget__more"
                    onClick={() => navigate('/monitoring/doctor')}
                >
                    {open.length - TOP_N} more in Doctor
                </button>
            )}
        </div>
    );
};

export default SetupHealthWidget;
