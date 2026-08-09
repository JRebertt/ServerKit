import { useState, useEffect, useMemo } from 'react';
import useTabParam from '../hooks/useTabParam';
import { api } from '../services/api';
import { useToast } from '../contexts/ToastContext';
import ConfirmDialog from '../components/ConfirmDialog';
import { DangerZone } from '../components/DangerZone';
import EmptyState from '../components/EmptyState';
import Modal from '@/components/Modal';
import {
    Pill, MetricCard, SegControl, Drawer, DataTable, SortMenu, ColumnsMenu, DataTableFooter,
    ListToolbar,
} from '../components/ds';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import PageLayout from '../layouts/PageLayout';
import {
    AlertCircle, FolderGit2, Webhook, Rocket, Server, Globe, Terminal, Tag,
    GitBranch, RefreshCw, Plus, ExternalLink, Lock, Trash2, ChevronRight,
    Clock, AlertTriangle, Settings,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';

const VALID_TABS = ['overview', 'repositories', 'access', 'webhooks', 'deployments', 'settings'];

const SOURCE_INITIALS = { github: 'GH', gitlab: 'GL', bitbucket: 'BB' };

const getStatusColor = (status) => {
    switch (status) {
        case 'success': return 'green';
        case 'failed': return 'red';
        case 'running': return 'amber';
        default: return 'gray';
    }
};

const formatDate = (dateString) => {
    if (!dateString) return 'Unknown';
    const date = new Date(dateString);
    const now = new Date();
    const diff = now - date;
    if (diff < 60000) return 'just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    if (diff < 604800000) return `${Math.floor(diff / 86400000)}d ago`;
    return date.toLocaleDateString();
};

// Columns for the shared DataTable. Cell markup and classNames are identical
// to the hand-rolled tables they replace, so _git.scss keeps applying
// (.sk-cell-name, .git-reponame, .git-branch-chip, .git-url, .dom-chev).
const REPO_COLUMNS = [
    {
        key: 'name',
        header: 'Repository',
        sortable: true,
        hideable: false,
        sortValue: (repo) => repo.name || '',
        render: (repo) => (
            <div className="sk-cell-name">
                <span className="dom-fav git-repo-ico">
                    {repo.private ? (
                        <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" fill="none" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                    ) : (
                        <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" fill="none" strokeWidth="2"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 0 0 9 9"/></svg>
                    )}
                </span>
                <div className="git-repocell">
                    <div className="git-reponame">
                        <span className="own">{repo.owner.login}/</span>{repo.name}
                        {repo.private && <span className="git-chip git-chip--amber">private</span>}
                        {repo.fork && <span className="git-chip git-chip--cyan">fork</span>}
                    </div>
                    {repo.description && <div className="sk-cell-sub git-repo-desc">{repo.description}</div>}
                </div>
            </div>
        ),
    },
    {
        key: 'branch',
        header: 'Branch',
        sortable: true,
        sortValue: (repo) => repo.default_branch || '',
        render: (repo) => (
            <span className="git-branch-chip">
                <svg viewBox="0 0 24 24" width="11" height="11" stroke="currentColor" fill="none" strokeWidth="2"><line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>
                {repo.default_branch}
            </span>
        ),
    },
    {
        key: 'stars',
        header: 'Stars',
        sortable: true,
        sortValue: (repo) => repo.stars ?? 0,
        cellClassName: 'sk-cell-mono',
    },
    {
        key: 'forks',
        header: 'Forks',
        sortable: true,
        sortValue: (repo) => repo.forks ?? 0,
        cellClassName: 'sk-cell-mono',
    },
    {
        key: 'updated',
        header: 'Updated',
        sortable: true,
        sortValue: (repo) => (repo.updated_at ? new Date(repo.updated_at).getTime() : null),
        cellClassName: 'sk-cell-mono',
        render: (repo) => formatDate(repo.updated_at),
    },
    {
        key: 'open',
        header: '',
        sortable: false,
        hideable: false,
        width: 30,
        render: () => <ChevronRight size={16} className="dom-chev" />,
    },
];

const WEBHOOK_COLUMNS = [
    {
        key: 'name',
        header: 'Webhook',
        sortable: true,
        hideable: false,
        sortValue: (webhook) => webhook.name || '',
        render: (webhook) => (
            <div className="sk-cell-name">
                <span className={`git-src-tile git-src-tile--${webhook.source}`}>{SOURCE_INITIALS[webhook.source] || webhook.source?.slice(0, 2).toUpperCase()}</span>
                <div className="git-repocell">
                    <div className="git-reponame">{webhook.name}</div>
                    <div className="sk-cell-sub">{webhook.source}{webhook.deploy_on_push ? ' · deploy on push' : ''}</div>
                </div>
            </div>
        ),
    },
    {
        key: 'repository',
        header: 'Repository',
        sortable: true,
        sortValue: (webhook) => webhook.source_repo_url || '',
        cellClassName: 'sk-cell-mono git-url',
        render: (webhook) => <span title={webhook.source_repo_url}>{webhook.source_repo_url}</span>,
    },
    {
        key: 'branch',
        header: 'Branch',
        sortable: true,
        sortValue: (webhook) => webhook.source_branch || '',
        render: (webhook) => (
            <span className="git-branch-chip">
                <svg viewBox="0 0 24 24" width="11" height="11" stroke="currentColor" fill="none" strokeWidth="2"><line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>
                {webhook.source_branch}
            </span>
        ),
    },
    {
        key: 'lastSync',
        header: 'Last sync',
        sortable: true,
        sortValue: (webhook) => (webhook.last_sync_at ? new Date(webhook.last_sync_at).getTime() : null),
        cellClassName: 'sk-cell-mono',
        render: (webhook) => (
            <span title={webhook.last_sync_at ? new Date(webhook.last_sync_at).toLocaleString() : undefined}>
                {webhook.last_sync_at ? formatDate(webhook.last_sync_at) : 'never'}
            </span>
        ),
    },
    {
        key: 'sync_count',
        header: 'Syncs',
        sortable: true,
        sortValue: (webhook) => webhook.sync_count ?? 0,
        cellClassName: 'sk-cell-mono',
    },
    {
        key: 'status',
        header: 'Status',
        sortable: true,
        sortValue: (webhook) => (webhook.is_active ? 1 : 0),
        render: (webhook) => <Pill kind={webhook.is_active ? 'green' : 'gray'}>{webhook.is_active ? 'Active' : 'Inactive'}</Pill>,
    },
    {
        key: 'open',
        header: '',
        sortable: false,
        hideable: false,
        width: 30,
        render: () => <ChevronRight size={16} className="dom-chev" />,
    },
];

// Recent deployments table inside the webhook drawer.
const HOOK_DEPLOY_COLUMNS = [
    {
        key: 'version',
        header: 'Version',
        sortable: true,
        sortValue: (d) => d.version ?? 0,
        render: (d) => `v${d.version}`,
    },
    {
        key: 'status',
        header: 'Status',
        sortable: true,
        sortValue: (d) => d.status || '',
        render: (d) => <Pill kind={getStatusColor(d.status)}>{d.status}</Pill>,
    },
    {
        key: 'when',
        header: 'When',
        sortable: true,
        sortValue: (d) => (d.created_at ? new Date(d.created_at).getTime() : null),
        render: (d) => formatDate(d.created_at),
    },
];

function Git({ basePath = '/git' }) {
    const [status, setStatus] = useState(null);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useTabParam(basePath, VALID_TABS);
    const [pageError, setPageError] = useState('');

    const [showInstallModal, setShowInstallModal] = useState(false);
    const [actionLoading, setActionLoading] = useState(false);
    const [confirmDialog, setConfirmDialog] = useState(null);
    const [installForm, setInstallForm] = useState({
        adminUser: 'admin',
        adminEmail: '',
        adminPassword: ''
    });

    // Webhook state
    const [webhooks, setWebhooks] = useState([]);
    const [webhooksLoading, setWebhooksLoading] = useState(false);
    const [showWebhookModal, setShowWebhookModal] = useState(false);
    const [drawerWebhook, setDrawerWebhook] = useState(null);
    const [webhookFilter, setWebhookFilter] = useState('all');
    const [webhookDeployments, setWebhookDeployments] = useState([]);
    const [webhookForm, setWebhookForm] = useState({
        name: '',
        source: 'github',
        sourceRepoUrl: '',
        sourceBranch: 'main',
        localRepoName: '',
        syncDirection: 'pull',
        autoSync: true,
        appId: '',
        deployOnPush: false,
        preDeployScript: '',
        postDeployScript: '',
        zeroDowntime: false,
    });
    const [webhookSecret, setWebhookSecret] = useState(null);

    // Repository state
    const [repositories, setRepositories] = useState([]);
    const [reposLoading, setReposLoading] = useState(false);
    const [selectedRepo, setSelectedRepo] = useState(null);
    const [drawerRepo, setDrawerRepo] = useState(null);
    const [branches, setBranches] = useState([]);
    const [commits, setCommits] = useState([]);
    const [selectedBranch, setSelectedBranch] = useState(null);
    const [files, setFiles] = useState([]);
    const [currentPath, setCurrentPath] = useState('');
    const [repoDetailTab, setRepoDetailTab] = useState('files');
    const [repoFilter, setRepoFilter] = useState('all');

    // Deployment state
    const [applications, setApplications] = useState([]);
    const [deployments, setDeployments] = useState([]);
    const [deploymentsLoading, setDeploymentsLoading] = useState(false);
    const [selectedDeployment, setSelectedDeployment] = useState(null);
    const [drawerDeployment, setDrawerDeployment] = useState(null);
    const [showDeploymentLogs, setShowDeploymentLogs] = useState(false);
    const [deployingAppId, setDeployingAppId] = useState(null);
    const [deploymentFilter, setDeploymentFilter] = useState('all');

    const { sorts: repoSorts, setSorts: setRepoSorts } = useTableSort({ storageKey: 'serverkit-table-git-repos-sort' });
    const {
        hiddenKeys: repoHiddenKeys, toggleColumn: toggleRepoColumn, showAllColumns: showAllRepoColumns,
    } = useColumnVisibility({ storageKey: 'serverkit-table-git-repos-cols' });
    const { sorts: webhookSorts, setSorts: setWebhookSorts } = useTableSort({ storageKey: 'serverkit-table-git-webhooks-sort' });
    const {
        hiddenKeys: webhookHiddenKeys, toggleColumn: toggleWebhookColumn, showAllColumns: showAllWebhookColumns,
    } = useColumnVisibility({ storageKey: 'serverkit-table-git-webhooks-cols' });

    const toast = useToast();

    useEffect(() => {
        loadData();
    }, []);

    useEffect(() => {
        if (activeTab === 'webhooks' && status?.installed) {
            loadWebhooks();
            loadApplications();
        }
        if (activeTab === 'repositories' && status?.installed && status?.running) {
            loadRepositories();
        }
        if (activeTab === 'deployments' && status?.installed) {
            loadWebhooks();
            loadAllDeployments();
        }
    }, [activeTab, status?.installed, status?.running]);

    useEffect(() => {
        if (drawerWebhook?.id) {
            loadWebhookDeployments(drawerWebhook.id).then(setWebhookDeployments);
        }
    }, [drawerWebhook]);

    const loadData = async () => {
        setLoading(true);
        try {
            await loadStatus();
        } catch (error) {
            console.error('Failed to load git data:', error);
        } finally {
            setLoading(false);
        }
    };

    const loadStatus = async () => {
        try {
            const data = await api.getGitServerStatus();
            setStatus(data);
        } catch (error) {
            console.error('Failed to load status:', error);
            setStatus({ installed: false });
        }
    };

    const loadWebhooks = async () => {
        setWebhooksLoading(true);
        try {
            const data = await api.getWebhooks();
            setWebhooks(data.webhooks || []);
        } catch (error) {
            console.error('Failed to load webhooks:', error);
        } finally {
            setWebhooksLoading(false);
        }
    };

    const loadApplications = async () => {
        try {
            const data = await api.getApps();
            setApplications(data.apps || []);
        } catch (error) {
            console.error('Failed to load applications:', error);
        }
    };

    const handleCreateWebhook = async () => {
        if (!webhookForm.name || !webhookForm.sourceRepoUrl) {
            toast.error('Name and repository URL are required');
            return;
        }
        setActionLoading(true);
        try {
            const result = await api.createWebhook(webhookForm);
            if (result.success) {
                toast.success('Webhook created successfully');
                setWebhookSecret(result.secret);
                setShowWebhookModal(false);
                setWebhookForm({
                    name: '', source: 'github', sourceRepoUrl: '', sourceBranch: 'main',
                    localRepoName: '', syncDirection: 'pull', autoSync: true, appId: '',
                    deployOnPush: false, preDeployScript: '', postDeployScript: '', zeroDowntime: false,
                });
                await loadWebhooks();
            } else {
                toast.error(result.error || 'Failed to create webhook');
            }
        } catch (error) {
            toast.error(`Failed to create webhook: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleDeleteWebhook = async (webhookId) => {
        setConfirmDialog({
            title: 'Delete Webhook',
            message: 'Are you sure you want to delete this webhook? This cannot be undone.',
            confirmText: 'Delete',
            variant: 'danger',
            onConfirm: async () => {
                try {
                    await api.deleteWebhook(webhookId);
                    toast.success('Webhook deleted');
                    await loadWebhooks();
                } catch (error) {
                    toast.error(`Failed to delete: ${error.message}`);
                } finally {
                    setConfirmDialog(null);
                    setDrawerWebhook(null);
                }
            },
            onCancel: () => setConfirmDialog(null)
        });
    };

    const handleToggleWebhook = async (webhookId) => {
        try {
            const result = await api.toggleWebhook(webhookId);
            if (result.success) {
                toast.success(result.message);
                await loadWebhooks();
                if (drawerWebhook?.id === webhookId) {
                    const updated = webhooks.find(w => w.id === webhookId);
                    if (updated) setDrawerWebhook(updated);
                }
            }
        } catch (error) {
            toast.error(`Failed to toggle webhook: ${error.message}`);
        }
    };

    const handleTestWebhook = async (webhookId) => {
        try {
            const result = await api.testWebhook(webhookId);
            if (result.success) toast.success('Test event logged');
            else toast.error(result.error || 'Test failed');
        } catch (error) {
            toast.error(`Test failed: ${error.message}`);
        }
    };

    const copyWebhookUrl = (webhook) => {
        const baseUrl = window.location.origin;
        const url = `${baseUrl}/api${webhook.webhook_url}`;
        navigator.clipboard.writeText(url);
        toast.success('Webhook URL copied');
    };

    // Repository functions
    const loadRepositories = async () => {
        setReposLoading(true);
        try {
            const data = await api.getRepositories();
            setRepositories(data.repositories || []);
        } catch (error) {
            console.error('Failed to load repositories:', error);
            if (error.message?.includes('not running')) {
                toast.error('Gitea server is not running');
            }
        } finally {
            setReposLoading(false);
        }
    };

    const openRepoDrawer = async (repo) => {
        setDrawerRepo(repo);
        setSelectedRepo(repo);
        setRepoViewState(repo);
    };

    const setRepoViewState = (repo) => {
        setCurrentPath('');
        setSelectedBranch(repo.default_branch);
        setRepoDetailTab('files');
        Promise.all([
            api.getBranches(repo.owner.login, repo.name),
            api.getCommits(repo.owner.login, repo.name, repo.default_branch),
            api.getRepoFiles(repo.owner.login, repo.name, repo.default_branch)
        ]).then(([branchesData, commitsData, filesData]) => {
            setBranches(branchesData.branches || []);
            setCommits(commitsData.commits || []);
            setFiles(filesData.files || []);
        }).catch(() => {
            toast.error('Failed to load repository details');
        });
    };

    const navigateToPath = async (path) => {
        if (!selectedRepo) return;
        try {
            const data = await api.getRepoFiles(selectedRepo.owner.login, selectedRepo.name, selectedBranch, path);
            setFiles(data.files || []);
            setCurrentPath(path);
        } catch {
            toast.error('Failed to load directory');
        }
    };

    const navigateUp = () => {
        if (!currentPath) return;
        const parts = currentPath.split('/');
        parts.pop();
        navigateToPath(parts.join('/'));
    };

    const changeBranch = async (branchName) => {
        if (!selectedRepo) return;
        setSelectedBranch(branchName);
        setCurrentPath('');
        try {
            const [commitsData, filesData] = await Promise.all([
                api.getCommits(selectedRepo.owner.login, selectedRepo.name, branchName),
                api.getRepoFiles(selectedRepo.owner.login, selectedRepo.name, branchName)
            ]);
            setCommits(commitsData.commits || []);
            setFiles(filesData.files || []);
        } catch {
            toast.error('Failed to switch branch');
        }
    };

    const loadMoreCommits = async () => {
        if (!selectedRepo) return;
        const currentPage = Math.ceil(commits.length / 30) + 1;
        try {
            const data = await api.getCommits(selectedRepo.owner.login, selectedRepo.name, selectedBranch, currentPage);
            if (data.commits?.length) setCommits([...commits, ...data.commits]);
        } catch {
            toast.error('Failed to load more commits');
        }
    };

    // Deployment functions
    const loadAllDeployments = async () => {
        setDeploymentsLoading(true);
        try {
            const webhooksData = await api.getWebhooks();
            const webhooksWithDeploy = (webhooksData.webhooks || []).filter(w => w.deploy_on_push && w.app_id);
            let allDeployments = [];
            for (const webhook of webhooksWithDeploy) {
                const data = await api.getWebhookDeployments(webhook.id, 10);
                if (data.deployments) {
                    allDeployments = [...allDeployments, ...data.deployments.map(d => ({ ...d, webhook_name: webhook.name }))];
                }
            }
            allDeployments.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
            setDeployments(allDeployments);
        } catch (error) {
            console.error('Failed to load deployments:', error);
        } finally {
            setDeploymentsLoading(false);
        }
    };

    const loadWebhookDeployments = async (webhookId) => {
        try {
            const data = await api.getWebhookDeployments(webhookId, 20);
            return data.deployments || [];
        } catch (error) {
            console.error('Failed to load webhook deployments:', error);
            return [];
        }
    };

    const handleTriggerDeploy = async (appId) => {
        setDeployingAppId(appId);
        try {
            const result = await api.triggerGitDeploy(appId);
            if (result.success) {
                toast.success(`Deployment started: v${result.version}`);
                await loadAllDeployments();
            } else {
                toast.error(result.error || 'Failed to trigger deployment');
            }
        } catch (error) {
            toast.error(`Failed to deploy: ${error.message}`);
        } finally {
            setDeployingAppId(null);
        }
    };

    const handleRollback = async (appId, targetVersion) => {
        setConfirmDialog({
            title: 'Rollback Deployment',
            message: `Rollback to version ${targetVersion}? This will restart the application with the previous code.`,
            confirmText: 'Rollback',
            variant: 'warning',
            onConfirm: async () => {
                try {
                    const result = await api.rollbackDeployment(appId, targetVersion);
                    if (result.success) {
                        toast.success(result.message || 'Rollback completed');
                        await loadAllDeployments();
                    } else {
                        toast.error(result.error || 'Rollback failed');
                    }
                } catch (error) {
                    toast.error(`Rollback failed: ${error.message}`);
                } finally {
                    setConfirmDialog(null);
                }
            },
            onCancel: () => setConfirmDialog(null)
        });
    };

    const viewDeploymentLogs = async (deploymentId) => {
        try {
            const data = await api.getDeployment(deploymentId, true);
            if (data.success) {
                setSelectedDeployment(data.deployment);
                setShowDeploymentLogs(true);
            } else {
                toast.error('Failed to load deployment details');
            }
        } catch (error) {
            toast.error(`Failed to load logs: ${error.message}`);
        }
    };

    const formatFileSize = (bytes) => {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    };

    const handleInstall = async () => {
        if (!installForm.adminEmail) {
            toast.error('Admin email is required');
            return;
        }
        setActionLoading(true);
        try {
            const result = await api.installGit(installForm);
            if (result.success) {
                toast.success('Git server installed successfully');
                setShowInstallModal(false);
                if (result.admin_password) {
                    toast.info(`Admin password: ${result.admin_password} (save this!)`);
                }
                await loadData();
            } else {
                toast.error(result.error || 'Installation failed');
            }
        } catch (error) {
            toast.error(`Failed to install: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleUninstall = async () => {
        setConfirmDialog({
            title: 'Uninstall Git Server',
            message: 'Uninstall the Gitea server? This will stop the container but preserve your data.',
            confirmText: 'Uninstall',
            variant: 'danger',
            onConfirm: async () => {
                setActionLoading(true);
                try {
                    await api.uninstallGit(false);
                    toast.success('Git server uninstalled');
                    await loadData();
                } catch (error) {
                    toast.error(`Failed to uninstall: ${error.message}`);
                } finally {
                    setActionLoading(false);
                    setConfirmDialog(null);
                }
            },
            onCancel: () => setConfirmDialog(null)
        });
    };

    const handleStart = async () => {
        setActionLoading(true);
        try {
            await api.startGit();
            toast.success('Git server started');
            await loadStatus();
        } catch (error) {
            toast.error(`Failed to start: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleStop = async () => {
        setConfirmDialog({
            title: 'Stop Git Server',
            message: 'Stop the Git server?',
            confirmText: 'Stop',
            variant: 'warning',
            onConfirm: async () => {
                setActionLoading(true);
                try {
                    await api.stopGit();
                    toast.success('Git server stopped');
                    await loadStatus();
                } catch (error) {
                    toast.error(`Failed to stop: ${error.message}`);
                } finally {
                    setActionLoading(false);
                    setConfirmDialog(null);
                }
            },
            onCancel: () => setConfirmDialog(null)
        });
    };

    const openGitea = () => {
        if (status?.url_path) {
            window.open(`${window.location.origin}${status.url_path}`, '_blank');
        } else if (status?.http_port) {
            window.open(`http://${window.location.hostname}:${status.http_port}`, '_blank');
        }
    };

    const getGiteaUrl = () => {
        if (status?.url_path) return `${window.location.origin}${status.url_path}`;
        return `http://${window.location.hostname}:${status?.http_port}`;
    };

    const getAppName = (appId) => {
        const app = applications.find(a => String(a.id) === String(appId));
        return app ? app.name : 'Unknown';
    };

    // ── Filters ───────────────────────────────────────────────
    const filteredRepos = repositories.filter(repo => {
        if (repoFilter === 'private') return repo.private;
        if (repoFilter === 'forks') return repo.fork;
        return true;
    });

    const filteredWebhooks = webhooks.filter(w => {
        if (webhookFilter === 'active') return w.is_active;
        if (webhookFilter === 'inactive') return !w.is_active;
        return true;
    });

    const filteredDeployments = deployments.filter(d => {
        if (deploymentFilter === 'all') return true;
        return d.status === deploymentFilter;
    });

    // ── KPIs ──────────────────────────────────────────────────
    const repoPrivateCount = repositories.filter(r => r.private).length;
    const repoForkCount = repositories.filter(r => r.fork).length;
    const repoUpdatedCount = repositories.filter(r => {
        if (!r.updated_at) return false;
        return (Date.now() - new Date(r.updated_at).getTime()) < 86400000 * 7;
    }).length;

    const webhookActiveCount = webhooks.filter(w => w.is_active).length;
    const webhookInactiveCount = webhooks.filter(w => !w.is_active).length;
    const webhookDeployCount = webhooks.filter(w => w.deploy_on_push).length;

    const deploymentSuccessCount = deployments.filter(d => d.status === 'success').length;
    const deploymentFailedCount = deployments.filter(d => d.status === 'failed').length;
    const deploymentRunningCount = deployments.filter(d => d.status === 'running').length;

    const renderKpis = () => {
        switch (activeTab) {
            case 'overview':
                return (
                    <div className="dom-kpis">
                        <MetricCard tone={status?.running ? 'green' : 'red'} icon={<Server size={16} />} value={status?.running ? 'Running' : 'Stopped'} label="Server status" />
                        <MetricCard tone="accent" icon={<Globe size={16} />} value={status?.url_path || '/gitea'} label="URL path" />
                        <MetricCard tone="cyan" icon={<Terminal size={16} />} value={status?.ssh_port || 'N/A'} label="SSH port" />
                        <MetricCard tone="violet" icon={<Tag size={16} />} value={status?.version || 'Unknown'} label="Gitea version" />
                    </div>
                );
            case 'repositories':
                return (
                    <div className="dom-kpis">
                        <MetricCard tone="accent" icon={<FolderGit2 size={16} />} value={repositories.length} label="Repositories" />
                        <MetricCard tone="amber" icon={<Lock size={16} />} value={repoPrivateCount} label="Private" />
                        <MetricCard tone="cyan" icon={<GitBranch size={16} />} value={repoForkCount} label="Forks" />
                        <MetricCard tone="green" icon={<Clock size={16} />} value={repoUpdatedCount} label="Updated ≤7d" />
                    </div>
                );
            case 'webhooks':
                return (
                    <div className="dom-kpis">
                        <MetricCard tone="accent" icon={<Webhook size={16} />} value={webhooks.length} label="Webhooks" />
                        <MetricCard tone="green" icon={<Server size={16} />} value={webhookActiveCount} label="Active" />
                        <MetricCard tone="gray" icon={<AlertCircle size={16} />} value={webhookInactiveCount} label="Inactive" />
                        <MetricCard tone="cyan" icon={<Rocket size={16} />} value={webhookDeployCount} label="Deploy on push" />
                    </div>
                );
            case 'deployments':
                return (
                    <div className="dom-kpis">
                        <MetricCard tone="accent" icon={<Rocket size={16} />} value={deployments.length} label="Deployments" />
                        <MetricCard tone="green" icon={<Server size={16} />} value={deploymentSuccessCount} label="Success" />
                        <MetricCard tone="red" icon={<AlertTriangle size={16} />} value={deploymentFailedCount} label="Failed" />
                        <MetricCard tone="amber" icon={<Clock size={16} />} value={deploymentRunningCount} label="Running" />
                    </div>
                );
            default:
                return null;
        }
    };

    // ── Tab content ───────────────────────────────────────────
    const renderOverview = () => (
        <>
            <ListToolbar title="Server overview" />
            <div className="dom-specs">
                <div className="sk-spec-card">
                    <div className="sk-spec-card__label">HTTP URL</div>
                    <div className="sk-spec-card__value" style={{ fontSize: 13 }}>{status?.running ? getGiteaUrl() : 'Server not running'}</div>
                    <div className="sk-spec-card__sub">Web interface</div>
                </div>
                <div className="sk-spec-card">
                    <div className="sk-spec-card__label">SSH Clone URL</div>
                    <div className="sk-spec-card__value" style={{ fontSize: 13 }}>ssh://git@{window.location.hostname}:{status?.ssh_port}/user/repo.git</div>
                    <div className="sk-spec-card__sub">Use your SSH key</div>
                </div>
                <div className="sk-spec-card">
                    <div className="sk-spec-card__label">Quick actions</div>
                    <div className="git-quick-actions" style={{ marginTop: 8 }}>
                        <Button variant="outline" size="sm" onClick={openGitea} disabled={!status?.running}>Open Gitea</Button>
                        <Button variant="outline" size="sm" onClick={() => { navigator.clipboard.writeText(`git clone ssh://git@${window.location.hostname}:${status?.ssh_port}/user/repo.git`); toast.success('SSH URL copied'); }}>
                            Copy SSH URL
                        </Button>
                    </div>
                    <div className="sk-spec-card__sub">Access repositories</div>
                </div>
            </div>
        </>
    );

    const renderRepositories = () => {
        if (!status?.running) {
            return (
                <EmptyState
                    icon={AlertCircle}
                    title="Server not running"
                    description="Start the Git server to browse repositories."
                    action={<Button onClick={handleStart}>Start Server</Button>}
                />
            );
        }
        if (reposLoading) return <EmptyState loading loadingVariant="table" title="Loading repositories" />;
        if (repositories.length === 0) {
            return (
                <EmptyState
                    icon={FolderGit2}
                    title="No repositories yet"
                    description="Create your first repository in Gitea."
                    action={<Button onClick={openGitea}>Open Gitea</Button>}
                />
            );
        }
        return (
            <>
                <ListToolbar
                    title="Repositories"
                    filters={(
                        <SegControl
                            value={repoFilter}
                            onChange={setRepoFilter}
                            options={[
                                { value: 'all', label: 'All', count: repositories.length },
                                { value: 'private', label: 'Private', count: repoPrivateCount },
                                { value: 'forks', label: 'Forks', count: repoForkCount },
                            ]}
                        />
                    )}
                    tools={(
                        <>
                            <SortMenu columns={REPO_COLUMNS} sorts={repoSorts} onChange={setRepoSorts} />
                            <ColumnsMenu
                                columns={REPO_COLUMNS}
                                hiddenKeys={repoHiddenKeys}
                                onToggle={toggleRepoColumn}
                                onShowAll={showAllRepoColumns}
                            />
                        </>
                    )}
                />
                {filteredRepos.length === 0 ? (
                    <EmptyState icon={FolderGit2} title="No repositories match this filter." />
                ) : (
                    <div className="dom-card">
                        <DataTable
                            columns={REPO_COLUMNS}
                            data={filteredRepos}
                            keyField="id"
                            sorts={repoSorts}
                            onSortsChange={setRepoSorts}
                            hiddenKeys={repoHiddenKeys}
                            onRowClick={openRepoDrawer}
                            tableClassName="git-repos-table"
                            footer={(
                                <DataTableFooter
                                    shown={filteredRepos.length}
                                    total={repositories.length}
                                    noun="repo"
                                />
                            )}
                        />
                    </div>
                )}
            </>
        );
    };

    const renderAccess = () => (
        <>
            <ListToolbar title="Access information" />
            <div className="dom-specs">
                <div className="sk-spec-card">
                    <div className="sk-spec-card__label">HTTP Access</div>
                    <div className="sk-spec-card__value" style={{ fontSize: 13 }}>{getGiteaUrl()}</div>
                    <div className="sk-spec-card__sub">Web browser access</div>
                    <div className="git-quick-actions" style={{ marginTop: 12 }}>
                        <Button variant="outline" size="sm" onClick={() => { navigator.clipboard.writeText(getGiteaUrl()); toast.success('URL copied'); }}>Copy URL</Button>
                        <Button variant="outline" size="sm" onClick={openGitea} disabled={!status?.running}>Open Gitea</Button>
                    </div>
                </div>
                <div className="sk-spec-card">
                    <div className="sk-spec-card__label">SSH Access</div>
                    <div className="sk-spec-card__value" style={{ fontSize: 13 }}>ssh://git@{window.location.hostname}:{status?.ssh_port}/username/repo.git</div>
                    <div className="sk-spec-card__sub">Clone repositories via SSH</div>
                    <div className="git-quick-actions" style={{ marginTop: 12 }}>
                        <Button variant="outline" size="sm" onClick={() => { navigator.clipboard.writeText(`ssh://git@${window.location.hostname}:${status?.ssh_port}/username/repo.git`); toast.success('SSH URL copied'); }}>Copy SSH URL</Button>
                    </div>
                </div>
                <div className="sk-spec-card">
                    <div className="sk-spec-card__label">SSH key requirement</div>
                    <div className="sk-spec-card__value" style={{ fontSize: 13 }}>Add your public key in Gitea</div>
                    <div className="sk-spec-card__sub">Required for SSH clone/push</div>
                </div>
            </div>
        </>
    );

    const renderWebhooks = () => {
        if (webhooksLoading) return <EmptyState loading loadingVariant="table" title="Loading webhooks" />;
        if (webhooks.length === 0) {
            return (
                <EmptyState
                    icon={Webhook}
                    title="No webhooks configured"
                    description="Add a webhook to sync repositories from external sources."
                    action={<Button onClick={() => setShowWebhookModal(true)}>Add Webhook</Button>}
                />
            );
        }
        return (
            <>
                <ListToolbar
                    title="External repository webhooks"
                    filters={(
                        <SegControl
                            value={webhookFilter}
                            onChange={setWebhookFilter}
                            options={[
                                { value: 'all', label: 'All', count: webhooks.length },
                                { value: 'active', label: 'Active', count: webhookActiveCount },
                                { value: 'inactive', label: 'Inactive', count: webhookInactiveCount },
                            ]}
                        />
                    )}
                    tools={(
                        <>
                            <SortMenu columns={WEBHOOK_COLUMNS} sorts={webhookSorts} onChange={setWebhookSorts} />
                            <ColumnsMenu
                                columns={WEBHOOK_COLUMNS}
                                hiddenKeys={webhookHiddenKeys}
                                onToggle={toggleWebhookColumn}
                                onShowAll={showAllWebhookColumns}
                            />
                        </>
                    )}
                />
                {filteredWebhooks.length === 0 ? (
                    <EmptyState icon={Webhook} title="No webhooks match this filter." />
                ) : (
                    <div className="dom-card">
                        <DataTable
                            columns={WEBHOOK_COLUMNS}
                            data={filteredWebhooks}
                            keyField="id"
                            sorts={webhookSorts}
                            onSortsChange={setWebhookSorts}
                            hiddenKeys={webhookHiddenKeys}
                            onRowClick={setDrawerWebhook}
                            rowClassName={(webhook) => (!webhook.is_active ? 'is-disabled' : '')}
                            tableClassName="git-webhooks-table"
                            footer={(
                                <DataTableFooter
                                    shown={filteredWebhooks.length}
                                    total={webhooks.length}
                                    noun="webhook"
                                />
                            )}
                        />
                    </div>
                )}
            </>
        );
    };

    const renderDeployments = () => {
        if (deploymentsLoading) return <EmptyState loading loadingVariant="table" title="Loading deployments" />;
        if (deployments.length === 0) {
            return (
                <EmptyState
                    icon={Rocket}
                    title="No deployments yet"
                    description='Configure a webhook with "Deploy on Push" enabled to see deployments here.'
                    action={<Button onClick={() => setActiveTab('webhooks')}>Configure Webhooks</Button>}
                />
            );
        }
        return (
            <>
                <ListToolbar
                    title="Deployment history"
                    filters={(
                        <SegControl
                            value={deploymentFilter}
                            onChange={setDeploymentFilter}
                            options={[
                                { value: 'all', label: 'All', count: deployments.length },
                                { value: 'success', label: 'Success', count: deploymentSuccessCount },
                                { value: 'failed', label: 'Failed', count: deploymentFailedCount },
                                { value: 'running', label: 'Running', count: deploymentRunningCount },
                            ]}
                        />
                    )}
                />
                {filteredDeployments.length === 0 ? (
                    <EmptyState icon={Rocket} title="No deployments match this filter." />
                ) : (
                    <div className="dom-card">
                        {filteredDeployments.map(deployment => (
                            <div key={deployment.id} className="git-deploy-row is-clickable" onClick={() => setDrawerDeployment(deployment)}>
                                <span className={`git-deploy-dot git-deploy-dot--${getStatusColor(deployment.status)}`} />
                                <div className="git-deploy-body">
                                    <div className="git-deploy-top">
                                        <span className="git-deploy-version">v{deployment.version}</span>
                                        <Pill kind={getStatusColor(deployment.status)}>{deployment.status}</Pill>
                                        {deployment.is_rollback && <span className="git-chip git-chip--cyan">rollback</span>}
                                        {deployment.commit_sha && <code className="git-hash">{deployment.commit_sha.slice(0, 7)}</code>}
                                    </div>
                                    {deployment.commit_message && <div className="git-deploy-msg">{deployment.commit_message.split('\n')[0]}</div>}
                                    <div className="git-deploy-meta">
                                        <span>{deployment.branch}</span>
                                        <span>{deployment.triggered_by}</span>
                                        {deployment.webhook_name && <span>{deployment.webhook_name}</span>}
                                        {deployment.duration_seconds != null && <span>{deployment.duration_seconds}s</span>}
                                    </div>
                                    {deployment.error_message && <div className="git-deploy-error">{deployment.error_message}</div>}
                                </div>
                                <div className="git-deploy-side">
                                    <span className="git-deploy-time">{formatDate(deployment.created_at)}</span>
                                    <ChevronRight size={16} className="dom-chev" />
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </>
        );
    };

    const renderSettings = () => (
        <>
            <ListToolbar title="Server settings" />
            <div className="dom-specs">
                <div className="sk-spec-card">
                    <div className="sk-spec-card__label">Server power</div>
                    <div className="git-quick-actions" style={{ marginTop: 8 }}>
                        {status?.running ? (
                            <Button variant="secondary" onClick={handleStop} disabled={actionLoading}>Stop Server</Button>
                        ) : (
                            <Button onClick={handleStart} disabled={actionLoading}>Start Server</Button>
                        )}
                    </div>
                    <div className="sk-spec-card__sub">Start or stop the Gitea container</div>
                </div>
                <div className="sk-spec-card">
                    <div className="sk-spec-card__label">Uninstall</div>
                    <div className="git-quick-actions" style={{ marginTop: 8 }}>
                        <Button variant="destructive" onClick={handleUninstall} disabled={actionLoading}>Uninstall Git Server</Button>
                    </div>
                    <div className="sk-spec-card__sub">Stops Gitea; data is preserved unless removed manually</div>
                </div>
            </div>
            <div style={{ marginTop: 24 }}>
                <DangerZone
                    title="Danger Zone"
                    description="Uninstalling will stop the Gitea container. Your data will be preserved unless you choose to remove it."
                />
            </div>
        </>
    );

    const renderTabContent = () => {
        switch (activeTab) {
            case 'overview': return renderOverview();
            case 'repositories': return renderRepositories();
            case 'access': return renderAccess();
            case 'webhooks': return renderWebhooks();
            case 'deployments': return renderDeployments();
            case 'settings': return renderSettings();
            default: return renderOverview();
        }
    };

    const topbarActions = () => {
        if (!status?.installed) {
            return <Button onClick={() => setShowInstallModal(true)}>Install Git Server</Button>;
        }
        const common = (
            <Button variant="outline" onClick={openGitea} disabled={!status?.running}>
                <ExternalLink size={15} /> Open Gitea
            </Button>
        );
        switch (activeTab) {
            case 'webhooks':
                return (
                    <>
                        {common}
                        <Button onClick={() => setShowWebhookModal(true)}><Plus size={15} /> Add Webhook</Button>
                    </>
                );
            case 'deployments':
                return (
                    <>
                        {common}
                        <Button variant="outline" onClick={loadAllDeployments} disabled={deploymentsLoading}>
                            <RefreshCw size={15} /> Refresh
                        </Button>
                    </>
                );
            case 'repositories':
                return (
                    <>
                        {common}
                        <Button variant="outline" onClick={loadRepositories} disabled={reposLoading}>
                            <RefreshCw size={15} /> Refresh
                        </Button>
                    </>
                );
            default:
                return (
                    <>
                        {common}
                        {status?.running ? (
                            <Button variant="secondary" onClick={handleStop} disabled={actionLoading}>Stop Server</Button>
                        ) : (
                            <Button onClick={handleStart} disabled={actionLoading}>Start Server</Button>
                        )}
                    </>
                );
        }
    };

    // Tabs live in the page top bar (like Domains/Services). The single Git page
    // renders all sections, keyed off the /git/:tab route via useTabParam — the
    // header title + icon mirror the active tab.
    const GIT_TABS = useMemo(() => [
        { slug: 'overview', to: basePath, label: 'Overview', end: true, icon: <Server size={15} /> },
        { slug: 'repositories', to: `${basePath}/repositories`, label: 'Repositories', icon: <FolderGit2 size={15} /> },
        { slug: 'webhooks', to: `${basePath}/webhooks`, label: 'Webhooks', icon: <Webhook size={15} /> },
        { slug: 'deployments', to: `${basePath}/deployments`, label: 'Deployments', icon: <Rocket size={15} /> },
        { slug: 'access', to: `${basePath}/access`, label: 'Access', icon: <Globe size={15} /> },
        { slug: 'settings', to: `${basePath}/settings`, label: 'Settings', icon: <Settings size={15} /> },
    ], [basePath]);
    const activeGit = GIT_TABS.find((t) => t.slug === activeTab) || GIT_TABS[0];

    if (loading) {
        return (
            <PageLayout className="git-page domains-page" navLabel="Git" tabs={GIT_TABS}>
                <EmptyState loading loadingVariant="table" size="lg" title="Loading Git" />
            </PageLayout>
        );
    }

    return (
        <PageLayout
            className="git-page domains-page"
            navLabel={activeGit.label}
            tabs={GIT_TABS}
            actions={topbarActions()}
        >
            {pageError && (
                <div className="error-banner">
                    {pageError}
                    <button type="button" onClick={() => setPageError('')} style={{ float: 'right', background: 'none', border: 'none', cursor: 'pointer' }}>×</button>
                </div>
            )}

            {!status?.installed ? (
                <div className="empty-state-large">
                    <div className="empty-icon">
                        <svg viewBox="0 0 24 24" width="64" height="64" stroke="currentColor" fill="none" strokeWidth="1.5">
                            <circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 0 0 9 9"/>
                        </svg>
                    </div>
                    <h2>No Git Server Installed</h2>
                    <p>Install Gitea to host and manage your Git repositories locally.</p>
                    <div className="resource-warning">
                        <div className="warning-header">
                            <AlertTriangle size={20} />
                            <strong>Resource Requirements</strong>
                        </div>
                        <ul>
                            <li><strong>Memory:</strong> ~512MB minimum (1GB recommended)</li>
                            <li><strong>Storage:</strong> ~5GB for database + repositories</li>
                            <li><strong>Components:</strong> Gitea + PostgreSQL database</li>
                        </ul>
                    </div>
                    <Button size="lg" onClick={() => setShowInstallModal(true)}>Install Git Server</Button>
                </div>
            ) : (
                <div className="domains-body">
                    {renderKpis()}
                    {renderTabContent()}
                </div>
            )}

            {/* Repository drawer */}
            <Drawer
                open={!!drawerRepo}
                onOpenChange={(open) => { if (!open) { setDrawerRepo(null); setSelectedRepo(null); } }}
                icon={<FolderGit2 size={18} />}
                iconColor="var(--accent-bright)"
                title={drawerRepo ? `${drawerRepo.owner.login}/${drawerRepo.name}` : ''}
                subtitle={drawerRepo ? `${drawerRepo.description || 'No description'} · ${drawerRepo.private ? 'private' : 'public'}` : ''}
                width={720}
            >
                {drawerRepo && selectedRepo && (
                    <div className="dom-drawer">
                        <div className="dom-drawer__actions">
                            <Button variant="outline" size="sm" onClick={openGitea} disabled={!status?.running}>
                                <ExternalLink size={14} /> Open in Gitea
                            </Button>
                            <Button variant="outline" size="sm" onClick={() => {
                                navigator.clipboard.writeText(`${getGiteaUrl()}/${selectedRepo.owner.login}/${selectedRepo.name}`);
                                toast.success('Repository URL copied');
                            }}>
                                Copy URL
                            </Button>
                        </div>
                        <div className="dom-specs">
                            <div className="sk-spec-card">
                                <div className="sk-spec-card__label">Default branch</div>
                                <div className="sk-spec-card__value">{selectedRepo.default_branch}</div>
                                <div className="sk-spec-card__sub">{branches.length} branches</div>
                            </div>
                            <div className="sk-spec-card">
                                <div className="sk-spec-card__label">Stars</div>
                                <div className="sk-spec-card__value">{selectedRepo.stars}</div>
                                <div className="sk-spec-card__sub">{selectedRepo.forks} forks</div>
                            </div>
                            <div className="sk-spec-card">
                                <div className="sk-spec-card__label">Visibility</div>
                                <div className="sk-spec-card__value">{selectedRepo.private ? 'Private' : 'Public'}</div>
                                <div className="sk-spec-card__sub">{selectedRepo.fork ? 'Fork' : 'Original'}</div>
                            </div>
                        </div>

                        <div className="git-repo-detail-tabs">
                            <div className="branch-selector">
                                <Label>Branch</Label>
                                <select value={selectedBranch || ''} onChange={(e) => changeBranch(e.target.value)}>
                                    {branches.map(b => <option key={b.name} value={b.name}>{b.name}</option>)}
                                </select>
                            </div>
                            <div className="git-mini-tabs">
                                <button type="button" className={repoDetailTab === 'files' ? 'active' : ''} onClick={() => setRepoDetailTab('files')}>Files</button>
                                <button type="button" className={repoDetailTab === 'commits' ? 'active' : ''} onClick={() => setRepoDetailTab('commits')}>Commits</button>
                                <button type="button" className={repoDetailTab === 'branches' ? 'active' : ''} onClick={() => setRepoDetailTab('branches')}>Branches</button>
                            </div>
                        </div>

                        {repoDetailTab === 'files' && (
                            <div className="files-browser">
                                {currentPath && (
                                    <div className="breadcrumb">
                                        <button type="button" onClick={() => navigateToPath('')}>{selectedRepo.name}</button>
                                        {currentPath.split('/').map((part, i, arr) => (
                                            <span key={i}><span className="separator">/</span><button type="button" onClick={() => navigateToPath(arr.slice(0, i + 1).join('/'))}>{part}</button></span>
                                        ))}
                                    </div>
                                )}
                                <div className="files-list">
                                    {currentPath && (
                                        <div className="file-item dir" onClick={navigateUp}>
                                            <div className="file-icon">
                                                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2"><polyline points="15 18 9 12 15 6"/></svg>
                                            </div>
                                            <span className="file-name">..</span>
                                        </div>
                                    )}
                                    {files.sort((a, b) => {
                                        if (a.type === 'dir' && b.type !== 'dir') return -1;
                                        if (a.type !== 'dir' && b.type === 'dir') return 1;
                                        return a.name.localeCompare(b.name);
                                    }).map(file => (
                                        <div key={file.path} className={`file-item ${file.type}`} onClick={() => file.type === 'dir' && navigateToPath(file.path)}>
                                            <div className="file-icon">
                                                {file.type === 'dir' ? (
                                                    <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                                                ) : (
                                                    <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                                                )}
                                            </div>
                                            <span className="file-name">{file.name}</span>
                                            {file.type === 'file' && <span className="file-size">{formatFileSize(file.size)}</span>}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {repoDetailTab === 'commits' && (
                            <div className="commits-list">
                                {commits.map(commit => (
                                    <div key={commit.sha} className="commit-item">
                                        <div className="commit-info">
                                            <div className="commit-message">{commit.message?.split('\n')[0]}</div>
                                            <div className="commit-meta">
                                                <span className="author">{commit.author?.name}</span>
                                                <span className="date">{formatDate(commit.author?.date)}</span>
                                            </div>
                                        </div>
                                        <code className="git-hash">{commit.short_sha}</code>
                                    </div>
                                ))}
                                {commits.length >= 30 && (
                                    <Button variant="outline" className="btn-block" onClick={loadMoreCommits}>Load More</Button>
                                )}
                            </div>
                        )}

                        {repoDetailTab === 'branches' && (
                            <div className="branches-list">
                                {branches.map(branch => (
                                    <div key={branch.name} className={`branch-item ${branch.name === selectedBranch ? 'active' : ''}`}>
                                        <div className="branch-info">
                                            <div className="branch-name">
                                                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2"><line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>
                                                {branch.name}
                                                {branch.name === selectedRepo?.default_branch && <span className="git-chip git-chip--green">default</span>}
                                                {branch.protected && <span className="git-chip git-chip--amber">protected</span>}
                                            </div>
                                            {branch.commit && (
                                                <div className="branch-commit">
                                                    <code>{branch.commit.sha?.slice(0, 7)}</code>
                                                    <span className="commit-date">{formatDate(branch.commit.date)}</span>
                                                </div>
                                            )}
                                        </div>
                                        <Button size="sm" variant="ghost" onClick={() => changeBranch(branch.name)}>Switch</Button>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}
            </Drawer>

            {/* Webhook drawer */}
            <Drawer
                open={!!drawerWebhook}
                onOpenChange={(open) => { if (!open) setDrawerWebhook(null); }}
                icon={<Webhook size={18} />}
                iconColor="var(--accent-bright)"
                title={drawerWebhook?.name || ''}
                subtitle={drawerWebhook ? `${drawerWebhook.source} · ${drawerWebhook.is_active ? 'active' : 'inactive'}` : ''}
                width={640}
            >
                {drawerWebhook && (
                    <div className="dom-drawer">
                        <div className="dom-drawer__actions">
                            <Button variant="outline" size="sm" onClick={() => copyWebhookUrl(drawerWebhook)}>Copy URL</Button>
                            <Button variant="outline" size="sm" onClick={() => handleTestWebhook(drawerWebhook.id)}>Test</Button>
                            <Button variant="outline" size="sm" onClick={() => handleToggleWebhook(drawerWebhook.id)}>
                                {drawerWebhook.is_active ? 'Disable' : 'Enable'}
                            </Button>
                            <Button variant="outline" size="sm" className="dom-delete-btn" onClick={() => handleDeleteWebhook(drawerWebhook.id)}>
                                <Trash2 size={14} /> Delete
                            </Button>
                        </div>
                        <div className="dom-specs">
                            <div className="sk-spec-card">
                                <div className="sk-spec-card__label">Source</div>
                                <div className="sk-spec-card__value">{drawerWebhook.source}</div>
                                <div className="sk-spec-card__sub">{drawerWebhook.source_repo_url}</div>
                            </div>
                            <div className="sk-spec-card">
                                <div className="sk-spec-card__label">Branch</div>
                                <div className="sk-spec-card__value">{drawerWebhook.source_branch}</div>
                                <div className="sk-spec-card__sub">{drawerWebhook.sync_direction}</div>
                            </div>
                            <div className="sk-spec-card">
                                <div className="sk-spec-card__label">Status</div>
                                <div style={{ marginTop: 8 }}><Pill kind={drawerWebhook.is_active ? 'green' : 'gray'}>{drawerWebhook.is_active ? 'Active' : 'Inactive'}</Pill></div>
                                <div className="sk-spec-card__sub">{drawerWebhook.sync_count} syncs</div>
                            </div>
                        </div>
                        {drawerWebhook.app_id && (
                            <div className="dom-drawer__section">
                                <h3 className="dom-drawer__sectiontitle">Deployment</h3>
                                <div className="dom-specs">
                                    <div className="sk-spec-card">
                                        <div className="sk-spec-card__label">Application</div>
                                        <div className="sk-spec-card__value">{getAppName(drawerWebhook.app_id)}</div>
                                    </div>
                                    <div className="sk-spec-card">
                                        <div className="sk-spec-card__label">Deploy on push</div>
                                        <div style={{ marginTop: 8 }}><Pill kind={drawerWebhook.deploy_on_push ? 'green' : 'gray'}>{drawerWebhook.deploy_on_push ? 'Enabled' : 'Disabled'}</Pill></div>
                                    </div>
                                    <div className="sk-spec-card">
                                        <div className="sk-spec-card__label">Zero downtime</div>
                                        <div style={{ marginTop: 8 }}><Pill kind={drawerWebhook.zero_downtime ? 'green' : 'gray'}>{drawerWebhook.zero_downtime ? 'Yes' : 'No'}</Pill></div>
                                    </div>
                                </div>
                            </div>
                        )}
                        <div className="dom-drawer__section">
                            <h3 className="dom-drawer__sectiontitle">Recent deployments</h3>
                            {webhookDeployments.length === 0 ? (
                                <p className="dom-drawer__hint">No deployments for this webhook.</p>
                            ) : (
                                <div className="dom-dns__table">
                                    <DataTable
                                        columns={HOOK_DEPLOY_COLUMNS}
                                        data={webhookDeployments}
                                        keyField="id"
                                        storageKey="serverkit-table-git-hook-deploys"
                                        onRowClick={(d) => { setDrawerWebhook(null); viewDeploymentLogs(d.id); }}
                                        footer={(
                                            <DataTableFooter
                                                shown={webhookDeployments.length}
                                                total={webhookDeployments.length}
                                                noun="deployment"
                                            />
                                        )}
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </Drawer>

            {/* Deployment drawer */}
            <Drawer
                open={!!drawerDeployment}
                onOpenChange={(open) => { if (!open) setDrawerDeployment(null); }}
                icon={<Rocket size={18} />}
                iconColor="var(--accent-bright)"
                title={drawerDeployment ? `Deployment v${drawerDeployment.version}` : ''}
                subtitle={drawerDeployment ? `${drawerDeployment.webhook_name || 'Manual'} · ${drawerDeployment.status}` : ''}
                width={640}
            >
                {drawerDeployment && (
                    <div className="dom-drawer">
                        <div className="dom-drawer__actions">
                            <Button variant="outline" size="sm" onClick={() => viewDeploymentLogs(drawerDeployment.id)}>View Logs</Button>
                            {drawerDeployment.status === 'success' && !drawerDeployment.is_rollback && (
                                <Button variant="secondary" size="sm" onClick={() => handleRollback(drawerDeployment.app_id, drawerDeployment.version)}>Rollback</Button>
                            )}
                            {drawerDeployment.status === 'success' && (
                                <Button size="sm" onClick={() => handleTriggerDeploy(drawerDeployment.app_id)} disabled={deployingAppId === drawerDeployment.app_id}>
                                    {deployingAppId === drawerDeployment.app_id ? 'Deploying...' : 'Redeploy'}
                                </Button>
                            )}
                        </div>
                        <div className="dom-specs">
                            <div className="sk-spec-card">
                                <div className="sk-spec-card__label">Status</div>
                                <div style={{ marginTop: 8 }}><Pill kind={getStatusColor(drawerDeployment.status)}>{drawerDeployment.status}</Pill></div>
                                {drawerDeployment.duration_seconds != null && <div className="sk-spec-card__sub">{drawerDeployment.duration_seconds}s</div>}
                            </div>
                            <div className="sk-spec-card">
                                <div className="sk-spec-card__label">Branch</div>
                                <div className="sk-spec-card__value">{drawerDeployment.branch}</div>
                                <div className="sk-spec-card__sub">{drawerDeployment.triggered_by}</div>
                            </div>
                            <div className="sk-spec-card">
                                <div className="sk-spec-card__label">Commit</div>
                                <div className="sk-spec-card__value">{drawerDeployment.commit_sha ? drawerDeployment.commit_sha.slice(0, 7) : '—'}</div>
                                <div className="sk-spec-card__sub">{formatDate(drawerDeployment.created_at)}</div>
                            </div>
                        </div>
                        {drawerDeployment.commit_message && (
                            <div className="dom-drawer__section">
                                <h3 className="dom-drawer__sectiontitle">Commit message</h3>
                                <p className="dom-drawer__hint">{drawerDeployment.commit_message.split('\n')[0]}</p>
                            </div>
                        )}
                        {drawerDeployment.error_message && (
                            <div className="dom-drawer__section">
                                <h3 className="dom-drawer__sectiontitle">Error</h3>
                                <p className="dom-drawer__hint dom-dns__error">{drawerDeployment.error_message}</p>
                            </div>
                        )}
                    </div>
                )}
            </Drawer>

            {/* Install Modal */}
            <Modal open={showInstallModal} onClose={() => setShowInstallModal(false)} title="Install Git Server" size="lg">
                            <div className="install-warning">
                                <AlertTriangle size={20} />
                                <div>
                                    <strong>This will install:</strong>
                                    <ul>
                                        <li>Gitea (Git server) - ~300MB RAM</li>
                                        <li>PostgreSQL database - ~200MB RAM</li>
                                    </ul>
                                </div>
                            </div>
                            <div className="form-group">
                                <Label>Admin Username</Label>
                                <Input type="text" value={installForm.adminUser} onChange={(e) => setInstallForm({ ...installForm, adminUser: e.target.value })} placeholder="admin" />
                            </div>
                            <div className="form-group">
                                <Label>Admin Email <span className="required">*</span></Label>
                                <Input type="email" value={installForm.adminEmail} onChange={(e) => setInstallForm({ ...installForm, adminEmail: e.target.value })} placeholder="admin@example.com" />
                            </div>
                            <div className="form-group">
                                <Label>Admin Password (leave empty to auto-generate)</Label>
                                <Input type="password" value={installForm.adminPassword} onChange={(e) => setInstallForm({ ...installForm, adminPassword: e.target.value })} placeholder="Auto-generate secure password" />
                            </div>
                        <div className="modal-actions">
                            <Button variant="outline" onClick={() => setShowInstallModal(false)}>Cancel</Button>
                            <Button onClick={handleInstall} disabled={actionLoading || !installForm.adminEmail}>
                                {actionLoading ? 'Installing...' : 'Install Git Server'}
                            </Button>
                        </div>
            </Modal>

            {/* Webhook Modal */}
            <Modal open={showWebhookModal} onClose={() => setShowWebhookModal(false)} title="Add Webhook" size="lg">
                            <div className="form-group">
                                <Label>Name <span className="required">*</span></Label>
                                <Input type="text" value={webhookForm.name} onChange={(e) => setWebhookForm({ ...webhookForm, name: e.target.value })} placeholder="My GitHub Repo" />
                            </div>
                            <div className="form-group">
                                <Label>Source</Label>
                                <select value={webhookForm.source} onChange={(e) => setWebhookForm({ ...webhookForm, source: e.target.value })}>
                                    <option value="github">GitHub</option>
                                    <option value="gitlab">GitLab</option>
                                    <option value="bitbucket">Bitbucket</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <Label>Repository URL <span className="required">*</span></Label>
                                <Input type="text" value={webhookForm.sourceRepoUrl} onChange={(e) => setWebhookForm({ ...webhookForm, sourceRepoUrl: e.target.value })} placeholder="https://github.com/user/repo.git" />
                            </div>
                            <div className="form-row">
                                <div className="form-group">
                                    <Label>Branch</Label>
                                    <Input type="text" value={webhookForm.sourceBranch} onChange={(e) => setWebhookForm({ ...webhookForm, sourceBranch: e.target.value })} placeholder="main" />
                                </div>
                                <div className="form-group">
                                    <Label>Sync Direction</Label>
                                    <select value={webhookForm.syncDirection} onChange={(e) => setWebhookForm({ ...webhookForm, syncDirection: e.target.value })}>
                                        <option value="pull">Pull (External → Local)</option>
                                        <option value="push">Push (Local → External)</option>
                                        <option value="bidirectional">Bidirectional</option>
                                    </select>
                                </div>
                            </div>
                            <div className="form-group checkbox">
                                <label>
                                    <input type="checkbox" checked={webhookForm.autoSync} onChange={(e) => setWebhookForm({ ...webhookForm, autoSync: e.target.checked })} />
                                    Auto-sync on push events
                                </label>
                            </div>
                            <div className="form-group">
                                <Label>Local Repository Name (optional)</Label>
                                <Input type="text" value={webhookForm.localRepoName} onChange={(e) => setWebhookForm({ ...webhookForm, localRepoName: e.target.value })} placeholder="Leave empty to use same name" />
                            </div>
                            <div className="form-section">
                                <h4>Deployment Settings</h4>
                                <p className="text-muted">Optionally deploy an application when code is pushed</p>
                                <div className="form-group">
                                    <Label>Deploy to Application</Label>
                                    <select value={webhookForm.appId} onChange={(e) => setWebhookForm({ ...webhookForm, appId: e.target.value, deployOnPush: e.target.value ? webhookForm.deployOnPush : false })}>
                                        <option value="">None (sync only)</option>
                                        {applications.map(app => <option key={app.id} value={app.id}>{app.name} ({app.status})</option>)}
                                    </select>
                                </div>
                                {webhookForm.appId && (
                                    <>
                                        <div className="form-group checkbox">
                                            <label>
                                                <input type="checkbox" checked={webhookForm.deployOnPush} onChange={(e) => setWebhookForm({ ...webhookForm, deployOnPush: e.target.checked })} />
                                                Deploy on push
                                            </label>
                                            <span className="form-hint">Automatically deploy when code is pushed to the branch</span>
                                        </div>
                                        <div className="form-group checkbox">
                                            <label>
                                                <input type="checkbox" checked={webhookForm.zeroDowntime} onChange={(e) => setWebhookForm({ ...webhookForm, zeroDowntime: e.target.checked })} />
                                                Zero-downtime deployment
                                            </label>
                                        </div>
                                        <div className="form-group">
                                            <Label>Pre-deploy Script (optional)</Label>
                                            <Textarea value={webhookForm.preDeployScript} onChange={(e) => setWebhookForm({ ...webhookForm, preDeployScript: e.target.value })} placeholder="#!/bin/bash&#10;npm install" rows={3} />
                                        </div>
                                        <div className="form-group">
                                            <Label>Post-deploy Script (optional)</Label>
                                            <Textarea value={webhookForm.postDeployScript} onChange={(e) => setWebhookForm({ ...webhookForm, postDeployScript: e.target.value })} placeholder="#!/bin/bash&#10;npm run cache:clear" rows={3} />
                                        </div>
                                    </>
                                )}
                            </div>
                        <div className="modal-actions">
                            <Button variant="outline" onClick={() => setShowWebhookModal(false)}>Cancel</Button>
                            <Button onClick={handleCreateWebhook} disabled={actionLoading || !webhookForm.name || !webhookForm.sourceRepoUrl}>
                                {actionLoading ? 'Creating...' : 'Create Webhook'}
                            </Button>
                        </div>
            </Modal>

            {/* Webhook Secret Modal */}
            <Modal open={!!webhookSecret} onClose={() => setWebhookSecret(null)} title="Webhook Secret">
                            <div className="secret-warning">
                                <AlertTriangle size={20} />
                                <span>Save this secret! It will not be shown again.</span>
                            </div>
                            <div className="secret-display">
                                <code>{webhookSecret}</code>
                                <Button size="sm" variant="outline" onClick={() => { navigator.clipboard.writeText(webhookSecret); toast.success('Secret copied'); }}>Copy</Button>
                            </div>
                            <p className="text-muted">Use this secret when configuring the webhook in your repository settings.</p>
                        <div className="modal-actions">
                            <Button onClick={() => setWebhookSecret(null)}>I&apos;ve Saved It</Button>
                        </div>
            </Modal>

            {/* Deployment Logs Modal */}
            <Modal
                open={showDeploymentLogs && !!selectedDeployment}
                onClose={() => setShowDeploymentLogs(false)}
                title={selectedDeployment ? `Deployment v${selectedDeployment.version} Logs` : ''}
                size="xl"
            >
                        {selectedDeployment && (<>
                            <div className="deployment-summary">
                                <div className="summary-item"><span className="label">Status:</span><Pill kind={getStatusColor(selectedDeployment.status)}>{selectedDeployment.status}</Pill></div>
                                {selectedDeployment.commit_sha && <div className="summary-item"><span className="label">Commit:</span><code className="git-hash">{selectedDeployment.commit_sha.slice(0, 7)}</code></div>}
                                <div className="summary-item"><span className="label">Branch:</span><span>{selectedDeployment.branch}</span></div>
                                <div className="summary-item"><span className="label">Triggered by:</span><span>{selectedDeployment.triggered_by}</span></div>
                                {selectedDeployment.duration_seconds != null && <div className="summary-item"><span className="label">Duration:</span><span>{selectedDeployment.duration_seconds}s</span></div>}
                            </div>
                            {selectedDeployment.error_message && <div className="deployment-error"><strong>Error:</strong> {selectedDeployment.error_message}</div>}
                            {selectedDeployment.pre_script_output && <div className="log-section"><h4>Pre-deployment Script Output</h4><pre className="log-output">{selectedDeployment.pre_script_output}</pre></div>}
                            {selectedDeployment.deploy_output && <div className="log-section"><h4>Deployment Output</h4><pre className="log-output">{selectedDeployment.deploy_output}</pre></div>}
                            {selectedDeployment.post_script_output && <div className="log-section"><h4>Post-deployment Script Output</h4><pre className="log-output">{selectedDeployment.post_script_output}</pre></div>}
                            {!selectedDeployment.pre_script_output && !selectedDeployment.deploy_output && !selectedDeployment.post_script_output && <div className="no-logs"><p>No deployment logs available.</p></div>}
                        </>)}
                        <div className="modal-actions">
                            <Button variant="outline" onClick={() => setShowDeploymentLogs(false)}>Close</Button>
                        </div>
            </Modal>

            {confirmDialog && (
                <ConfirmDialog
                    title={confirmDialog.title}
                    message={confirmDialog.message}
                    confirmText={confirmDialog.confirmText}
                    variant={confirmDialog.variant}
                    onConfirm={confirmDialog.onConfirm}
                    onCancel={confirmDialog.onCancel}
                />
            )}
        </PageLayout>
    );
}

export default Git;
