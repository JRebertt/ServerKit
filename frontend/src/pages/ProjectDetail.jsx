import { useState, useEffect, useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
    FolderKanban,
    Plus,
    ArrowLeft,
    ArrowUp,
    ArrowDown,
    Trash2,
    Boxes,
    ExternalLink,
} from 'lucide-react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import EmptyState from '../components/EmptyState';
import { ConfirmDialog } from '../components/ConfirmDialog';
import PageLayout from '../layouts/PageLayout';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
} from '@/components/ui/dialog';

const ProjectDetail = () => {
    const { id } = useParams();
    const toast = useToast();

    const [project, setProject] = useState(null);
    const [environments, setEnvironments] = useState([]);
    const [apps, setApps] = useState([]);
    const [activeEnvId, setActiveEnvId] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [showCreateEnv, setShowCreateEnv] = useState(false);
    const [deleteEnv, setDeleteEnv] = useState(null);
    const [manifest, setManifest] = useState(null);

    const loadProject = useCallback(async () => {
        setLoading(true);
        try {
            const [projectData, appsData, manifestData] = await Promise.all([
                api.getProject(id),
                api.getApps(),
                api.getManifest(id).catch(() => null),
            ]);
            setManifest(manifestData?.manifest || null);
            const p = projectData?.project || null;
            setProject(p);
            const envs = Array.isArray(p?.environments) ? p.environments : [];
            setEnvironments(envs);
            setActiveEnvId(prev => {
                if (prev && envs.some(e => e.id === prev)) return prev;
                const def = envs.find(e => e.is_default) || envs[0];
                return def ? def.id : null;
            });
            const allApps = Array.isArray(appsData?.apps) ? appsData.apps : [];
            setApps(allApps.filter(a => String(a.project_id) === String(id)));
            setError(null);
        } catch (err) {
            setError(err.message || 'Failed to load project');
        } finally {
            setLoading(false);
        }
    }, [id]);

    useEffect(() => {
        loadProject();
    }, [loadProject]);

    async function handleReorder(envId, direction) {
        const idx = environments.findIndex(e => e.id === envId);
        const target = idx + direction;
        if (idx < 0 || target < 0 || target >= environments.length) return;
        const next = [...environments];
        [next[idx], next[target]] = [next[target], next[idx]];
        setEnvironments(next);
        try {
            await api.reorderEnvironments(Number(id), next.map(e => e.id));
        } catch (err) {
            toast.error(err.message || 'Failed to reorder environments');
            loadProject();
        }
    }

    async function handleDeleteEnvironment() {
        if (!deleteEnv) return;
        try {
            await api.deleteEnvironment(deleteEnv.id);
            toast.success(`Environment "${deleteEnv.name}" deleted`);
            setDeleteEnv(null);
            loadProject();
        } catch (err) {
            toast.error(err.message || 'Failed to delete environment');
            setDeleteEnv(null);
        }
    }

    // Loading / not-found take the same shell as the loaded page, so the top
    // bar does not appear, move, or vanish as the project resolves.
    if (loading) {
        return (
            <PageLayout className="project-detail-page" icon={<FolderKanban size={20} />} title="Project">
                <EmptyState loading loadingVariant="detail" title="Loading project" />
            </PageLayout>
        );
    }

    if (error || !project) {
        return (
            <PageLayout className="project-detail-page" icon={<FolderKanban size={20} />} title="Project">
                <EmptyState
                    icon={FolderKanban}
                    title="Project not found"
                    description={error || 'This project could not be loaded.'}
                    action={
                        <Button variant="outline" asChild>
                            <Link to="/projects"><ArrowLeft size={16} /> Back to Projects</Link>
                        </Button>
                    }
                />
            </PageLayout>
        );
    }

    const activeEnv = environments.find(e => e.id === activeEnvId) || null;
    const envApps = apps.filter(a => String(a.environment_id) === String(activeEnvId));
    const unassignedApps = apps.filter(a => !a.environment_id);

    return (
        <PageLayout
            className="project-detail-page"
            icon={<FolderKanban size={20} />}
            title={project.name}
            meta={project.slug}
            actions={
                <>
                    <Button variant="outline" asChild>
                        <Link to="/projects"><ArrowLeft size={16} /> Projects</Link>
                    </Button>
                    <Button onClick={() => setShowCreateEnv(true)}>
                        <Plus size={16} /> New Environment
                    </Button>
                </>
            }
        >
            <div className="project-detail-page__body">
                {project.description && (
                    <p className="project-detail-page__description">{project.description}</p>
                )}

                {manifest && (() => {
                    const src = manifest.source || {};
                    const commit = src.commit ? String(src.commit).slice(0, 7) : null;
                    const status = manifest.status || 'pending';
                    return (
                        <div className="project-manifest-strip">
                            <span className="project-manifest-strip__label">Manifest</span>
                            <span className={`project-manifest-strip__pill project-manifest-strip__pill--${status}`}>
                                {status}
                            </span>
                            {(src.repo || commit) && (
                                <span className="project-manifest-strip__source">
                                    {src.repo || ''}{src.repo && commit ? '@' : ''}{commit || ''}
                                </span>
                            )}
                        </div>
                    );
                })()}

                <div className="project-env-tabs" role="tablist" aria-label="Environments">
                    {environments.map((env, index) => (
                        <div
                            key={env.id}
                            className={`project-env-tab ${env.id === activeEnvId ? 'is-active' : ''}`}
                        >
                            <button
                                type="button"
                                role="tab"
                                aria-selected={env.id === activeEnvId}
                                className="project-env-tab__label"
                                onClick={() => setActiveEnvId(env.id)}
                            >
                                {env.name}
                                {env.is_default && <Badge variant="outline">default</Badge>}
                                <span className="project-env-tab__count">{env.app_count ?? 0}</span>
                            </button>
                            <div className="project-env-tab__controls">
                                <button
                                    type="button"
                                    title="Move up"
                                    aria-label={`Move ${env.name} up`}
                                    disabled={index === 0}
                                    onClick={() => handleReorder(env.id, -1)}
                                >
                                    <ArrowUp size={13} />
                                </button>
                                <button
                                    type="button"
                                    title="Move down"
                                    aria-label={`Move ${env.name} down`}
                                    disabled={index === environments.length - 1}
                                    onClick={() => handleReorder(env.id, 1)}
                                >
                                    <ArrowDown size={13} />
                                </button>
                                <button
                                    type="button"
                                    className="project-env-tab__delete"
                                    title="Delete environment"
                                    aria-label={`Delete ${env.name}`}
                                    disabled={environments.length <= 1}
                                    onClick={() => setDeleteEnv(env)}
                                >
                                    <Trash2 size={13} />
                                </button>
                            </div>
                        </div>
                    ))}
                </div>

                <div className="project-env-panel" role="tabpanel">
                    {activeEnv ? (
                        <>
                            <div className="project-env-panel__header">
                                <h2>{activeEnv.name}</h2>
                                <span>{envApps.length} app{envApps.length === 1 ? '' : 's'}</span>
                            </div>
                            {envApps.length === 0 ? (
                                <EmptyState
                                    icon={Boxes}
                                    size="sm"
                                    title="No apps in this environment"
                                    description="Assign apps to this environment when creating them, or move existing apps here."
                                />
                            ) : (
                                <AppList apps={envApps} />
                            )}
                        </>
                    ) : (
                        <EmptyState
                            icon={FolderKanban}
                            title="No environments"
                            description="Add an environment to start organizing this project's apps."
                        />
                    )}
                </div>

                {unassignedApps.length > 0 && (
                    <div className="project-unassigned">
                        <div className="project-unassigned__header">
                            <h3>In this project, no environment</h3>
                            <span>{unassignedApps.length}</span>
                        </div>
                        <AppList apps={unassignedApps} />
                    </div>
                )}
            </div>

            <CreateEnvironmentDialog
                projectId={Number(id)}
                open={showCreateEnv}
                onOpenChange={setShowCreateEnv}
                onCreated={() => {
                    setShowCreateEnv(false);
                    loadProject();
                }}
            />

            <ConfirmDialog
                isOpen={Boolean(deleteEnv)}
                title={`Delete environment "${deleteEnv?.name || ''}"?`}
                message="Apps assigned to this environment will stay in the project but lose their environment assignment. This cannot be undone."
                confirmText="Delete environment"
                variant="danger"
                onConfirm={handleDeleteEnvironment}
                onCancel={() => setDeleteEnv(null)}
            />
        </PageLayout>
    );
};

const AppList = ({ apps }) => (
    <ul className="project-app-list">
        {apps.map(app => (
            <li key={app.id} className="project-app-row">
                <span className={`project-app-row__status project-app-row__status--${app.status || 'stopped'}`} aria-hidden="true" />
                <Link to={`/services/${app.id}`} className="project-app-row__name">
                    {app.name}
                </Link>
                <span className="project-app-row__type">{app.app_type}</span>
                <span className={`status-pill status-pill--${app.status || 'stopped'}`}>
                    {app.status || 'stopped'}
                </span>
                <Link to={`/services/${app.id}`} className="project-app-row__link" aria-label={`Open ${app.name}`}>
                    <ExternalLink size={14} />
                </Link>
            </li>
        ))}
    </ul>
);

const CreateEnvironmentDialog = ({ projectId, open, onOpenChange, onCreated }) => {
    const [name, setName] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const toast = useToast();

    async function handleSubmit(e) {
        e.preventDefault();
        if (!name.trim()) {
            toast.error('Environment name is required');
            return;
        }
        setSubmitting(true);
        try {
            await api.createEnvironment(projectId, { name: name.trim() });
            toast.success('Environment created');
            setName('');
            onCreated();
        } catch (err) {
            toast.error(err.message || 'Failed to create environment');
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={(v) => { if (!v) setName(''); onOpenChange(v); }}>
            <DialogContent>
                <form onSubmit={handleSubmit}>
                    <DialogHeader>
                        <DialogTitle>New Environment</DialogTitle>
                        <DialogDescription>
                            Common names are production, staging, and development — but any name works.
                        </DialogDescription>
                    </DialogHeader>

                    <div className="projects-form">
                        <div className="projects-form__field">
                            <Label htmlFor="env-name">Name</Label>
                            <Input
                                id="env-name"
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                placeholder="staging"
                                autoFocus
                                required
                            />
                        </div>
                    </div>

                    <DialogFooter>
                        <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                            Cancel
                        </Button>
                        <Button type="submit" disabled={submitting || !name.trim()}>
                            {submitting ? 'Creating…' : 'Create Environment'}
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
};

export default ProjectDetail;
