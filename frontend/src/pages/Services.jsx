import { useState, useEffect, useMemo } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Layers, Plus, Square, Play, RotateCw, GitBranch, Github, FolderOpen, FileArchive, FolderKanban, ArrowDownToLine } from 'lucide-react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import { getServiceType, getStatusConfig, formatRelativeTime } from '../utils/serviceTypes';
import ResourceListPage from '../components/layouts/ResourceListPage';
import BandwidthSparkline from '../components/BandwidthSparkline';
import { formatBytes } from '../utils/formatBytes';
import { Pill, ServiceTile, EnvTag, SearchField } from '@/components/ds';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
} from '@/components/ui/dialog';
import RequiresDocker from '../components/RequiresDocker';

const STATUS_PILL = { running: 'green', stopped: 'gray', deploying: 'amber', building: 'amber', failed: 'red' };

// Severity order for status sorting — also the page's default row order.
const STATUS_SORT_ORDER = { running: 0, deploying: 1, building: 2, stopped: 3, failed: 4 };

// Sentinels for the move-to-project Select (Radix forbids empty-string values).
const UNASSIGN = '__unassign__';
const NO_ENV = '__no_env__';

const Services = () => {
    const navigate = useNavigate();
    const toast = useToast();
    const [apps, setApps] = useState([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [statusFilter, setStatusFilter] = useState('all');
    const [actionLoading, setActionLoading] = useState(null);
    const [selectedIds, setSelectedIds] = useState(new Set());
    const [bulkLoading, setBulkLoading] = useState(false);
    const [showMoveDialog, setShowMoveDialog] = useState(false);
    const [bandwidth, setBandwidth] = useState({});

    useEffect(() => {
        loadApps();
        // Best-effort: one call for every row's sparkline; absence is fine.
        api.getBandwidthApps()
            .then((data) => setBandwidth(data?.apps || {}))
            .catch(() => {});
    }, []);

    async function loadApps() {
        try {
            const data = await api.getApps();
            setApps(data.apps || []);
        } catch (err) {
            toast.error('Failed to load services');
        } finally {
            setLoading(false);
        }
    }

    async function handleAction(e, appId, action) {
        e.stopPropagation();
        setActionLoading(`${appId}-${action}`);
        try {
            if (action === 'start') await api.startApp(appId);
            else if (action === 'stop') await api.stopApp(appId);
            else if (action === 'restart') await api.restartApp(appId);
            await loadApps();
        } catch (err) {
            toast.error(`Failed to ${action} service`);
        } finally {
            setActionLoading(null);
        }
    }

    async function handleBulkAction(action) {
        if (selectedIds.size === 0) return;
        setBulkLoading(true);
        try {
            const promises = [...selectedIds].map(id => {
                if (action === 'start') return api.startApp(id);
                if (action === 'stop') return api.stopApp(id);
                if (action === 'restart') return api.restartApp(id);
                return Promise.resolve();
            });
            await Promise.allSettled(promises);
            toast.success(`${action} sent to ${selectedIds.size} service(s)`);
            setSelectedIds(new Set());
            await loadApps();
        } catch (err) {
            toast.error(`Bulk ${action} failed`);
        } finally {
            setBulkLoading(false);
        }
    }

    const filteredApps = useMemo(() => {
        const q = searchTerm.trim().toLowerCase();
        return apps
            .filter(app => {
                if (statusFilter !== 'all' && (statusFilter === 'running' ? app.status !== 'running' : app.status === 'running')) return false;
                if (q && !app.name.toLowerCase().includes(q)) return false;
                return true;
            })
            .sort((a, b) => {
                return (STATUS_SORT_ORDER[a.status] ?? 5) - (STATUS_SORT_ORDER[b.status] ?? 5) || a.name.localeCompare(b.name);
            });
    }, [apps, searchTerm, statusFilter]);

    const runningCount = useMemo(() => apps.filter(a => a.status === 'running').length, [apps]);

    useTopbarActions(() =>
        <>
            <Button variant="outline" size="sm" asChild>
                <Link to="/imports">
                    <ArrowDownToLine size={16} />
                    Import a site
                </Link>
            </Button>
            <Button size="sm" asChild>
                <Link to="/services/new">
                    <Plus size={16} />
                    New Service
                </Link>
            </Button>
            <SearchField
                value={searchTerm}
                onSearch={setSearchTerm}
                placeholder="Search services…"
            />
        </>,
        [searchTerm]
    );

    const allSelected = filteredApps.length > 0 && filteredApps.every(a => selectedIds.has(a.id));

    const toggleOne = (id, checked) => {
        setSelectedIds(prev => {
            const next = new Set(prev);
            if (checked) next.add(id);
            else next.delete(id);
            return next;
        });
    };

    // DataTable columns. Interactive cells (checkbox, row actions) stop click
    // propagation so they don't trigger the row's navigate.
    const columns = [
        {
            key: '__select',
            sortable: false,
            hideable: false,
            className: 'wp-list__ck',
            cellClassName: 'wp-list__ck',
            header: (
                <Checkbox
                    checked={allSelected}
                    onCheckedChange={(checked) => {
                        setSelectedIds(checked ? new Set(filteredApps.map(a => a.id)) : new Set());
                    }}
                    aria-label="Select all services"
                />
            ),
            render: (app) => (
                <div onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                        checked={selectedIds.has(app.id)}
                        onCheckedChange={(checked) => toggleOne(app.id, checked)}
                        aria-label={`Select ${app.name}`}
                    />
                </div>
            ),
        },
        {
            key: 'name',
            header: 'Service',
            sortable: true,
            hideable: false,
            render: (app) => {
                const typeInfo = getServiceType(app.app_type);
                return (
                    <div className="sk-cell-name">
                        <ServiceTile name={app.name} size={30} className="wp-list__tile" aria-hidden="true" />
                        <span>
                            <div>{app.name}</div>
                            <div className="sk-cell-sub">{typeInfo.label}</div>
                        </span>
                    </div>
                );
            },
        },
        {
            key: 'project',
            header: 'Project',
            sortable: true,
            // Unassigned services (no project) sort last.
            sortValue: (app) => app.project_name || null,
            render: (app) => (
                app.project_name ? (
                    <span className="services-page__project">
                        <span className="services-page__project-name" title={app.project_name}>
                            <FolderKanban size={12} aria-hidden="true" />
                            {app.project_name}
                        </span>
                        {app.environment_name && (
                            <EnvTag env={app.environment_name}>{app.environment_name}</EnvTag>
                        )}
                    </span>
                ) : (
                    <span className="services-page__unassigned">Unassigned</span>
                )
            ),
        },
        {
            key: 'source',
            header: 'Source',
            render: (app) => {
                const isGithub = (app.deploy_repo_url || '').includes('github.com');
                if (app.deploy_repo_url) {
                    return (
                        <span className="services-page__src-badge" title={app.deploy_repo_url}>
                            {isGithub ? <Github size={12} /> : <GitBranch size={12} />}
                            {extractRepoName(app.deploy_repo_url)}
                        </span>
                    );
                }
                if (app.source === 'manual') {
                    return (
                        <span className="services-page__src-badge services-page__src-badge--manual" title={app.root_path || ''}>
                            <FolderOpen size={12} />
                            Local
                        </span>
                    );
                }
                if (app.source === 'upload') {
                    return (
                        <span className="services-page__src-badge services-page__src-badge--upload" title={app.upload_path || ''}>
                            <FileArchive size={12} />
                            Upload v{app.version || 1}
                        </span>
                    );
                }
                return <span className="wp-list__dash">—</span>;
            },
        },
        {
            key: 'domain',
            header: 'Domain',
            sortable: true,
            sortValue: (app) => (app.domains?.find(d => d.is_primary) || app.domains?.[0])?.name || null,
            cellClassName: 'sk-cell-mono',
            render: (app) => {
                const primaryDomain = (app.domains?.find(d => d.is_primary) || app.domains?.[0])?.name || '';
                return primaryDomain || <span className="wp-list__dash">—</span>;
            },
        },
        {
            key: 'bandwidth',
            header: 'Transfer',
            render: (app) => {
                const bw = bandwidth[String(app.id)];
                if (!bw || !bw.series30?.some(v => v > 0)) {
                    return <span className="wp-list__dash">—</span>;
                }
                return (
                    <span className="bw-cell" title="Transfer — last 30 days">
                        <BandwidthSparkline data={bw.series30} width={72} height={20} />
                        <span className="bw-cell__month">{formatBytes(bw.month_bytes)}/mo</span>
                    </span>
                );
            },
        },
        {
            key: 'status',
            header: 'Status',
            sortable: true,
            // Same severity order as the page's default ordering, not alphabet.
            sortValue: (app) => STATUS_SORT_ORDER[app.status] ?? 5,
            render: (app) => <Pill kind={STATUS_PILL[app.status] || 'gray'}>{getStatusConfig(app.status).label}</Pill>,
        },
        {
            key: 'last_deploy',
            header: 'Last Deploy',
            sortable: true,
            // Numeric timestamp sort; never-deployed services sort last.
            sortValue: (app) => (app.last_deploy_at ? new Date(app.last_deploy_at).getTime() : null),
            cellClassName: 'sk-cell-mono',
            render: (app) => (
                app.last_deploy_at ? formatRelativeTime(app.last_deploy_at) : <span className="wp-list__dash">—</span>
            ),
        },
        {
            key: '__actions',
            header: '',
            width: 70,
            sortable: false,
            hideable: false,
            render: (app) => {
                const isRunning = app.status === 'running';
                return (
                    <div className="services-page__actions" onClick={(e) => e.stopPropagation()}>
                        {isRunning ? (
                            <>
                                <Button variant="ghost" size="sm" onClick={(e) => handleAction(e, app.id, 'restart')} disabled={actionLoading === `${app.id}-restart`} title="Restart">
                                    <RotateCw size={14} />
                                </Button>
                                <Button variant="ghost" size="sm" onClick={(e) => handleAction(e, app.id, 'stop')} disabled={actionLoading === `${app.id}-stop`} title="Stop">
                                    <Square size={14} />
                                </Button>
                            </>
                        ) : (
                            <Button variant="ghost" size="sm" onClick={(e) => handleAction(e, app.id, 'start')} disabled={actionLoading === `${app.id}-start`} title="Start">
                                <Play size={14} />
                            </Button>
                        )}
                    </div>
                );
            },
        },
    ];

    return (
        <RequiresDocker what="Services">
        <ResourceListPage
            className="services-page"
            loading={loading}
            loadingTitle="Loading services..."
            storageKey="serverkit-list-services"
            viewPageKey="services"
            builtinViews={[
                { name: 'Running', state: { filter: 'running', search: '', sorts: [], hiddenKeys: [] } },
                { name: 'Stopped', state: { filter: 'stopped', search: '', sorts: [], hiddenKeys: [] } },
                { name: 'Recently deployed', state: { filter: 'all', search: '', sorts: [{ key: 'last_deploy', direction: 'desc' }], hiddenKeys: [] } },
            ]}
            totalCount={apps.length}
            items={filteredApps}
            columns={columns}
            keyField="id"
            onRowClick={(app) => navigate(app.app_type === 'wordpress' ? `/wordpress/${app.id}` : `/services/${app.id}`)}
            rowClassName={(app) => (selectedIds.has(app.id) ? 'is-selected' : '')}
            filters={[
                { value: 'all', label: 'All', count: apps.length },
                { value: 'running', label: 'Running', count: runningCount },
                { value: 'stopped', label: 'Stopped', count: apps.length - runningCount },
            ]}
            activeFilter={statusFilter}
            onFilterChange={setStatusFilter}
            selectedCount={selectedIds.size}
            onClearSelection={() => setSelectedIds(new Set())}
            bulkActions={
                <>
                    <Button variant="outline" size="sm" onClick={() => setShowMoveDialog(true)} disabled={bulkLoading}>
                        <FolderKanban size={14} />
                        Move to project
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => handleBulkAction('restart')} disabled={bulkLoading}>Restart All</Button>
                    <Button variant="outline" size="sm" onClick={() => handleBulkAction('stop')} disabled={bulkLoading}>Stop All</Button>
                    <Button variant="outline" size="sm" onClick={() => handleBulkAction('start')} disabled={bulkLoading}>Start All</Button>
                </>
            }
            emptyIcon={Layers}
            emptyTitle="No services found"
            emptyDescription="Connect a repository or install a template to get started"
            emptyAction={
                <Button asChild>
                    <Link to="/services/new">Create Service</Link>
                </Button>
            }
            filteredEmptyIcon={Layers}
            filteredEmptyTitle="No services found"
            filteredEmptyDescription="Try adjusting your search or filter"
            viewStorageKey="serverkit.services.view"
            renderCard={(app) => {
                const typeInfo = getServiceType(app.app_type);
                const primaryDomain = (app.domains?.find(d => d.is_primary) || app.domains?.[0])?.name;
                const isRunning = app.status === 'running';
                const bw = bandwidth[String(app.id)];
                return (
                    <>
                        <div className="services-card__top">
                            <ServiceTile name={app.name} size={40} aria-hidden="true" />
                            <div className="services-card__id">
                                <div className="services-card__name">{app.name}</div>
                                <div className="sk-cell-sub">{typeInfo.label}</div>
                            </div>
                            <Pill kind={STATUS_PILL[app.status] || 'gray'}>
                                {getStatusConfig(app.status).label}
                            </Pill>
                        </div>

                        <div className="services-card__domain">
                            {primaryDomain || <span className="wp-list__dash">No domain</span>}
                        </div>

                        <div className="services-card__stats">
                            <div>
                                <span className="l">Project</span>
                                <span className="v">{app.project_name || '—'}</span>
                            </div>
                            <div>
                                <span className="l">Transfer</span>
                                <span className="v">{bw?.month_bytes ? `${formatBytes(bw.month_bytes)}/mo` : '—'}</span>
                            </div>
                            <div>
                                <span className="l">Last deploy</span>
                                <span className="v">
                                    {app.last_deploy_at ? formatRelativeTime(app.last_deploy_at) : '—'}
                                </span>
                            </div>
                        </div>

                        <div className="services-card__foot" onClick={(e) => e.stopPropagation()}>
                            {isRunning ? (
                                <>
                                    <Button variant="ghost" size="sm" onClick={(e) => handleAction(e, app.id, 'restart')} disabled={actionLoading === `${app.id}-restart`} title="Restart">
                                        <RotateCw size={14} />
                                    </Button>
                                    <Button variant="ghost" size="sm" onClick={(e) => handleAction(e, app.id, 'stop')} disabled={actionLoading === `${app.id}-stop`} title="Stop">
                                        <Square size={14} />
                                    </Button>
                                </>
                            ) : (
                                <Button variant="ghost" size="sm" onClick={(e) => handleAction(e, app.id, 'start')} disabled={actionLoading === `${app.id}-start`} title="Start">
                                    <Play size={14} />
                                </Button>
                            )}
                        </div>
                    </>
                );
            }}
        >
            <MoveToProjectDialog
                open={showMoveDialog}
                onOpenChange={setShowMoveDialog}
                count={selectedIds.size}
                onMove={async (projectId, environmentId) => {
                    setBulkLoading(true);
                    try {
                        await api.moveAppsToProject([...selectedIds], projectId, environmentId);
                        toast.success(
                            projectId === null
                                ? `Unassigned ${selectedIds.size} service(s)`
                                : `Moved ${selectedIds.size} service(s)`
                        );
                        setShowMoveDialog(false);
                        setSelectedIds(new Set());
                        await loadApps();
                    } catch (err) {
                        toast.error(err.message || 'Failed to move services');
                    } finally {
                        setBulkLoading(false);
                    }
                }}
            />
        </ResourceListPage>
        </RequiresDocker>
    );
};

// Bulk "Move to project" modal: pick a project, then one of its environments
// (or leave unassigned). Loads the project list lazily on open; fetches the
// chosen project's environments on selection.
const MoveToProjectDialog = ({ open, onOpenChange, count, onMove }) => {
    const toast = useToast();
    const [projects, setProjects] = useState([]);
    const [environments, setEnvironments] = useState([]);
    const [projectValue, setProjectValue] = useState(UNASSIGN);
    const [envValue, setEnvValue] = useState(NO_ENV);
    const [loadingProjects, setLoadingProjects] = useState(false);
    const [loadingEnvs, setLoadingEnvs] = useState(false);
    const [submitting, setSubmitting] = useState(false);

    useEffect(() => {
        if (!open) return;
        // Reset selection each time the dialog opens.
        setProjectValue(UNASSIGN);
        setEnvValue(NO_ENV);
        setEnvironments([]);
        setLoadingProjects(true);
        api.getProjects()
            .then((data) => setProjects(Array.isArray(data?.projects) ? data.projects : []))
            .catch(() => toast.error('Failed to load projects'))
            .finally(() => setLoadingProjects(false));
    }, [open, toast]);

    async function handleProjectChange(value) {
        setProjectValue(value);
        setEnvValue(NO_ENV);
        setEnvironments([]);
        if (value === UNASSIGN) return;
        setLoadingEnvs(true);
        try {
            const data = await api.getProject(value);
            const envs = Array.isArray(data?.project?.environments) ? data.project.environments : [];
            setEnvironments(envs);
        } catch {
            toast.error('Failed to load environments');
        } finally {
            setLoadingEnvs(false);
        }
    }

    async function handleSubmit() {
        const projectId = projectValue === UNASSIGN ? null : Number(projectValue);
        const environmentId = envValue === NO_ENV ? null : Number(envValue);
        setSubmitting(true);
        try {
            await onMove(projectId, environmentId);
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Move to project</DialogTitle>
                    <DialogDescription>
                        Assign {count} selected service{count === 1 ? '' : 's'} to a project and
                        environment, or leave them unassigned.
                    </DialogDescription>
                </DialogHeader>

                <div className="services-move">
                    <div className="services-move__field">
                        <Label htmlFor="move-project">Project</Label>
                        <Select value={projectValue} onValueChange={handleProjectChange} disabled={loadingProjects}>
                            <SelectTrigger id="move-project">
                                <SelectValue placeholder={loadingProjects ? 'Loading…' : 'Select a project'} />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value={UNASSIGN}>Unassigned</SelectItem>
                                {projects.map((p) => (
                                    <SelectItem key={p.id} value={String(p.id)}>{p.name}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    {projectValue !== UNASSIGN && (
                        <div className="services-move__field">
                            <Label htmlFor="move-env">Environment</Label>
                            <Select value={envValue} onValueChange={setEnvValue} disabled={loadingEnvs}>
                                <SelectTrigger id="move-env">
                                    <SelectValue placeholder={loadingEnvs ? 'Loading…' : 'No specific environment'} />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value={NO_ENV}>No specific environment</SelectItem>
                                    {environments.map((e) => (
                                        <SelectItem key={e.id} value={String(e.id)}>{e.name}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                    )}
                </div>

                <DialogFooter>
                    <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                        Cancel
                    </Button>
                    <Button type="button" onClick={handleSubmit} disabled={submitting || loadingProjects}>
                        {submitting ? 'Moving…' : (projectValue === UNASSIGN ? 'Unassign' : 'Move')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};

function extractRepoName(url) {
    if (!url) return '';
    try {
        const cleaned = url.replace(/\.git$/, '').replace(/^https?:\/\/[^@]+@/, 'https://');
        const parts = cleaned.split(/[/:]/).filter(Boolean);
        return parts.slice(-2).join('/');
    } catch {
        return url;
    }
}

export default Services;
