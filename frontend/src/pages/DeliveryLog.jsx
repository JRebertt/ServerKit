import { useState, useEffect, useCallback, useRef } from 'react';
import { Send, RefreshCw, Inbox } from 'lucide-react';
import api from '../services/api';
import { MetricCard, KpiBand, FilterDrawer, FilterButton } from '@/components/ds';
import PageLayout from '../layouts/PageLayout';
import { Button } from '@/components/ui/button';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import { timeAgo } from '../utils/timeAgo';
import EmailProviders from '../components/EmailProviders';

const STATUSES = ['all', 'pending', 'sent', 'failed', 'skipped'];
const CHANNELS = ['all', 'inapp', 'email', 'discord', 'slack', 'telegram', 'webhook'];
const POLL_MS = 5000;

export default function DeliveryLog() {
    const { isAdmin } = useAuth();
    const toast = useToast();
    const [deliveries, setDeliveries] = useState([]);
    const [stats, setStats] = useState(null);
    const [status, setStatus] = useState('all');
    const [channel, setChannel] = useState('all');
    const [filtersOpen, setFiltersOpen] = useState(false);
    const [loading, setLoading] = useState(true);
    const pollRef = useRef(null);

    const load = useCallback(async () => {
        try {
            const params = {};
            if (status !== 'all') params.status = status;
            if (channel !== 'all') params.channel = channel;
            const data = await api.getDeliveryLog(params);
            setDeliveries(data.deliveries || []);
            setStats(data.stats || null);
        } catch {
            // leave the last good state on screen
        } finally {
            setLoading(false);
        }
    }, [status, channel]);

    useEffect(() => {
        if (!isAdmin) return undefined;
        load();
        pollRef.current = setInterval(load, POLL_MS);
        return () => clearInterval(pollRef.current);
    }, [isAdmin, load]);

    const onRetry = async (id) => {
        try {
            await api.retryDelivery(id);
            toast.success('Delivery re-queued');
            load();
        } catch {
            toast.error('Retry failed');
        }
    };

    if (!isAdmin) {
        return (
            <PageLayout icon={<Send size={18} />} title="Notification Delivery Log">
                <div className="sk-dlog"><div className="sk-dlog__empty">Admins only.</div></div>
            </PageLayout>
        );
    }

    const byStatus = stats?.by_status || {};

    return (
        <PageLayout
            icon={<Send size={18} />}
            title="Notification Delivery Log"
            meta="Outbound deliveries across all channels"
            actions={(
                <>
                    <FilterButton
                        count={(status !== 'all' ? 1 : 0) + (channel !== 'all' ? 1 : 0)}
                        onClick={() => setFiltersOpen(true)}
                    />
                    <Button variant="outline" size="sm" onClick={load}>
                        <RefreshCw size={14} /> Refresh
                    </Button>
                </>
            )}
        >
            <div className="sk-dlog">
                <EmailProviders />

                <KpiBand>
                    <MetricCard label="Total" value={stats?.total ?? 0} tone="accent" />
                    <MetricCard label="Sent" value={byStatus.sent ?? 0} tone="green" />
                    <MetricCard label="Pending" value={byStatus.pending ?? 0} tone="amber" />
                    <MetricCard label="Failed" value={byStatus.failed ?? 0} tone="red" />
                </KpiBand>


                {loading && deliveries.length === 0 ? (
                    <div className="sk-dlog__empty">Loading…</div>
                ) : deliveries.length === 0 ? (
                    <div className="sk-dlog__empty">
                        <Inbox size={24} aria-hidden="true" />
                        <p>No deliveries match these filters.</p>
                    </div>
                ) : (
                    <div className="sk-dlog__table-wrap">
                        <table className="sk-dlog__table">
                            <thead>
                                <tr>
                                    <th>Status</th>
                                    <th>Channel</th>
                                    <th>To</th>
                                    <th>Notification</th>
                                    <th>Tries</th>
                                    <th>When</th>
                                    <th aria-label="Actions" />
                                </tr>
                            </thead>
                            <tbody>
                                {deliveries.map((d) => (
                                    <tr key={d.id}>
                                        <td><span className={`sk-dlog__status is-${d.status}`}>{d.status}</span></td>
                                        <td>{d.channel}</td>
                                        <td className="sk-dlog__target">{d.target || '—'}</td>
                                        <td>
                                            <div className="sk-dlog__title">{d.title || d.event_key}</div>
                                            {d.error && <div className="sk-dlog__error" title={d.error}>{d.error}</div>}
                                        </td>
                                        <td>{d.attempts}</td>
                                        <td className="sk-dlog__when">{timeAgo(d.created_at)}</td>
                                        <td>
                                            {(d.status === 'failed' || d.status === 'skipped') && d.channel !== 'inapp' && (
                                                <Button variant="ghost" size="sm" onClick={() => onRetry(d.id)}>Retry</Button>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            <FilterDrawer
                open={filtersOpen}
                onOpenChange={setFiltersOpen}
                title="Filter deliveries"
                activeCount={(status !== 'all' ? 1 : 0) + (channel !== 'all' ? 1 : 0)}
                groups={[
                    { key: 'status', label: 'Status', type: 'single',
                      options: STATUSES.filter((v) => v !== 'all').map((v) => ({ value: v, label: v })) },
                    { key: 'channel', label: 'Channel', type: 'single',
                      options: CHANNELS.filter((v) => v !== 'all').map((v) => ({ value: v, label: v })) },
                ]}
                value={{
                    status: status === 'all' ? '' : status,
                    channel: channel === 'all' ? '' : channel,
                }}
                onChange={(next) => {
                    setStatus(next.status || 'all');
                    setChannel(next.channel || 'all');
                }}
            />
        </PageLayout>
    );
}
