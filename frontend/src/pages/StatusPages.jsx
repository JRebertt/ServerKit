import { useEffect, useMemo, useState } from 'react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import { useAuth } from '../contexts/AuthContext';
import PageLoader from '../components/PageLoader';
import ConfirmDialog from '../components/ConfirmDialog';
import EmptyState from '../components/EmptyState';
import Modal from '@/components/Modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Pill } from '@/components/ds';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import { copyToClipboard } from '@/utils/clipboard';
import {
    Activity,
    CheckCircle2,
    Copy,
    ExternalLink,
    Globe2,
    Link2,
    PlayCircle,
    Plus,
    RefreshCw,
    Trash2,
    Unlink,
} from 'lucide-react';

// pill → ds Pill kind · tone → .status-dot modifier · dot → .comp-dots square
const STATUS_META = {
    operational: { label: 'Operational', pill: 'green', tone: 'success', dot: '' },
    degraded: { label: 'Degraded', pill: 'amber', tone: 'warning', dot: 'degraded' },
    partial_outage: { label: 'Partial outage', pill: 'amber', tone: 'warning', dot: 'degraded' },
    major_outage: { label: 'Major outage', pill: 'red', tone: 'danger', dot: 'down' },
    maintenance: { label: 'Maintenance', pill: 'cyan', tone: 'info', dot: 'maintenance' },
};

const INCIDENT_STATUS = [
    { value: 'investigating', label: 'Investigating' },
    { value: 'identified', label: 'Identified' },
    { value: 'monitoring', label: 'Monitoring' },
    { value: 'resolved', label: 'Resolved' },
];

const IMPACT_OPTIONS = [
    { value: 'none', label: 'None' },
    { value: 'minor', label: 'Minor' },
    { value: 'major', label: 'Major' },
    { value: 'critical', label: 'Critical' },
];

const CHECK_TARGET_PLACEHOLDERS = {
    http: 'https://example.com/health',
    tcp: 'example.com:443',
    dns: 'example.com',
    ping: 'example.com',
};

const defaultPageForm = { name: '', slug: '', description: '', primary_color: '#6d7cff' };
const defaultCompForm = {
    name: '',
    group: 'Services',
    check_type: 'http',
    check_target: '',
    check_interval: 60,
    check_timeout: 10,
};
const defaultIncidentForm = { title: '', status: 'investigating', impact: 'minor', body: '' };

function normalizeSlug(value) {
    return (value || '')
        .toLowerCase()
        .trim()
        .replace(/[\s_]+/g, '-')
        .replace(/[^a-z0-9-]/g, '')
        .replace(/-+/g, '-')
        .replace(/^-|-$/g, '');
}

function formatDate(value) {
    if (!value) return 'Never';
    return new Date(value).toLocaleString();
}

function formatUptime(value) {
    if (typeof value !== 'number') return '100.00%';
    return `${value.toFixed(2)}%`;
}

function getPublicStatusUrl(page) {
    if (!page) return '';
    return `${window.location.origin}/status/${page.slug}`;
}

function getOverallStatus(components) {
    const statuses = components.map((component) => component.status);
    if (statuses.some((status) => status === 'major_outage')) return 'major_outage';
    if (statuses.some((status) => status === 'partial_outage' || status === 'degraded')) return 'degraded';
    if (statuses.some((status) => status === 'maintenance')) return 'maintenance';
    return 'operational';
}

const StatusPages = () => {
    const toast = useToast();
    const { user } = useAuth();
    const [pages, setPages] = useState([]);
    const [loading, setLoading] = useState(true);
    const [selectedPage, setSelectedPage] = useState(null);
    const [components, setComponents] = useState([]);
    const [incidents, setIncidents] = useState([]);
    const [showCreatePage, setShowCreatePage] = useState(false);
    const [showCreateComponent, setShowCreateComponent] = useState(false);
    // Monitors are first-class now (core /api/v1/monitors) — a status page
    // publishes a subset of them rather than owning its own private probes. This
    // is the list of monitors not yet on any page.
    const [unattached, setUnattached] = useState([]);
    const [showAttach, setShowAttach] = useState(false);
    const [showCreateIncident, setShowCreateIncident] = useState(false);
    const [deleteConfirm, setDeleteConfirm] = useState(null);

    const [pageForm, setPageForm] = useState(defaultPageForm);
    const [compForm, setCompForm] = useState(defaultCompForm);
    const [incidentForm, setIncidentForm] = useState(defaultIncidentForm);

    const isAdmin = Boolean(user?.is_admin);

    const groupedComponents = useMemo(() => {
        return components.reduce((groups, component) => {
            const groupName = component.group || 'Services';
            groups[groupName] = groups[groupName] || [];
            groups[groupName].push(component);
            return groups;
        }, {});
    }, [components]);

    const activeIncidents = useMemo(
        () => incidents.filter((incident) => incident.status !== 'resolved'),
        [incidents]
    );

    const overallStatus = useMemo(() => getOverallStatus(components), [components]);
    const overallMeta = STATUS_META[overallStatus] || STATUS_META.operational;
    const selectedUrl = getPublicStatusUrl(selectedPage);

    const loadPageDetails = async (page) => {
        if (!page) return;
        try {
            const [cData, iData, mData] = await Promise.all([
                api.getStatusPageComponents(page.id),
                api.getStatusPageIncidents(page.id),
                api.getMonitors().catch(() => null),
            ]);
            setSelectedPage(page);
            setComponents(cData.components || []);
            setIncidents(iData.incidents || []);
            setUnattached((mData?.monitors || []).filter((m) => m.page_id == null));
        } catch (err) {
            toast.error(err.message || 'Failed to load page details');
        }
    };

    // Publishing an existing monitor is just setting its page — no second probe,
    // no duplicated config, and the monitor keeps the history it already has.
    const handleAttachMonitor = async (monitor) => {
        try {
            await api.updateMonitor(monitor.id, { page_id: selectedPage.id });
            toast.success(`${monitor.name} added to ${selectedPage.name}`);
            setShowAttach(false);
            await loadPageDetails(selectedPage);
        } catch (err) {
            toast.error(err.message || 'Could not add the monitor');
        }
    };

    // Unpublish without destroying: deleting a component now deletes a real
    // monitor and its history, so removing it from a page needs its own action.
    const handleDetachMonitor = async (component) => {
        try {
            await api.updateMonitor(component.id, { page_id: null });
            toast.success(`${component.name} removed from this page`);
            await loadPageDetails(selectedPage);
        } catch (err) {
            toast.error(err.message || 'Could not remove the monitor');
        }
    };

    const loadPages = async () => {
        try {
            setLoading(true);
            const data = await api.getStatusPages();
            const nextPages = data.pages || [];
            setPages(nextPages);

            const nextSelected = selectedPage
                ? nextPages.find((page) => page.id === selectedPage.id) || nextPages[0]
                : nextPages[0];

            if (nextSelected) {
                await loadPageDetails(nextSelected);
            } else {
                setSelectedPage(null);
                setComponents([]);
                setIncidents([]);
            }
        } catch (err) {
            toast.error(err.message || 'Failed to load status pages');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadPages();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const handlePageNameChange = (name) => {
        setPageForm((prev) => {
            const previousAutoSlug = normalizeSlug(prev.name);
            const shouldSyncSlug = !prev.slug || prev.slug === previousAutoSlug;
            return {
                ...prev,
                name,
                slug: shouldSyncSlug ? normalizeSlug(name) : prev.slug,
            };
        });
    };

    const handleCreatePage = async () => {
        try {
            const page = await api.createStatusPage({
                ...pageForm,
                slug: normalizeSlug(pageForm.slug),
            });
            toast.success('Status page created');
            setShowCreatePage(false);
            setPageForm(defaultPageForm);
            setPages((current) => [...current, page].sort((a, b) => a.name.localeCompare(b.name)));
            await loadPageDetails(page);
        } catch (err) {
            toast.error(err.message || 'Failed to create status page');
        }
    };

    const handleCreateComponent = async () => {
        if (!selectedPage) return;
        try {
            await api.createStatusComponent(selectedPage.id, compForm);
            toast.success('Component added');
            setShowCreateComponent(false);
            setCompForm(defaultCompForm);
            await loadPageDetails(selectedPage);
            await loadPages();
        } catch (err) {
            toast.error(err.message || 'Failed to add component');
        }
    };

    const handleRunCheck = async (component) => {
        try {
            const result = await api.runStatusCheck(component.id);
            toast.success(`Check ${result.status}${result.response_time ? ` in ${result.response_time}ms` : ''}`);
            if (selectedPage) await loadPageDetails(selectedPage);
        } catch (err) {
            toast.error(err.message || 'Check failed');
        }
    };

    const handleCreateIncident = async () => {
        if (!selectedPage) return;
        try {
            await api.createStatusIncident(selectedPage.id, incidentForm);
            toast.success('Incident created');
            setShowCreateIncident(false);
            setIncidentForm(defaultIncidentForm);
            await loadPageDetails(selectedPage);
        } catch (err) {
            toast.error(err.message || 'Failed to create incident');
        }
    };

    const handleUpdateIncidentStatus = async (incident, status) => {
        try {
            const statusLabel = INCIDENT_STATUS.find((item) => item.value === status)?.label || status;
            await api.updateStatusIncident(incident.id, {
                status,
                update_body: status === 'resolved' ? 'Issue has been resolved.' : `Status changed to ${statusLabel}.`,
            });
            toast.success(`Incident set to ${statusLabel}`);
            if (selectedPage) await loadPageDetails(selectedPage);
        } catch (err) {
            toast.error(err.message || 'Failed to update incident');
        }
    };

    const handleCopyUrl = async () => {
        if (!selectedUrl) return;
        if (await copyToClipboard(selectedUrl)) toast.success('Status page URL copied');
        else toast.error('Could not copy URL');
    };

    const handleConfirmDelete = async () => {
        if (!deleteConfirm) return;
        try {
            if (deleteConfirm.type === 'page') {
                await api.deleteStatusPage(deleteConfirm.item.id);
                toast.success('Status page deleted');
                setDeleteConfirm(null);
                setSelectedPage(null);
                setComponents([]);
                setIncidents([]);
                await loadPages();
                return;
            }

            if (deleteConfirm.type === 'component') {
                await api.deleteStatusComponent(deleteConfirm.item.id);
                toast.success('Component deleted');
            }

            if (deleteConfirm.type === 'incident') {
                await api.deleteStatusIncident(deleteConfirm.item.id);
                toast.success('Incident deleted');
            }

            setDeleteConfirm(null);
            if (selectedPage) await loadPageDetails(selectedPage);
        } catch (err) {
            toast.error(err.message || 'Delete failed');
        }
    };

    useTopbarActions(() =>
        (
            <>
                <Button size="sm" variant="outline" onClick={loadPages}>
                    <RefreshCw size={16} />
                    Refresh
                </Button>
                {isAdmin && (
                    <Button size="sm" onClick={() => setShowCreatePage(true)}>
                        <Plus size={16} />
                        Create Page
                    </Button>
                )}
            </>
        ),
        [isAdmin]
    );

    if (loading) return <PageLoader />;

    return (
        <div className="sk-tabgroup__inner status-pages-page">
            <div className="status-layout">
                <aside className="status-pages-list" aria-label="Status pages">
                    {pages.map((page) => (
                        <button
                            key={page.id}
                            type="button"
                            className={`status-page-item ${selectedPage?.id === page.id ? 'active' : ''}`}
                            onClick={() => loadPageDetails(page)}
                        >
                            <span className="status-page-item__top">
                                <span className="status-page-item__name">{page.name}</span>
                                <Pill kind={page.is_public ? 'green' : 'gray'} dot={false}>
                                    {page.is_public ? 'Public' : 'Private'}
                                </Pill>
                            </span>
                            <span className="status-page-item__slug">/status/{page.slug}</span>
                            <span className="status-page-item__meta">
                                <Globe2 size={13} />
                                {page.component_count} component{page.component_count !== 1 ? 's' : ''}
                            </span>
                        </button>
                    ))}
                    {pages.length === 0 && (
                        <EmptyState icon={Activity} title="No status pages yet" />
                    )}
                </aside>

                {selectedPage ? (
                    <section className="status-detail-panel">
                        <div className="status-detail-panel__hero">
                            <div>
                                <Pill kind={overallMeta.pill} className="status-overall-pill">
                                    {overallMeta.label}
                                </Pill>
                                <h2>{selectedPage.name}</h2>
                                {selectedPage.description && <p>{selectedPage.description}</p>}
                                {components.length > 0 && (
                                    <div className="comp-dots" aria-hidden="true">
                                        {components.map((component) => {
                                            const meta = STATUS_META[component.status] || STATUS_META.operational;
                                            return <i key={component.id} className={meta.dot} title={component.name} />;
                                        })}
                                    </div>
                                )}
                            </div>
                            <div className="status-url-card">
                                <span>Public URL</span>
                                <code>{selectedUrl}</code>
                                <div>
                                    <Button size="sm" variant="outline" onClick={handleCopyUrl}>
                                        <Copy size={14} />
                                        Copy
                                    </Button>
                                    <Button size="sm" asChild>
                                        <a href={selectedUrl} target="_blank" rel="noreferrer">
                                            <ExternalLink size={14} />
                                            Open
                                        </a>
                                    </Button>
                                </div>
                            </div>
                        </div>

                        <div className="status-detail-metrics">
                            <div className="sk-spec-card">
                                <div className="sk-spec-card__label">Components</div>
                                <div className="sk-spec-card__value">{components.length}</div>
                            </div>
                            <div className="sk-spec-card">
                                <div className="sk-spec-card__label">Active incidents</div>
                                <div className="sk-spec-card__value">{activeIncidents.length}</div>
                            </div>
                            <div className="sk-spec-card">
                                <div className="sk-spec-card__label">30 day uptime</div>
                                <div className="sk-spec-card__value">{formatUptime(
                                    components.length
                                        ? components.reduce((total, component) => total + (component.uptime_30d || 100), 0) / components.length
                                        : 100
                                )}</div>
                            </div>
                        </div>

                        <Tabs defaultValue="components">
                            <TabsList>
                                <TabsTrigger value="components">Components</TabsTrigger>
                                <TabsTrigger value="incidents">Incidents</TabsTrigger>
                                <TabsTrigger value="settings">Page</TabsTrigger>
                            </TabsList>

                            <TabsContent value="components">
                                <div className="status-actions-bar">
                                    {isAdmin && (
                                        <>
                                            <Button
                                                size="sm"
                                                variant="outline"
                                                onClick={() => setShowAttach(true)}
                                                disabled={unattached.length === 0}
                                                title={unattached.length === 0
                                                    ? 'Every monitor is already on a page'
                                                    : undefined}
                                            >
                                                <Link2 size={14} />
                                                Add existing monitor
                                            </Button>
                                            <Button size="sm" onClick={() => setShowCreateComponent(true)}>
                                                <Plus size={14} />
                                                New component
                                            </Button>
                                        </>
                                    )}
                                </div>

                                <div className="components-list">
                                    {Object.entries(groupedComponents).map(([groupName, groupComponents]) => (
                                        <div key={groupName} className="component-group">
                                            <h3>{groupName}</h3>
                                            {groupComponents.map((component) => {
                                                const meta = STATUS_META[component.status] || STATUS_META.operational;
                                                return (
                                                    <div key={component.id} className="component-row">
                                                        <div className="component-row__info">
                                                            <span className={`status-dot status-dot--${meta.tone}`} />
                                                            <div>
                                                                <strong>{component.name}</strong>
                                                                <span>{component.check_type.toUpperCase()} · {component.check_target || 'No target'}</span>
                                                            </div>
                                                        </div>
                                                        <div className="component-row__stats">
                                                            <Pill kind={meta.pill}>{meta.label}</Pill>
                                                            <span>{formatUptime(component.uptime_30d)} uptime</span>
                                                            <span>{component.last_response_time ? `${component.last_response_time}ms` : 'No response'}</span>
                                                            <span>{formatDate(component.last_check_at)}</span>
                                                        </div>
                                                        {isAdmin && (
                                                            <div className="component-row__actions">
                                                                <Button size="sm" variant="outline" onClick={() => handleRunCheck(component)}>
                                                                    <PlayCircle size={14} />
                                                                    Check
                                                                </Button>
                                                                <Button
                                                                    size="sm"
                                                                    variant="ghost"
                                                                    onClick={() => handleDetachMonitor(component)}
                                                                    title="Remove from this page — the monitor keeps running"
                                                                >
                                                                    <Unlink size={14} />
                                                                </Button>
                                                                <Button
                                                                    size="sm"
                                                                    variant="ghost"
                                                                    onClick={() => setDeleteConfirm({ type: 'component', item: component })}
                                                                    title="Delete the monitor and its history"
                                                                >
                                                                    <Trash2 size={14} />
                                                                </Button>
                                                            </div>
                                                        )}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    ))}
                                    {components.length === 0 && (
                                        <EmptyState icon={Activity} title="No components yet" />
                                    )}
                                </div>
                            </TabsContent>

                            <TabsContent value="incidents">
                                <div className="status-actions-bar">
                                    {isAdmin && (
                                        <Button size="sm" onClick={() => setShowCreateIncident(true)}>
                                            <Plus size={14} />
                                            Create Incident
                                        </Button>
                                    )}
                                </div>
                                <div className="incidents-list">
                                    {incidents.map((incident) => (
                                        <article key={incident.id} className={`incident-row incident-row--${incident.status}`}>
                                            <div className="incident-row__header">
                                                <div>
                                                    <strong>{incident.title}</strong>
                                                    <span>{formatDate(incident.created_at)}</span>
                                                </div>
                                                <div className="incident-row__badges">
                                                    <span className={`inc-state inc-state--${incident.status}`}>
                                                        {incident.status}
                                                    </span>
                                                    <span className={`inc-impact inc-impact--${incident.impact}`}>
                                                        {incident.impact}
                                                    </span>
                                                </div>
                                            </div>
                                            {incident.body && <p>{incident.body}</p>}
                                            {incident.updates?.length > 0 && (
                                                <div className="incident-timeline">
                                                    {incident.updates.map((update) => (
                                                        <div key={update.id}>
                                                            <span>{formatDate(update.created_at)}</span>
                                                            <strong>{update.status}</strong>
                                                            <p>{update.body}</p>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                            {isAdmin && (
                                                <div className="incident-row__actions">
                                                    {incident.status !== 'resolved' && (
                                                        <>
                                                            {INCIDENT_STATUS.filter((status) => status.value !== incident.status).map((status) => (
                                                                <Button
                                                                    key={status.value}
                                                                    size="sm"
                                                                    variant={status.value === 'resolved' ? 'secondary' : 'outline'}
                                                                    onClick={() => handleUpdateIncidentStatus(incident, status.value)}
                                                                >
                                                                    {status.label}
                                                                </Button>
                                                            ))}
                                                        </>
                                                    )}
                                                    <Button size="sm" variant="ghost" onClick={() => setDeleteConfirm({ type: 'incident', item: incident })}>
                                                        <Trash2 size={14} />
                                                    </Button>
                                                </div>
                                            )}
                                        </article>
                                    ))}
                                    {incidents.length === 0 && (
                                        <EmptyState icon={CheckCircle2} title="No incidents" />
                                    )}
                                </div>
                            </TabsContent>

                            <TabsContent value="settings">
                                <div className="status-page-settings">
                                    <div>
                                        <span>Slug</span>
                                        <strong>/{selectedPage.slug}</strong>
                                    </div>
                                    <div>
                                        <span>Visibility</span>
                                        <Pill kind={selectedPage.is_public ? 'green' : 'gray'}>
                                            {selectedPage.is_public ? 'Public' : 'Private'}
                                        </Pill>
                                    </div>
                                    <div>
                                        <span>Created</span>
                                        <strong>{formatDate(selectedPage.created_at)}</strong>
                                    </div>
                                    {isAdmin && (
                                        <Button variant="destructive" onClick={() => setDeleteConfirm({ type: 'page', item: selectedPage })}>
                                            <Trash2 size={16} />
                                            Delete Page
                                        </Button>
                                    )}
                                </div>
                            </TabsContent>
                        </Tabs>
                    </section>
                ) : (
                    <section className="status-detail-panel status-detail-panel--empty">
                        <EmptyState icon={Globe2} title="Select a status page" />
                    </section>
                )}
            </div>

            <Modal
                open={showCreatePage}
                onClose={() => setShowCreatePage(false)}
                title="Create Status Page"
                size="lg"
                className="status-modal"
                footer={(
                    <>
                        <Button variant="outline" onClick={() => setShowCreatePage(false)}>Cancel</Button>
                        <Button onClick={handleCreatePage} disabled={!pageForm.name.trim() || !pageForm.slug.trim()}>
                            Create
                        </Button>
                    </>
                )}
            >
                <div className="form-group">
                    <label>Name</label>
                    <Input value={pageForm.name} onChange={(e) => handlePageNameChange(e.target.value)} autoFocus />
                </div>
                <div className="form-group">
                    <label>Slug</label>
                    <Input
                        value={pageForm.slug}
                        onChange={(e) => setPageForm({ ...pageForm, slug: normalizeSlug(e.target.value) })}
                        placeholder="my-services"
                    />
                    <span className="form-help">/status/{pageForm.slug || 'my-services'}</span>
                </div>
                <div className="form-group">
                    <label>Description</label>
                    <Textarea
                        value={pageForm.description}
                        onChange={(e) => setPageForm({ ...pageForm, description: e.target.value })}
                        rows={3}
                    />
                </div>
            </Modal>

            <Modal
                open={showAttach}
                onClose={() => setShowAttach(false)}
                title="Add an existing monitor"
                size="md"
                className="status-modal"
                footer={<Button variant="outline" onClick={() => setShowAttach(false)}>Close</Button>}
            >
                <p className="form-help">
                    These monitors are already running and are not on any status page yet.
                    Adding one publishes it here — it keeps the history it has already collected.
                </p>
                <div className="status-attach-list">
                    {unattached.map((monitor) => (
                        <button
                            key={monitor.id}
                            type="button"
                            className="status-attach-row"
                            onClick={() => handleAttachMonitor(monitor)}
                        >
                            <span className="status-attach-row__body">
                                <strong>{monitor.name}</strong>
                                <span>{monitor.check_type.toUpperCase()} · {monitor.check_target || 'bound site'}</span>
                            </span>
                            <Pill kind={(STATUS_META[monitor.status] || STATUS_META.operational).pill}>
                                {(STATUS_META[monitor.status] || STATUS_META.operational).label}
                            </Pill>
                        </button>
                    ))}
                    {unattached.length === 0 && (
                        <p className="form-help">Every monitor is already on a page.</p>
                    )}
                </div>
            </Modal>

            <Modal
                open={showCreateComponent}
                onClose={() => setShowCreateComponent(false)}
                title="Add Component"
                size="lg"
                className="status-modal"
                footer={(
                    <>
                        <Button variant="outline" onClick={() => setShowCreateComponent(false)}>Cancel</Button>
                        <Button onClick={handleCreateComponent} disabled={!compForm.name.trim() || !compForm.check_target.trim()}>
                            Add Component
                        </Button>
                    </>
                )}
            >
                <div className="status-modal-grid">
                    <div className="form-group">
                        <label>Name</label>
                        <Input value={compForm.name} onChange={(e) => setCompForm({ ...compForm, name: e.target.value })} autoFocus />
                    </div>
                    <div className="form-group">
                        <label>Group</label>
                        <Input value={compForm.group} onChange={(e) => setCompForm({ ...compForm, group: e.target.value })} />
                    </div>
                    <div className="form-group">
                        <label>Check Type</label>
                        <select
                            className="form-select"
                            value={compForm.check_type}
                            onChange={(e) => setCompForm({ ...compForm, check_type: e.target.value })}
                        >
                            <option value="http">HTTP</option>
                            <option value="tcp">TCP</option>
                            <option value="dns">DNS</option>
                            <option value="ping">Ping</option>
                        </select>
                    </div>
                    <div className="form-group">
                        <label>Target</label>
                        <Input
                            value={compForm.check_target}
                            onChange={(e) => setCompForm({ ...compForm, check_target: e.target.value })}
                            placeholder={CHECK_TARGET_PLACEHOLDERS[compForm.check_type]}
                        />
                    </div>
                    <div className="form-group">
                        <label>Interval</label>
                        <Input
                            type="number"
                            min="30"
                            value={compForm.check_interval}
                            onChange={(e) => setCompForm({ ...compForm, check_interval: parseInt(e.target.value, 10) || 60 })}
                        />
                    </div>
                    <div className="form-group">
                        <label>Timeout</label>
                        <Input
                            type="number"
                            min="1"
                            value={compForm.check_timeout}
                            onChange={(e) => setCompForm({ ...compForm, check_timeout: parseInt(e.target.value, 10) || 10 })}
                        />
                    </div>
                </div>
            </Modal>

            <Modal
                open={showCreateIncident}
                onClose={() => setShowCreateIncident(false)}
                title="Create Incident"
                size="lg"
                className="status-modal"
                footer={(
                    <>
                        <Button variant="outline" onClick={() => setShowCreateIncident(false)}>Cancel</Button>
                        <Button onClick={handleCreateIncident} disabled={!incidentForm.title.trim()}>
                            Create Incident
                        </Button>
                    </>
                )}
            >
                <div className="form-group">
                    <label>Title</label>
                    <Input value={incidentForm.title} onChange={(e) => setIncidentForm({ ...incidentForm, title: e.target.value })} autoFocus />
                </div>
                <div className="status-modal-grid">
                    <div className="form-group">
                        <label>Status</label>
                        <select
                            className="form-select"
                            value={incidentForm.status}
                            onChange={(e) => setIncidentForm({ ...incidentForm, status: e.target.value })}
                        >
                            {INCIDENT_STATUS.filter((status) => status.value !== 'resolved').map((status) => (
                                <option key={status.value} value={status.value}>{status.label}</option>
                            ))}
                        </select>
                    </div>
                    <div className="form-group">
                        <label>Impact</label>
                        <select
                            className="form-select"
                            value={incidentForm.impact}
                            onChange={(e) => setIncidentForm({ ...incidentForm, impact: e.target.value })}
                        >
                            {IMPACT_OPTIONS.map((impact) => (
                                <option key={impact.value} value={impact.value}>{impact.label}</option>
                            ))}
                        </select>
                    </div>
                </div>
                <div className="form-group">
                    <label>Description</label>
                    <Textarea
                        value={incidentForm.body}
                        onChange={(e) => setIncidentForm({ ...incidentForm, body: e.target.value })}
                        rows={4}
                    />
                </div>
            </Modal>

            <ConfirmDialog
                isOpen={Boolean(deleteConfirm)}
                title={`Delete ${deleteConfirm?.type || 'item'}?`}
                message="This removes the selected record and related status data."
                confirmText="Delete"
                requireConfirmation={deleteConfirm?.item?.name || deleteConfirm?.item?.title}
                onConfirm={handleConfirmDelete}
                onCancel={() => setDeleteConfirm(null)}
            />
        </div>
    );
};

export default StatusPages;
