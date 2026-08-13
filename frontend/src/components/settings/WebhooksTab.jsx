import { useEffect, useMemo, useState } from 'react';
import api from '../../services/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import Modal from '@/components/Modal';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { useToast } from '../../contexts/ToastContext';
import { useConfirm } from '../../hooks/useConfirm';
import { Plus, MoreVertical, Copy, RefreshCw, ArrowRightLeft } from 'lucide-react';
import EmptyState from '../EmptyState';

const formatDate = (d) => (d ? new Date(d).toLocaleString() : '—');

/**
 * Webhooks — receive, verify, and forward inbound webhooks.
 *
 * Lives as a Settings → Admin tab rather than a top-level page: it's server
 * configuration, not a daily operations surface, and it sits next to the
 * outbound notification subscriptions it complements. /webhooks redirects here.
 * (Secret storage moved to the Organization tab group at /vaults earlier.)
 */
export default function WebhooksTab() {
    const toast = useToast();
    const { confirm } = useConfirm();

    const [endpoints, setEndpoints] = useState([]);
    const [loading, setLoading] = useState(true);

    const [endpointForm, setEndpointForm] = useState({ open: false, name: '', forward_url: '', filter_paths: '', retry_count: 3 });
    const [selectedEndpoint, setSelectedEndpoint] = useState(null);
    const [deliveries, setDeliveries] = useState([]);
    const [regeneratedSecret, setRegeneratedSecret] = useState(null);

    useEffect(() => {
        loadAll();
    }, []);

    async function loadAll() {
        setLoading(true);
        try {
            const e = await api.listWebhookEndpoints();
            setEndpoints(e.endpoints || []);
        } catch (err) {
            toast.error(`Load failed: ${err.message}`);
        } finally {
            setLoading(false);
        }
    }

    async function createEndpoint(e) {
        e.preventDefault();
        try {
            const paths = endpointForm.filter_paths.split('\n').map(s => s.trim()).filter(Boolean);
            await api.createWebhookEndpoint({
                name: endpointForm.name,
                forward_url: endpointForm.forward_url,
                filter_paths: paths,
                retry_count: parseInt(endpointForm.retry_count, 10) || 3,
            });
            setEndpointForm({ open: false, name: '', forward_url: '', filter_paths: '', retry_count: 3 });
            loadAll();
            toast.success('Endpoint created');
        } catch (err) {
            toast.error(`Failed to create endpoint: ${err.message}`);
        }
    }

    async function deleteEndpoint(id) {
        const confirmed = await confirm({
            title: 'Delete Webhook Endpoint',
            message: 'Delete this webhook endpoint? Inbound deliveries to its URL will stop being accepted.',
        });
        if (!confirmed) return;
        try {
            await api.deleteWebhookEndpoint(id);
            if (selectedEndpoint?.id === id) setSelectedEndpoint(null);
            loadAll();
            toast.success('Endpoint deleted');
        } catch (err) {
            toast.error(`Failed to delete endpoint: ${err.message}`);
        }
    }

    async function regenerateSecret(id) {
        try {
            const data = await api.regenerateWebhookSecret(id);
            setRegeneratedSecret({ name: data.endpoint.name, secret: data.secret });
            loadAll();
            if (selectedEndpoint?.id === id) openEndpoint(data.endpoint.id);
        } catch (err) {
            toast.error(`Regenerate failed: ${err.message}`);
        }
    }

    async function openEndpoint(id) {
        try {
            const { endpoint } = await api.getWebhookEndpoint(id);
            const { deliveries } = await api.listWebhookDeliveries(id, { limit: 50 });
            setSelectedEndpoint(endpoint);
            setDeliveries(deliveries || []);
        } catch (err) {
            toast.error(`Failed to load endpoint: ${err.message}`);
        }
    }

    async function replayDelivery(deliveryId) {
        try {
            await api.replayWebhookDelivery(deliveryId);
            openEndpoint(selectedEndpoint.id);
            toast.success('Replayed delivery');
        } catch (err) {
            toast.error(`Replay failed: ${err.message}`);
        }
    }

    const receiverUrl = useMemo(() => {
        if (!selectedEndpoint) return '';
        const base = window.location.origin.replace(/\/$/, '');
        return `${base}/api/v1/webhooks/receive/${selectedEndpoint.slug}`;
    }, [selectedEndpoint]);

    if (loading) {
        return <EmptyState loading loadingVariant="table" title="Loading webhooks..." />;
    }

    return (
        <div className="settings-webhooks">
            {!selectedEndpoint ? (
                <Card>
                    <CardHeader>
                        <div className="secrets__header">
                            <div>
                                <CardTitle>Webhook Endpoints</CardTitle>
                                <CardDescription>Receive, verify, and forward inbound webhooks.</CardDescription>
                            </div>
                            <Button onClick={() => setEndpointForm({ open: true, name: '', forward_url: '', filter_paths: '', retry_count: 3 })}>
                                <Plus size={14} /> New Endpoint
                            </Button>
                        </div>
                    </CardHeader>
                    <CardContent>
                        {endpoints.length === 0 ? (
                            <EmptyState title="No webhook endpoints" description="Create an endpoint to receive webhooks." />
                        ) : (
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Name</TableHead>
                                        <TableHead>Slug</TableHead>
                                        <TableHead>Forward URL</TableHead>
                                        <TableHead>Status</TableHead>
                                        <TableHead className="text-right">Actions</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {endpoints.map(ep => (
                                        <TableRow key={ep.id} className="cursor-pointer" onClick={() => openEndpoint(ep.id)}>
                                            <TableCell className="font-medium">{ep.name}</TableCell>
                                            <TableCell>{ep.slug}</TableCell>
                                            <TableCell>{ep.forward_url || '—'}</TableCell>
                                            <TableCell><Badge variant={ep.is_active ? 'default' : 'secondary'}>{ep.is_active ? 'Active' : 'Inactive'}</Badge></TableCell>
                                            <TableCell className="text-right">
                                                <DropdownMenu>
                                                    <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                                                        <Button variant="ghost" size="icon"><MoreVertical size={14} /></Button>
                                                    </DropdownMenuTrigger>
                                                    <DropdownMenuContent align="end">
                                                        <DropdownMenuItem onClick={() => openEndpoint(ep.id)}>View deliveries</DropdownMenuItem>
                                                        <DropdownMenuItem onClick={() => regenerateSecret(ep.id)}><RefreshCw size={12} className="mr-2" /> Regenerate secret</DropdownMenuItem>
                                                        <DropdownMenuItem className="text-destructive" onClick={() => deleteEndpoint(ep.id)}>Delete</DropdownMenuItem>
                                                    </DropdownMenuContent>
                                                </DropdownMenu>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        )}
                    </CardContent>
                </Card>
            ) : (
                <Card>
                    <CardHeader>
                        <div className="secrets__header">
                            <div>
                                <Button variant="ghost" size="sm" onClick={() => setSelectedEndpoint(null)}>← Back</Button>
                                <CardTitle className="mt-2">{selectedEndpoint.name}</CardTitle>
                                <CardDescription>
                                    POST to <code className="secrets__code">{receiverUrl}</code>
                                </CardDescription>
                            </div>
                            <Button variant="outline" onClick={() => regenerateSecret(selectedEndpoint.id)}>
                                <RefreshCw size={14} /> Regenerate secret
                            </Button>
                        </div>
                    </CardHeader>
                    <CardContent>
                        {deliveries.length === 0 ? (
                            <EmptyState title="No deliveries yet" description="Send a test payload to see it here." />
                        ) : (
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Event ID</TableHead>
                                        <TableHead>Status</TableHead>
                                        <TableHead>Signature</TableHead>
                                        <TableHead>Received</TableHead>
                                        <TableHead className="text-right">Actions</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {deliveries.map(d => (
                                        <TableRow key={d.id}>
                                            <TableCell className="font-mono text-xs max-w-[200px] truncate">{d.event_id}</TableCell>
                                            <TableCell><WebhookStatusBadge status={d.status} /></TableCell>
                                            <TableCell>{d.signature_valid === true ? 'Valid' : d.signature_valid === false ? 'Invalid' : '—'}</TableCell>
                                            <TableCell>{formatDate(d.received_at)}</TableCell>
                                            <TableCell className="text-right">
                                                <Button variant="ghost" size="icon" onClick={() => replayDelivery(d.id)} title="Replay">
                                                    <ArrowRightLeft size={14} />
                                                </Button>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        )}
                    </CardContent>
                </Card>
            )}

            <Modal open={endpointForm.open} onClose={() => setEndpointForm({ ...endpointForm, open: false })} title="New Webhook Endpoint">
                <p className="sk-modal__subtitle">Create a slug, secret, and optional forward URL.</p>
                <form onSubmit={createEndpoint} className="space-y-4">
                        <div>
                            <Label htmlFor="epName">Name</Label>
                            <Input id="epName" value={endpointForm.name} onChange={(e) => setEndpointForm({ ...endpointForm, name: e.target.value })} required />
                        </div>
                        <div>
                            <Label htmlFor="epForward">Forward URL (optional)</Label>
                            <Input id="epForward" type="url" value={endpointForm.forward_url} onChange={(e) => setEndpointForm({ ...endpointForm, forward_url: e.target.value })} />
                        </div>
                        <div>
                            <Label htmlFor="epFilters">Filter paths (one per line, optional)</Label>
                            <Textarea id="epFilters" value={endpointForm.filter_paths} onChange={(e) => setEndpointForm({ ...endpointForm, filter_paths: e.target.value })} placeholder="repository.full_name&#10;action" />
                        </div>
                        <div>
                            <Label htmlFor="epRetry">Retries</Label>
                            <Input id="epRetry" type="number" min={0} max={10} value={endpointForm.retry_count} onChange={(e) => setEndpointForm({ ...endpointForm, retry_count: e.target.value })} />
                        </div>
                        <div className="modal-actions">
                            <Button type="submit">Create Endpoint</Button>
                        </div>
                    </form>
            </Modal>

            <Modal
                open={!!regeneratedSecret}
                onClose={() => setRegeneratedSecret(null)}
                title="Webhook Secret"
                footer={(
                    <Button onClick={() => setRegeneratedSecret(null)}>Done</Button>
                )}
            >
                <p className="sk-modal__subtitle">Copy this secret now. It will not be shown again.</p>
                <div className="space-y-2">
                        <Label>Endpoint</Label>
                        <Input readOnly value={regeneratedSecret?.name || ''} />
                        <Label>Secret</Label>
                        <div className="flex gap-2">
                            <Input readOnly type="text" value={regeneratedSecret?.secret || ''} />
                            <Button variant="outline" onClick={() => { navigator.clipboard.writeText(regeneratedSecret?.secret || ''); toast.success('Copied') }}>
                                <Copy size={14} />
                            </Button>
                        </div>
                    </div>
            </Modal>
        </div>
    );
}

function WebhookStatusBadge({ status }) {
    const variant = status === 'forwarded' ? 'default' : status === 'received' ? 'secondary' : status === 'filtered' ? 'outline' : 'destructive';
    return <Badge variant={variant}>{status}</Badge>;
}
