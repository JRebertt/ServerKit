import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, Network, RefreshCw, Server as ServerIcon } from 'lucide-react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import { Button } from '@/components/ui/button';
import { DataTable, Pill } from '@/components/ds';
import EmptyState from '../components/EmptyState';

// Fleet-wide reverse-proxy dashboard (Phase 4 of C6). Aggregates every
// server's managed-proxy posture into one table: which proxy each server runs
// (host nginx by default, or a managed Traefik/Caddy stack), its status, when
// its config was last regenerated, and how many docker networks it joins.
// Per-server configuration still lives on each server's Proxy tab — every row
// links through to it.

// Human label + Pill kind for each proxy type. Host nginx is the default and
// reads as the "neutral" choice; the managed stacks get accent colors.
const PROXY_TYPE_META = {
    nginx: { label: 'Nginx', kind: 'gray' },
    traefik: { label: 'Traefik', kind: 'cyan' },
    caddy: { label: 'Caddy', kind: 'violet' },
};

// Status → Pill kind. 'host' means "host nginx, no managed stack" — a healthy
// default, not a fault, so it reads green-ish (cyan) rather than amber.
const STATUS_KIND = {
    running: 'green',
    host: 'cyan',
    stopped: 'gray',
    error: 'red',
    unknown: 'amber',
};

const STATUS_LABEL = {
    running: 'Running',
    host: 'Host default',
    stopped: 'Stopped',
    error: 'Error',
    unknown: 'Unknown',
};

// Recommendation level → Pill kind. 'ok' reads green (aligned), 'info' is a
// neutral note, 'warn' is amber so the operator can spot what needs action.
const RECOMMENDATION_KIND = {
    ok: 'green',
    info: 'gray',
    warn: 'amber',
};

function formatTimestamp(value) {
    if (!value) return 'Never';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Never';
    return date.toLocaleString();
}

function typeMeta(type) {
    return PROXY_TYPE_META[type] || { label: type || 'Unknown', kind: 'gray' };
}

const FleetProxy = () => {
    const toast = useToast();
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await api.getFleetProxyOverview();
            const list = Array.isArray(data?.servers) ? data.servers : [];
            setRows(list);
            setError(null);
        } catch (err) {
            setError(err.message || 'Failed to load fleet proxy overview');
            toast.error('Failed to load fleet proxy overview');
        } finally {
            setLoading(false);
        }
    }, [toast]);

    useEffect(() => {
        load();
    }, [load]);

    // Publish a Refresh button into the shared Servers tab-group top bar.
    useTopbarActions(() => (
        <Button size="sm" onClick={load} disabled={loading}>
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            Refresh
        </Button>
    ), [loading]);

    // No KPI band and no page title: every tile it held was a re-count of a
    // column already on the table below, and the tab strip names the page.
    const columns = [
        { key: 'server', header: 'Server' },
        { key: 'type', header: 'Proxy type' },
        { key: 'status', header: 'Status' },
        { key: 'apps', header: 'Apps' },
        { key: 'recommendation', header: 'Recommendation' },
        { key: 'lastRegenerated', header: 'Last regenerated' },
        { key: 'networks', header: 'Networks' },
        { key: 'actions', header: '', className: 'fleet-proxy__col-actions' },
    ];

    return (
        <div className="sk-tabgroup__inner fleet-proxy">
            {error ? (
                <div className="fleet-proxy__error">
                    <p>{error}</p>
                    <Button variant="outline" size="sm" onClick={load}>Retry</Button>
                </div>
            ) : (
                <div className="fleet-proxy__table">
                    <DataTable
                        loading={loading}
                        sortable={false}
                        columns={columns}
                        data={rows}
                        keyField="server_id"
                        emptyState={(
                            <EmptyState
                                icon={Network}
                                title="No servers in the fleet"
                                description="This is where each server's reverse-proxy posture lands: which proxy it runs, whether it's healthy, and when its config was last regenerated. Host Nginx is the default; a server can opt into a managed Traefik or Caddy stack from its Proxy tab. Add a server to start."
                            />
                        )}
                        renderRow={(row, { key }) => {
                            const meta = typeMeta(row.proxy_type);
                            return (
                                <tr key={key} className="fleet-proxy__row">
                                    <td>
                                        <Link
                                            to={`/servers/${row.server_id}/proxy`}
                                            className="fleet-proxy__server"
                                        >
                                            <ServerIcon size={14} />
                                            <span>{row.server_name || 'Unnamed server'}</span>
                                        </Link>
                                    </td>
                                    <td>
                                        <Pill kind={meta.kind} dot={false}>{meta.label}</Pill>
                                    </td>
                                    <td>
                                        <Pill kind={STATUS_KIND[row.status] || 'gray'}>
                                            {STATUS_LABEL[row.status] || row.status || 'Unknown'}
                                        </Pill>
                                    </td>
                                    <td>
                                        <div className="fleet-proxy__apps">
                                            <span className="fleet-proxy__muted">{row.app_count ?? 0}</span>
                                            {row.mismatch_count > 0 && (
                                                <Pill kind="amber" dot={false}>
                                                    <AlertTriangle size={12} />
                                                    {row.mismatch_count} ingress mismatch{row.mismatch_count === 1 ? '' : 'es'}
                                                </Pill>
                                            )}
                                        </div>
                                    </td>
                                    <td>
                                        {row.recommendation ? (
                                            <Pill
                                                kind={RECOMMENDATION_KIND[row.recommendation.level] || 'gray'}
                                                dot={false}
                                                className="fleet-proxy__recommendation"
                                                title={row.recommendation.text}
                                            >
                                                {row.recommendation.text}
                                            </Pill>
                                        ) : (
                                            <span className="fleet-proxy__muted">—</span>
                                        )}
                                    </td>
                                    <td className="fleet-proxy__muted">
                                        {formatTimestamp(row.last_regenerated_at)}
                                    </td>
                                    <td className="fleet-proxy__muted">{row.networks_count ?? 0}</td>
                                    <td className="fleet-proxy__col-actions">
                                        <Button asChild variant="ghost" size="sm">
                                            <Link to={`/servers/${row.server_id}/proxy`}>Manage</Link>
                                        </Button>
                                    </td>
                                </tr>
                            );
                        }}
                    />
                </div>
            )}
        </div>
    );
};

export default FleetProxy;
