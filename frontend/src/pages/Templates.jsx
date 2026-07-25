import { useState, useEffect, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
    Search, X, Star, ExternalLink, BookOpen, Container, Globe, BarChart3,
    Database, Shield, Cloud, MessageSquare, Video, Music, Image, Home,
    Code, Server, GitBranch, Workflow, HardDrive, Lock, Users, FileText,
    Settings, Layers, LayoutTemplate, Copy, Check, Tag, Cpu,
    Newspaper, TrendingUp, Rocket, Box, Download, ChevronRight
} from 'lucide-react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
    SearchField, FilterDrawer, FilterButton, countActiveFilters, Drawer,
} from '@/components/ds';
import ServerPicker from '@/components/templates/ServerPicker';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import EmptyState from '../components/EmptyState';

// Featured templates (curated list)
const FEATURED_TEMPLATES = [
    'prompture-hub', 'wordpress', 'nextcloud', 'grafana', 'portainer',
    'uptime-kuma', 'gitea', 'vaultwarden', 'jellyfin', 'ghost', 'n8n'
];

// Icon strategy: every template ships an inline lucide-style base64 SVG in its
// YAML `icon:` field (rendered first by renderIcon). This map is the keyed
// fallback used when a template has no inline icon or it fails to load, so the
// grid never shows a broken image. Keep ids here in sync with backend/templates.
const TEMPLATE_ICONS = {
    // AI / LLM
    'prompture-hub': Cpu,
    'ollama-webui': Cpu,
    'qdrant': Database,
    'chroma': Database,
    'litellm': Cpu,
    'flowise': Workflow,
    'langflow': Workflow,
    'anythingllm': Cpu,
    'librechat': MessageSquare,
    'agentsite': Cpu,
    // Monitoring
    'uptime-kuma': BarChart3,
    'grafana': BarChart3,
    'prometheus': BarChart3,
    'netdata': BarChart3,
    'loki': BarChart3,
    'jaeger': BarChart3,
    'plausible': BarChart3,
    'umami': BarChart3,
    'beszel': BarChart3,
    'signoz': BarChart3,
    // Search
    'meilisearch': Search,
    'typesense': Search,
    'searxng': Search,
    // CMS / Blog
    'wordpress': Globe,
    'ghost': FileText,
    'strapi': Layers,
    'directus': Database,
    'payload': Layers,
    'grav': FileText,
    // DevOps
    'portainer': Container,
    'jenkins': Workflow,
    'drone': Workflow,
    'gitlab-runner': GitBranch,
    'sonarqube': Code,
    'registry': Container,
    'vault': Lock,
    // Storage
    'nextcloud': Cloud,
    'minio': Cloud,
    'seafile': Cloud,
    'filebrowser': HardDrive,
    'syncthing': Cloud,
    'duplicati': HardDrive,
    // Collaboration
    'rocketchat': MessageSquare,
    'mattermost': MessageSquare,
    'matrix-synapse': MessageSquare,
    'jitsi': Video,
    // Media
    'jellyfin': Video,
    'plex': Video,
    'photoprism': Image,
    'immich': Image,
    'navidrome': Music,
    'audiobookshelf': Music,
    'calibre-web': BookOpen,
    'sonarr': Video,
    'radarr': Video,
    'jellyseerr': Video,
    'prowlarr': Search,
    'qbittorrent': HardDrive,
    // News / RSS
    'freshrss': Newspaper,
    'miniflux': Newspaper,
    // Documents
    'paperless-ngx': FileText,
    'stirling-pdf': FileText,
    'memos': FileText,
    // Finance
    'actualbudget': TrendingUp,
    'firefly-iii': TrendingUp,
    // Project management
    'vikunja': Check,
    'plane': Workflow,
    // Productivity
    'bookstack': BookOpen,
    'wikijs': BookOpen,
    'outline': FileText,
    'excalidraw': FileText,
    'n8n': Workflow,
    // Notifications
    'gotify': MessageSquare,
    'ntfy': MessageSquare,
    // Security
    'vaultwarden': Lock,
    'authelia': Shield,
    'keycloak': Shield,
    'crowdsec': Shield,
    'authentik': Shield,
    'wg-easy': Shield,
    'pihole': Shield,
    // Business / niche
    'chatwoot': MessageSquare,
    'documenso': FileText,
    'metabase': BarChart3,
    'posthog': TrendingUp,
    'nodebb': Users,
    'linkding': BookOpen,
    'karakeep': BookOpen,
    // Database tools
    'phpmyadmin': Database,
    'pgadmin': Database,
    'redis-commander': Database,
    'mongo-express': Database,
    // Home Automation
    'homeassistant': Home,
    'nodered': Workflow,
    'mosquitto': Home,
    'zigbee2mqtt': Home,
    // Development
    'code-server': Code,
    'gitea': GitBranch,
    // Networking
    'traefik': Server,
    'caddy': Server,
    'nginx-proxy-manager': Server,
    // Custom apps
    'php-app': Code,
    'python-app': Code,
    'node-app': Code
};

const SORT_OPTIONS = [
    { value: 'featured', label: 'Featured first' },
    { value: 'name-asc', label: 'Name (A–Z)' },
    { value: 'name-desc', label: 'Name (Z–A)' },
];

const KIND_OPTIONS = [
    { value: 'compose', label: 'One-click' },
    { value: 'repo', label: 'Git repo' },
];

const Templates = () => {
    const navigate = useNavigate();
    const toast = useToast();
    const [searchParams, setSearchParams] = useSearchParams();

    const [templates, setTemplates] = useState([]);
    const [categories, setCategories] = useState([]);
    const [loading, setLoading] = useState(true);
    const [failedIcons, setFailedIcons] = useState(new Set());
    const [selectedTemplate, setSelectedTemplate] = useState(null);
    const [showInstallModal, setShowInstallModal] = useState(false);
    const [copiedCompose, setCopiedCompose] = useState(false);
    const [filtersOpen, setFiltersOpen] = useState(false);
    // Repo-template manifest inspection (populated when a repo detail opens).
    const [repoManifest, setRepoManifest] = useState(null);
    const [repoManifestLoading, setRepoManifestLoading] = useState(false);

    // Initialize from URL params
    const selectedCategory = searchParams.get('category') || '';
    const selectedKind = searchParams.get('kind') || '';
    const searchQuery = searchParams.get('search') || '';
    const sortBy = searchParams.get('sort') || 'featured';
    const installTemplateId = searchParams.get('install');

    useEffect(() => {
        loadData();
    }, []);

    // Compat: the old `#deploy-templates` anchor (linked from the wizard + docs)
    // now redirects to the repo-kind filtered view of the unified grid.
    useEffect(() => {
        if (window.location.hash === '#deploy-templates' && !selectedKind) {
            updateFilters({ kind: 'repo' });
            // Drop the hash so a refresh doesn't re-trigger.
            window.history.replaceState(null, '', window.location.pathname + window.location.search);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Auto-open install modal if template ID is in URL (compose templates only;
    // repo templates deploy through the wizard, never the install modal).
    useEffect(() => {
        if (installTemplateId && templates.length > 0 && !loading) {
            if (installTemplateId === 'wordpress') {
                navigate('/wordpress', { replace: true });
                return;
            }
            const template = templates.find(t => t.id === installTemplateId);
            if (template && template.kind !== 'repo') {
                handleViewTemplate(template).then(() => {
                    setShowInstallModal(true);
                });
                const newParams = new URLSearchParams(searchParams);
                newParams.delete('install');
                setSearchParams(newParams, { replace: true });
            }
        }
    }, [installTemplateId, templates, loading]);

    useEffect(() => {
        loadTemplates();
    }, [selectedCategory, searchQuery]);

    function updateFilters(updates) {
        const newParams = new URLSearchParams(searchParams);
        Object.entries(updates).forEach(([key, value]) => {
            if (value) {
                newParams.set(key, value);
            } else {
                newParams.delete(key);
            }
        });
        setSearchParams(newParams);
    }

    function setSelectedCategoryFilter(category) {
        updateFilters({ category });
    }

    function setSearchQueryFilter(search) {
        updateFilters({ search: search || null });
    }

    function clearAllFilters() {
        setSearchParams(new URLSearchParams());
    }

    async function loadData() {
        try {
            const [templatesRes, categoriesRes] = await Promise.all([
                api.listTemplates(),
                api.getTemplateCategories()
            ]);
            setTemplates(templatesRes.templates || []);
            setCategories(categoriesRes.categories || []);
        } catch (err) {
            toast.error('Failed to load templates');
        } finally {
            setLoading(false);
        }
    }

    async function loadTemplates() {
        try {
            const result = await api.listTemplates(selectedCategory || null, searchQuery || null);
            setTemplates(result.templates || []);
        } catch (err) {
            console.error('Failed to load templates:', err);
        }
    }

    function handleIconError(templateId) {
        setFailedIcons(prev => new Set(prev).add(templateId));
    }

    function getTemplateIcon(templateId) {
        return TEMPLATE_ICONS[templateId] || Layers;
    }

    function renderIcon(template, size = 32) {
        const IconComponent = getTemplateIcon(template.id);
        const hasIcon = template.icon && !failedIcons.has(template.id);

        if (hasIcon) {
            return (
                <img
                    src={template.icon}
                    alt={template.name}
                    onError={() => handleIconError(template.id)}
                />
            );
        }
        return <IconComponent size={size} />;
    }

    function getCategoryIcon(category) {
        const icons = {
            monitoring: BarChart3,
            devops: Settings,
            docker: Container,
            cms: FileText,
            blog: BookOpen,
            storage: HardDrive,
            collaboration: Users,
            git: GitBranch,
            development: Code,
            networking: Globe,
            proxy: Workflow,
            ssl: Lock,
            productivity: Layers,
            management: Server,
            publishing: Newspaper,
            media: Video,
            security: Shield,
            database: Database,
            'home-automation': Home,
            analytics: TrendingUp,
            iot: Cpu,
            // AI / LLM
            ai: Cpu,
            llm: Cpu,
            gateway: Server,
            rag: Cpu,
            chat: MessageSquare,
            'low-code': Workflow,
            workflow: Workflow,
            website: Globe,
            deployment: Rocket,
            // Search
            search: Search,
            vector: Database,
            // Notifications / messaging
            notifications: MessageSquare,
            messaging: MessageSquare,
            communication: MessageSquare,
            support: MessageSquare,
            // Documents / news
            documents: FileText,
            pdf: FileText,
            notes: FileText,
            rss: Newspaper,
            news: Newspaper,
            // Finance / business
            finance: TrendingUp,
            business: TrendingUp,
            // Productivity / tasks
            tasks: Workflow,
            'project-management': Workflow,
            bookmarks: BookOpen,
            ebooks: BookOpen,
            audiobooks: Music,
            automation: Workflow,
            downloads: HardDrive,
            // Identity / networking / privacy
            identity: Shield,
            sso: Shield,
            vpn: Shield,
            privacy: Lock,
            dns: Globe,
            forum: Users,
            community: Users,
            // Observability
            observability: BarChart3,
            apm: BarChart3
        };
        const Icon = icons[category] || Container;
        return <Icon size={14} />;
    }

    async function handleViewTemplate(template) {
        // WordPress has its own dedicated page
        if (template.id === 'wordpress') {
            navigate('/wordpress');
            return;
        }
        try {
            const result = await api.getTemplate(template.id);
            if (result.template) {
                setSelectedTemplate(result.template);
                if (result.template.kind === 'repo') {
                    loadRepoManifest(result.template);
                }
            }
        } catch (err) {
            toast.error('Failed to load template details');
        }
    }

    // Fetch the repo template's detected manifests / env from the Phase 1
    // endpoint so the detail body shows real data (or labeled hints).
    function loadRepoManifest(template) {
        setRepoManifest(null);
        setRepoManifestLoading(true);
        api.inspectTemplateManifest(template.id, template.repo?.branch)
            .then(data => setRepoManifest(data))
            .catch(() => setRepoManifest(null))
            .finally(() => setRepoManifestLoading(false));
    }

    function deployRepoTemplate(templateId) {
        navigate(`/services/new?template=${encodeURIComponent(templateId)}`);
    }

    // Hover-reveal primary action. Repo templates route to the wizard; compose
    // templates skip the detail modal and go straight to install.
    async function handleDeploy(template) {
        if (template.kind === 'repo') {
            deployRepoTemplate(template.id);
            return;
        }
        if (template.id === 'wordpress') {
            navigate('/wordpress');
            return;
        }
        try {
            const result = await api.getTemplate(template.id);
            if (result.template) {
                setSelectedTemplate(result.template);
                setShowInstallModal(true);
            }
        } catch (err) {
            toast.error('Failed to load template details');
        }
    }

    function isFeatured(templateId) {
        return FEATURED_TEMPLATES.includes(templateId);
    }

    // Sort templates
    function sortTemplates(list) {
        const sorted = [...list];
        switch (sortBy) {
            case 'name-asc':
                return sorted.sort((a, b) => a.name.localeCompare(b.name));
            case 'name-desc':
                return sorted.sort((a, b) => b.name.localeCompare(a.name));
            case 'featured':
                return sorted.sort((a, b) => {
                    const aFeatured = isFeatured(a.id);
                    const bFeatured = isFeatured(b.id);
                    if (aFeatured && !bFeatured) return -1;
                    if (!aFeatured && bFeatured) return 1;
                    return a.name.localeCompare(b.name);
                });
            default:
                return sorted;
        }
    }

    // Kind is filtered client-side (the list endpoint filters category + search).
    const kindFiltered = selectedKind
        ? templates.filter(t => (t.kind || 'compose') === selectedKind)
        : templates;
    const sortedTemplates = sortTemplates(kindFiltered);

    // The active-filter badge counts real filters only (category + kind); sort is
    // an ordering, not a filter, so it never inflates the count.
    const activeFilterCount = countActiveFilters({ category: selectedCategory, kind: selectedKind });
    const hasActiveFilters = Boolean(selectedCategory || selectedKind || searchQuery
        || (sortBy && sortBy !== 'featured'));

    // How many templates each option would match, counted over the whole
    // catalog rather than the current result set — a count that shrank to 0 as
    // you filtered would say nothing about whether the option is worth a click.
    const optionCounts = useMemo(() => {
        const byKind = {};
        const byCategory = {};
        templates.forEach((t) => {
            const kind = t.kind || 'compose';
            byKind[kind] = (byKind[kind] || 0) + 1;
            (t.categories || []).forEach((c) => {
                byCategory[c] = (byCategory[c] || 0) + 1;
            });
        });
        return { byKind, byCategory };
    }, [templates]);

    const filterGroups = [
        {
            key: 'kind',
            label: 'Type',
            type: 'single',
            options: KIND_OPTIONS.map(o => ({ ...o, count: optionCounts.byKind[o.value] || 0 })),
        },
        {
            key: 'category',
            label: 'Category',
            type: 'single',
            options: categories.map(cat => ({
                value: cat,
                label: cat,
                count: optionCounts.byCategory[cat] || 0,
            })),
        },
        {
            key: 'sort',
            label: 'Sort',
            type: 'single',
            options: SORT_OPTIONS,
        },
    ];

    const filterValue = { category: selectedCategory, kind: selectedKind, sort: sortBy };

    function handleFilterChange(next) {
        updateFilters({
            category: next.category || null,
            kind: next.kind || null,
            sort: next.sort && next.sort !== 'featured' ? next.sort : null,
        });
    }

    useTopbarActions(() =>
        <>
            <SearchField
                value={searchQuery}
                onSearch={setSearchQueryFilter}
                placeholder="Search templates…"
            />
            <FilterButton count={activeFilterCount} onClick={() => setFiltersOpen(true)} />
        </>,
        [searchQuery, activeFilterCount]
    );

    if (loading) {
        return (
            <div className="sk-tabgroup__inner">
                <EmptyState loading title="Loading templates" />
            </div>
        );
    }

    return (
        <div className="sk-tabgroup__inner templates-page">
            {/* The catalog is not the only way in: a repo or an archive skips
                templates entirely, so both routes lead the page rather than
                hiding behind the New Service tab. */}
            <div className="tpl-quickstart">
                <button type="button" className="tpl-quickstart__card" onClick={() => navigate('/services/new?source=github')}>
                    <span className="tpl-quickstart__ico"><GitBranch size={18} /></span>
                    <span className="tpl-quickstart__body">
                        <span className="tpl-quickstart__title">Import from GitHub</span>
                        <span className="tpl-quickstart__sub">Connect a repo and auto-deploy on every push</span>
                    </span>
                    <ChevronRight size={16} className="tpl-quickstart__arrow" />
                </button>
                <button type="button" className="tpl-quickstart__card" onClick={() => navigate('/services/new?source=archive')}>
                    <span className="tpl-quickstart__ico"><Download size={18} /></span>
                    <span className="tpl-quickstart__body">
                        <span className="tpl-quickstart__title">Import a ZIP</span>
                        <span className="tpl-quickstart__sub">Drop in a project archive to build &amp; run</span>
                    </span>
                    <ChevronRight size={16} className="tpl-quickstart__arrow" />
                </button>
            </div>

            {/* One header row: result count, whatever filtering is currently in
                force (as removable chips), and sort. Categories are not listed
                here — every filter lives in the FilterDrawer, so there is one
                place to look rather than two competing ones. */}
            <div className="templates-results-header">
                <span className="results-count">
                    {sortedTemplates.length} template{sortedTemplates.length !== 1 ? 's' : ''}
                </span>
                <div className="active-filters">
                    {selectedKind && (
                        <button type="button" className="filter-chip"
                            onClick={() => updateFilters({ kind: null })}>
                            {KIND_OPTIONS.find(k => k.value === selectedKind)?.label || selectedKind}
                            <X size={12} />
                        </button>
                    )}
                    {selectedCategory && (
                        <button type="button" className="filter-chip"
                            onClick={() => setSelectedCategoryFilter(null)}>
                            {selectedCategory}
                            <X size={12} />
                        </button>
                    )}
                    {searchQuery && (
                        <button type="button" className="filter-chip"
                            onClick={() => setSearchQueryFilter('')}>
                            &ldquo;{searchQuery}&rdquo;
                            <X size={12} />
                        </button>
                    )}
                    {hasActiveFilters && (
                        <Button variant="ghost" size="sm" className="clear-all-btn" onClick={clearAllFilters}>
                            Clear all
                        </Button>
                    )}
                </div>
                {/* The two orders people actually reach for; the full sort list
                    (incl. Z–A) stays in the filter drawer. */}
                <div className="tpl-sort" role="group" aria-label="Sort templates">
                    {[['featured', 'Featured'], ['name-asc', 'A–Z']].map(([value, label]) => (
                        <button
                            type="button"
                            key={value}
                            className={sortBy === value ? 'is-active' : ''}
                            onClick={() => updateFilters({ sort: value === 'featured' ? null : value })}
                        >
                            {label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Templates Grid */}
            <div className="templates-grid">
                {sortedTemplates.length === 0 ? (
                    <EmptyState
                        icon={LayoutTemplate}
                        title="No templates found"
                        description={hasActiveFilters ? 'Try adjusting your filters' : 'No templates are available yet'}
                        action={hasActiveFilters && (
                            <Button variant="outline" size="sm" onClick={clearAllFilters}>
                                Clear Filters
                            </Button>
                        )}
                    />
                ) : (
                    sortedTemplates.map(template => {
                        const isRepo = (template.kind || 'compose') === 'repo';
                        return (
                            <div key={template.id} className="tpl-card" onClick={() => handleViewTemplate(template)}>
                                {isFeatured(template.id) && (
                                    <span className="tpl-ft" title="Featured">
                                        <Star size={14} />
                                    </span>
                                )}
                                <div className="tpl-top">
                                    <span className="tpl-ico">
                                        {renderIcon(template, 22)}
                                    </span>
                                    <div className="tpl-id">
                                        <div className="tpl-name">{template.name}</div>
                                        <div className="tpl-ver">v{template.version}</div>
                                    </div>
                                </div>
                                <p className="tpl-desc">{template.description}</p>
                                <div className="tpl-tags">
                                    <Badge variant={isRepo ? 'info' : 'outline'} className="tpl-kind">
                                        {isRepo ? 'Git repo' : 'One-click'}
                                    </Badge>
                                    {(template.categories || []).slice(0, 2).map(cat => (
                                        <span key={cat} className="tg">
                                            {cat}
                                        </span>
                                    ))}
                                    {template.website && (
                                        <span className="tpl-link" title="Has website">
                                            <ExternalLink size={12} />
                                        </span>
                                    )}
                                    {template.documentation && (
                                        <span className="tpl-link" title="Has documentation">
                                            <BookOpen size={12} />
                                        </span>
                                    )}
                                    <Button
                                        size="sm"
                                        className="tpl-deploy"
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            handleDeploy(template);
                                        }}
                                    >
                                        <Rocket size={12} /> Deploy
                                    </Button>
                                </div>
                            </div>
                        );
                    })
                )}
            </div>

            {/* Template Detail Modal */}
            {selectedTemplate && !showInstallModal && (
                <div className="modal-overlay" onClick={() => { setSelectedTemplate(null); setRepoManifest(null); }}>
                    <div className="modal template-detail-drawer" onClick={e => e.stopPropagation()}>
                        <div className="modal-header">
                            <div className="template-detail-header">
                                <div className="template-icon-large">
                                    {renderIcon(selectedTemplate, 40)}
                                </div>
                                <div>
                                    <h2>{selectedTemplate.name}</h2>
                                    <span className="template-version">Version {selectedTemplate.version}</span>
                                </div>
                            </div>
                            <button type="button" className="modal-close" onClick={() => { setSelectedTemplate(null); setRepoManifest(null); }}>&times;</button>
                        </div>
                        <div className="modal-body">
                            <p className="template-full-description">{selectedTemplate.description}</p>

                            <div className="template-links">
                                {selectedTemplate.website && (
                                    <a href={selectedTemplate.website} target="_blank" rel="noopener noreferrer">
                                        <Button variant="outline" size="sm">
                                            <ExternalLink size={14} /> Website
                                        </Button>
                                    </a>
                                )}
                                {selectedTemplate.documentation && (
                                    <a href={selectedTemplate.documentation} target="_blank" rel="noopener noreferrer">
                                        <Button variant="outline" size="sm">
                                            <BookOpen size={14} /> Documentation
                                        </Button>
                                    </a>
                                )}
                            </div>

                            {selectedTemplate.kind === 'repo' ? (
                                <RepoTemplateDetailBody
                                    template={selectedTemplate}
                                    manifest={repoManifest}
                                    loading={repoManifestLoading}
                                    getCategoryIcon={getCategoryIcon}
                                />
                            ) : (
                                <div className="template-details-grid">
                                    <div className="detail-section">
                                        <h4><Tag size={16} /> Categories</h4>
                                        <div className="template-categories">
                                            {(selectedTemplate.categories || []).map(cat => (
                                                <span key={cat} className="category-badge">
                                                    {getCategoryIcon(cat)} {cat}
                                                </span>
                                            ))}
                                        </div>
                                    </div>

                                    {selectedTemplate.requirements && (
                                        <div className="detail-section">
                                            <h4><Cpu size={16} /> Requirements</h4>
                                            <div className="requirements-list">
                                                {selectedTemplate.requirements.memory && (
                                                    <div className="requirement-item">
                                                        <span className="requirement-label">Memory:</span>
                                                        <span className="requirement-value">{selectedTemplate.requirements.memory}</span>
                                                    </div>
                                                )}
                                                {selectedTemplate.requirements.storage && (
                                                    <div className="requirement-item">
                                                        <span className="requirement-label">Storage:</span>
                                                        <span className="requirement-value">{selectedTemplate.requirements.storage}</span>
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    )}

                                    {selectedTemplate.variables && selectedTemplate.variables.length > 0 && (
                                        <div className="detail-section">
                                            <h4><Settings size={16} /> Configuration Variables</h4>
                                            <div className="variables-list">
                                                {selectedTemplate.variables
                                                    .filter(v => !v.hidden)
                                                    .sort((a, b) => (b.required ? 1 : 0) - (a.required ? 1 : 0))
                                                    .map(variable => (
                                                    <div key={variable.name} className={`variable-item ${variable.required ? 'required' : ''}`}>
                                                        <div className="variable-header">
                                                            <span className="variable-name">{variable.name}</span>
                                                            {variable.required && <span className="required-badge">Required</span>}
                                                            {variable.auto_generated && <span className="auto-badge">Auto</span>}
                                                        </div>
                                                        {variable.description && (
                                                            <span className="variable-description">{variable.description}</span>
                                                        )}
                                                        {variable.default && !variable.auto_generated && (
                                                            <span className="variable-default">Default: {variable.default}</span>
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {selectedTemplate.ports && selectedTemplate.ports.length > 0 && (
                                        <div className="detail-section">
                                            <h4><Server size={16} /> Exposed Ports</h4>
                                            <div className="ports-list">
                                                {selectedTemplate.ports.map((port, index) => (
                                                    <div key={index} className="port-item">
                                                        <span className="port-number">{port.port}</span>
                                                        <span className="port-protocol">{port.protocol}</span>
                                                        {port.description && (
                                                            <span className="port-description">{port.description}</span>
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {selectedTemplate.has_compose && (
                                        <div className="detail-section">
                                            <h4>
                                                <Container size={16} /> Docker Compose
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    className="copy-btn"
                                                    onClick={() => {
                                                        navigator.clipboard.writeText('docker-compose.yml available after install');
                                                        setCopiedCompose(true);
                                                        setTimeout(() => setCopiedCompose(false), 2000);
                                                    }}
                                                >
                                                    {copiedCompose ? <Check size={14} /> : <Copy size={14} />}
                                                </Button>
                                            </h4>
                                            <div className="compose-preview">
                                                <code>Docker Compose configuration will be generated during installation</code>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                        <div className="modal-footer">
                            <Button variant="outline" onClick={() => { setSelectedTemplate(null); setRepoManifest(null); }}>
                                Close
                            </Button>
                            {selectedTemplate.kind === 'repo' ? (
                                <Button onClick={() => deployRepoTemplate(selectedTemplate.id)}>
                                    <Rocket size={14} /> Deploy
                                </Button>
                            ) : (
                                <Button onClick={() => setShowInstallModal(true)}>
                                    Install Template
                                </Button>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* Install Modal (compose templates only) */}
            {showInstallModal && selectedTemplate && (
                <InstallModal
                    template={selectedTemplate}
                    renderIcon={renderIcon}
                    onClose={() => {
                        setShowInstallModal(false);
                        setSelectedTemplate(null);
                    }}
                    onSuccess={(appId) => {
                        setShowInstallModal(false);
                        setSelectedTemplate(null);
                        toast.success('Application installed successfully!');
                        navigate(`/services/${appId}/logs`);
                    }}
                />
            )}

            <FilterDrawer
                open={filtersOpen}
                onOpenChange={setFiltersOpen}
                groups={filterGroups}
                value={filterValue}
                onChange={handleFilterChange}
                title="Filter templates"
                activeCount={activeFilterCount}
                resultCount={sortedTemplates.length}
                resultNoun="template"
            />
        </div>
    );
};

// Repo-template detail body: repo URL, detected manifests, and env preview from
// the /templates/<id>/manifest endpoint (real inspection or labeled hints).
const RepoTemplateDetailBody = ({ template, manifest, loading, getCategoryIcon }) => {
    const repo = template.repo || {};
    const data = manifest?.manifest || null;
    const sourceLabel = manifest?.source === 'repo'
        ? 'Detected from repository'
        : manifest?.source === 'template-hints'
            ? 'From template hints'
            : null;

    return (
        <div className="template-details-grid">
            <div className="detail-section">
                <h4><GitBranch size={16} /> Repository</h4>
                <div className="repo-detail">
                    <a href={repo.url} target="_blank" rel="noopener noreferrer" className="repo-detail__url">
                        {repo.url}
                    </a>
                    <div className="repo-detail__meta">
                        {repo.branch && <span>branch: <code>{repo.branch}</code></span>}
                        {repo.app_type && <span>type: <code>{repo.app_type}</code></span>}
                        {repo.build_method && <span>build: <code>{repo.build_method}</code></span>}
                        {repo.port && <span>port: <code>{repo.port}</code></span>}
                    </div>
                </div>
            </div>

            {(template.categories || []).length > 0 && (
                <div className="detail-section">
                    <h4><Tag size={16} /> Categories</h4>
                    <div className="template-categories">
                        {(template.categories || []).map(cat => (
                            <span key={cat} className="category-badge">
                                {getCategoryIcon(cat)} {cat}
                            </span>
                        ))}
                    </div>
                </div>
            )}

            <div className="detail-section">
                <h4>
                    <Layers size={16} /> Detected manifests
                    {sourceLabel && <span className="detail-source-tag">{sourceLabel}</span>}
                </h4>
                {loading ? (
                    <p className="text-muted">Inspecting repository…</p>
                ) : (data?.manifests || []).length > 0 ? (
                    <div className="manifest-file-list">
                        {data.manifests.map(m => (
                            <span key={m.file} className="manifest-file">
                                <Check size={13} /> {m.file}
                            </span>
                        ))}
                    </div>
                ) : (
                    <p className="text-muted">No deploy manifests detected.</p>
                )}
            </div>

            {!loading && (data?.env || []).length > 0 && (
                <div className="detail-section">
                    <h4><Lock size={16} /> Environment</h4>
                    <div className="env-preview-list">
                        {data.env.map(env => (
                            <span
                                key={env.key}
                                className={`env-preview-chip ${env.secret ? 'env-preview-chip--secret' : ''}`}
                            >
                                {env.key}{env.required ? ' *' : ''}
                            </span>
                        ))}
                    </div>
                    <p className="env-preview-note text-muted">
                        Secret values stay empty until you add them to the service environment.
                    </p>
                </div>
            )}
        </div>
    );
};

const InstallModal = ({ template, onClose, onSuccess, renderIcon }) => {
    const toast = useToast();
    const navigate = useNavigate();
    const [appName, setAppName] = useState(template.id.toLowerCase().replace(/[^a-z0-9-]/g, '-'));
    const [variables, setVariables] = useState({});
    const [servers, setServers] = useState([{ id: 'local', name: 'Local server', is_local: true }]);
    const [selectedServerId, setSelectedServerId] = useState('local');
    const [installing, setInstalling] = useState(false);
    const [errors, setErrors] = useState([]);
    // Managed-sites base domain, so the drawer can offer the subdomain this
    // service would get instead of leaving the user to wire DNS afterwards.
    const [baseDomain, setBaseDomain] = useState(null);
    const [httpsBase, setHttpsBase] = useState(false);

    useEffect(() => {
        // Initialize variables with defaults
        const defaults = {};
        (template.variables || []).forEach(v => {
            if (v.default) {
                defaults[v.name] = v.default;
            }
        });
        setVariables(defaults);
    }, [template]);

    useEffect(() => {
        loadServers();
        api.getSiteBaseDomains()
            .then((data) => {
                const bases = data?.base_domains || [];
                const chosen = bases.find((b) => b.domain === data?.default) || bases[0];
                setBaseDomain(chosen?.domain || null);
                setHttpsBase(!!chosen?.https_enabled);
            })
            .catch(() => setBaseDomain(null));
    }, []);

    async function loadServers() {
        try {
            const data = await api.getAvailableServers();
            const list = Array.isArray(data) ? data : [];
            if (list.length > 0) {
                setServers(list);
                setSelectedServerId(list[0].id);
            }
        } catch {
            setServers([{ id: 'local', name: 'Local server', is_local: true }]);
            setSelectedServerId('local');
        }
    }

    const domainPreview = baseDomain && appName ? `${appName}.${baseDomain}` : null;

    async function handleInstall(e) {
        e.preventDefault();
        setInstalling(true);
        setErrors([]);

        try {
            // Validate first
            const validation = await api.validateTemplateInstall(template.id, appName, variables);
            if (!validation.valid) {
                setErrors(validation.errors || ['Validation failed']);
                setInstalling(false);
                return;
            }

            // Install
            const result = await api.installTemplate(template.id, appName, variables, {
                serverId: selectedServerId
            });
            if (result.success && result.job_id) {
                // Job started — hand off to the full-page Deploy Console.
                onClose?.();
                navigate(`/deployments/${result.job_id}`);
            } else if (result.success) {
                setInstalling(false);
                onSuccess(result.app_id);
            } else {
                setErrors([result.error || 'Installation failed']);
                setInstalling(false);
            }
        } catch (err) {
            setErrors([err?.data?.error || err.message || 'Installation failed']);
            setInstalling(false);
        }
    }

    const visibleVars = (template.variables || []).filter(v => !v.hidden);

    return (
        <Drawer
            open
            onOpenChange={(next) => { if (!next) onClose?.(); }}
            title={`Deploy ${template.name}`}
            subtitle={[`v${template.version}`, ...(template.categories || []).slice(0, 3)].join(' · ')}
            icon={renderIcon(template, 20)}
            width={560}
            className="tpl-deploy-drawer"
        >
            <form onSubmit={handleInstall} className="tpl-deploy-drawer__form">
                <div className="tpl-deploy-drawer__body">
                    {errors.length > 0 && (
                        <div className="alert alert-danger">
                            <ul>
                                {errors.map((error, i) => <li key={i}>{error}</li>)}
                            </ul>
                        </div>
                    )}

                    <p className="tpl-deploy-drawer__desc">{template.description}</p>

                    <div className="tpl-deploy-drawer__field">
                        <label htmlFor="tpl-deploy-name">Service name</label>
                        <div className="tpl-deploy-drawer__input">
                            <Box size={15} />
                            <input
                                id="tpl-deploy-name"
                                type="text"
                                value={appName}
                                onChange={(e) => setAppName(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''))}
                                placeholder="my-app"
                                minLength={2}
                                required
                            />
                        </div>
                        <span className="tpl-deploy-drawer__hint">
                            Lowercase letters, numbers, and hyphens only (min 2 chars)
                        </span>
                    </div>

                    {/* Only shown once a managed-sites base domain exists — with
                        no base there is no subdomain to promise, and a dead
                        field would be worse than none. */}
                    {domainPreview && (
                        <div className="tpl-deploy-drawer__field">
                            <span className="tpl-deploy-drawer__label">Domain</span>
                            <div className="tpl-deploy-drawer__input tpl-deploy-drawer__input--readonly">
                                <Globe size={15} />
                                <span className="tpl-deploy-drawer__domain">{domainPreview}</span>
                            </div>
                            <span className="tpl-deploy-drawer__hint">
                                {httpsBase
                                    ? 'Published automatically with HTTPS once the deploy finishes'
                                    : 'Published automatically once the deploy finishes'}
                            </span>
                        </div>
                    )}

                    <div className="tpl-deploy-drawer__field">
                        <span className="tpl-deploy-drawer__label">Deploy to server</span>
                        <ServerPicker
                            servers={servers}
                            value={selectedServerId}
                            onChange={setSelectedServerId}
                        />
                    </div>

                    {visibleVars.length > 0 && (
                        <div className="tpl-deploy-drawer__field">
                            <span className="tpl-deploy-drawer__label">Configuration</span>
                            {visibleVars.map(variable => (
                                <div key={variable.name} className="form-group">
                                    <label>
                                        {variable.name}
                                        {variable.required && ' *'}
                                    </label>
                                    {variable.options ? (
                                        <select
                                            value={variables[variable.name] || ''}
                                            onChange={(e) => setVariables({...variables, [variable.name]: e.target.value})}
                                            required={variable.required}
                                        >
                                            <option value="">Select...</option>
                                            {variable.options.map(opt => (
                                                <option key={opt} value={opt}>{opt}</option>
                                            ))}
                                        </select>
                                    ) : variable.type === 'password' ? (
                                        <Input
                                            type="password"
                                            value={variables[variable.name] || ''}
                                            onChange={(e) => setVariables({...variables, [variable.name]: e.target.value})}
                                            placeholder={variable.default ? '(auto-generated)' : ''}
                                            required={variable.required && !variable.default}
                                        />
                                    ) : (
                                        <Input
                                            type={variable.type === 'port' ? 'number' : 'text'}
                                            value={variables[variable.name] || ''}
                                            onChange={(e) => setVariables({...variables, [variable.name]: e.target.value})}
                                            placeholder={variable.default || ''}
                                            required={variable.required}
                                        />
                                    )}
                                    {variable.description && (
                                        <span className="form-help">{variable.description}</span>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                <div className="tpl-deploy-drawer__foot">
                    <Button type="button" variant="outline" onClick={onClose} disabled={installing}>
                        Cancel
                    </Button>
                    <Button type="submit" disabled={installing}>
                        <Rocket size={15} />
                        {installing ? 'Deploying…' : `Deploy ${template.name}`}
                    </Button>
                </div>
            </form>
        </Drawer>
    );
};

export default Templates;
