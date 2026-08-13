import { useState, useEffect, useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
    Globe, Plus, ShieldCheck, RefreshCw, Trash2, ExternalLink,
    AlertTriangle, Lock, Search, ChevronRight,
} from 'lucide-react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import { useAuth } from '../contexts/AuthContext';
import EmptyState from '../components/EmptyState';
import Modal from '@/components/Modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import {
    Select, SelectTrigger, SelectContent, SelectItem, SelectValue,
} from '@/components/ui/select';
import { SearchField, Pill, Drawer } from '@/components/ds';
import {
    DataGrid, GridViewPicker, GridChips, GridBulkBar, GridFooter,
    GridToolsMenu, GridFilterDrawer, GridFilterButton,
    useGridConfig, useGridRows, exportRows,
} from '@/components/ds/grid';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import useFocusParam from '@/hooks/useFocusParam';
import RegistrarPortfolio from '../components/domains/RegistrarPortfolio';
import { ProviderBrandIcon } from '../components/icons/ProviderBrands';
import DomainDnsPanel from '../components/domains/DomainDnsPanel';
import PluginSlot from '../components/PluginSlot';
import { formatExpiry } from '../utils/expiry';

const DAY = 86400000;
const norm = (s) => (s || '').toLowerCase().replace(/\.$/, '');
const daysUntil = (iso) => {
    if (!iso) return null;
    const t = new Date(iso).getTime();
    return Number.isNaN(t) ? null : Math.round((t - Date.now()) / DAY);
};

// ── SSL state helpers ────────────────────────────────────────
// Module scope, not component scope: they are pure functions of a row, and the
// column list memoises on them.
const sslDays = (d) => {
    if (!d.ssl_enabled || !d.ssl_expires_at) return null;
    const ms = new Date(d.ssl_expires_at).getTime() - Date.now();
    return Number.isNaN(ms) ? null : Math.max(0, Math.round(ms / DAY));
};
const sslState = (d) => {
    if (d.source === 'provider') return 'n/a';
    if (!d.ssl_enabled) return 'none';
    const days = sslDays(d);
    return days != null && days < 30 ? 'expiring' : 'valid';
};
const sslPill = (d) => {
    const state = sslState(d);
    const days = sslDays(d);
    if (state === 'valid') return <Pill kind="green">{days != null ? `Valid · ${days}d` : 'Valid'}</Pill>;
    if (state === 'expiring') return <Pill kind="amber">Expires {days}d</Pill>;
    if (state === 'n/a') return <span className="dom-dash">—</span>;
    return <Pill kind="gray">No SSL</Pill>;
};
const rowStatus = (d) => (d.source === 'provider'
    ? (d.cfStatus || 'active')
    : (d.ssl_enabled ? 'active' : 'unconfigured'));

// Which columns the top-bar search scans. Module scope so the grid's memo
// chain keeps a stable identity across renders.
const SEARCH_FIELDS = ['name', 'site', 'provider', 'registrar'];

// Built-in views: the questions people actually open this page to answer. They
// are saved-view presets, not a separate filter mechanism — clicking one loads
// its config into the same grid state a personal view would, so you can tweak
// one and "Save as…" it without leaving the page.
const BUILTIN_VIEWS = [
    {
        name: 'Needs attention',
        state: {
            cols: ['name', 'ssl', 'sslDays', 'expDays', 'autoRenew', 'status'],
            sort: { key: 'sslDays', dir: 'asc' },
            filters: {
                match: 'any',
                rules: [
                    { id: 'a1', field: 'ssl', op: 'any', value: ['none', 'expiring'] },
                    { id: 'a2', field: 'status', op: 'any', value: ['unconfigured'] },
                ],
            },
            sub: ['registrar'],
            density: 'cozy',
            group: null,
        },
    },
    {
        name: 'SSL expiring',
        state: {
            cols: ['name', 'ssl', 'sslDays', 'site', 'provider'],
            sort: { key: 'sslDays', dir: 'asc' },
            filters: { match: 'all', rules: [{ id: 's1', field: 'sslDays', op: 'lt', value: 30 }] },
            sub: [], density: 'cozy', group: null,
        },
    },
    {
        name: 'Renewals ≤ 60d',
        state: {
            cols: ['name', 'expiry', 'expDays', 'autoRenew', 'registrar'],
            sort: { key: 'expDays', dir: 'asc' },
            filters: { match: 'all', rules: [{ id: 'r1', field: 'expDays', op: 'lt', value: 60 }] },
            sub: [], density: 'cozy', group: null,
        },
    },
    {
        name: 'Unlinked',
        state: {
            cols: ['name', 'provider', 'registrar', 'expiry', 'status'],
            sort: { key: 'name', dir: 'asc' },
            filters: { match: 'all', rules: [{ id: 'u1', field: 'site', op: 'any', value: ['—'] }] },
            sub: [], density: 'cozy', group: null,
        },
    },
];

const Domains = () => {
    const toast = useToast();
    const { isAdmin } = useAuth();
    const [domains, setDomains] = useState([]);
    const [apps, setApps] = useState([]);
    const [portfolio, setPortfolio] = useState([]);          // zones across connected DNS providers
    const [portfolioErrors, setPortfolioErrors] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [search, setSearch] = useState('');
    const [drawerDomain, setDrawerDomain] = useState(null);
    const [regInfo, setRegInfo] = useState(null);            // lazy registration lookup for the open drawer
    const [searchParams, setSearchParams] = useSearchParams();

    const [picked, setPicked] = useState([]);
    const [filterOpen, setFilterOpen] = useState(false);
    const [page, setPage] = useState(1);
    const [perPage, setPerPage] = useState(25);

    // Modal states
    const [showAddModal, setShowAddModal] = useState(false);
    useFocusParam('create', () => setShowAddModal(true));
    const [showSslModal, setShowSslModal] = useState(false);
    const [selectedDomain, setSelectedDomain] = useState(null);

    // Form states
    const [domainName, setDomainName] = useState('');
    const [selectedAppId, setSelectedAppId] = useState('');
    const [isPrimary, setIsPrimary] = useState(false);
    const [sslEmail, setSslEmail] = useState('');
    const [actionLoading, setActionLoading] = useState(false);

    useEffect(() => { loadData(); }, []);

    // Lazily resolve registration (expiry/registrar) for the open provider domain:
    // use the provider value if present, else fall back to a one-off RDAP lookup.
    useEffect(() => {
        if (!drawerDomain || drawerDomain.source === 'app') { setRegInfo(null); return undefined; }
        if (drawerDomain.expires_at) {
            setRegInfo({
                expires_at: drawerDomain.expires_at,
                auto_renew: drawerDomain.auto_renew,
                registrar: drawerDomain.registrar,
                source: drawerDomain.registrar ? 'cache' : 'provider',
            });
            return undefined;
        }
        let cancelled = false;
        setRegInfo({ loading: true });
        api.getDomainRegistration(drawerDomain.name)
            .then((r) => {
                if (cancelled) return;
                setRegInfo(r && r.success
                    ? { expires_at: r.expires_at, registrar: r.registrar, source: 'rdap' }
                    : { error: (r && r.error) || 'not found' });
            })
            .catch(() => { if (!cancelled) setRegInfo({ error: 'lookup failed' }); });
        return () => { cancelled = true; };
    }, [drawerDomain]);

    async function loadData() {
        try {
            setLoading(true);
            const timeout = (promise, ms) => Promise.race([
                promise,
                new Promise((_, reject) => setTimeout(() => reject(new Error('Request timeout')), ms)),
            ]);
            const [domainsData, appsData, portfolioData] = await Promise.all([
                timeout(api.getDomains(), 10000).catch(() => ({ domains: [] })),
                timeout(api.getApps(), 10000).catch(() => ({ apps: [] })),
                timeout(api.getDnsPortfolio(), 15000).catch(() => ({ domains: [], errors: [] })),
            ]);
            setDomains(domainsData.domains || []);
            setApps(appsData.apps || []);
            setPortfolio(portfolioData.domains || []);
            setPortfolioErrors(portfolioData.errors || []);
        } catch (err) {
            setError('Failed to load data');
            console.error(err);
        } finally {
            setLoading(false);
        }
    }

    async function handleAddDomain(e) {
        e.preventDefault();
        if (!domainName || !selectedAppId) return;
        try {
            setActionLoading(true);
            await api.createDomain({
                name: domainName,
                application_id: parseInt(selectedAppId, 10),
                is_primary: isPrimary,
            });
            setShowAddModal(false);
            setDomainName('');
            setSelectedAppId('');
            setIsPrimary(false);
            loadData();
        } catch (err) {
            setError(err.message);
        } finally {
            setActionLoading(false);
        }
    }

    async function handleDeleteDomain(domain) {
        if (!confirm(`Are you sure you want to delete ${domain.name}?`)) return;
        try {
            await api.deleteDomain(domain.id);
            loadData();
        } catch (err) {
            setError(err.message);
        }
    }

    async function handleEnableSsl(e) {
        e.preventDefault();
        if (!selectedDomain || !sslEmail) return;
        try {
            setActionLoading(true);
            await api.enableSsl(selectedDomain.id, sslEmail);
            setShowSslModal(false);
            setSslEmail('');
            setSelectedDomain(null);
            loadData();
        } catch (err) {
            setError(err.message);
        } finally {
            setActionLoading(false);
        }
    }

    async function handleDisableSsl(domain) {
        if (!confirm(`Disable SSL for ${domain.name}?`)) return;
        try {
            await api.disableSsl(domain.id);
            loadData();
        } catch (err) {
            setError(err.message);
        }
    }

    async function handleRenewSsl(domain) {
        try {
            setActionLoading(true);
            await api.renewDomainSsl(domain.id);
            loadData();
        } catch (err) {
            setError(err.message);
        } finally {
            setActionLoading(false);
        }
    }

    async function handleVerifyDomain(domain) {
        try {
            const result = await api.verifyDomain(domain.id);
            if (!result.verified) {
                toast.error(`Domain verification failed: ${result.error}`);
            } else if (result.warning) {
                // The name resolves, but something about it will break
                // issuance later (a stray AAAA record, today). A green
                // "verified" toast here is how that stayed invisible.
                toast.warning(result.warning, { duration: 15000 });
            } else {
                toast.success(`Domain verified! IP: ${result.ip_address}`);
            }
        } catch (err) {
            setError(err.message);
        }
    }

    const appName = useCallback(
        (id) => apps.find((a) => a.id === id)?.name || 'Unknown',
        [apps],
    );

    // One unified list: ServerKit's app-linked domains + every zone in a connected
    // DNS provider. A domain that is both keeps its app row and gains the provider
    // badge, expiry, and quick actions; provider-only zones become their own rows.
    const rows = useMemo(() => {
        const providerByDomain = new Map(portfolio.map((z) => [norm(z.domain), z]));
        const appNames = new Set(domains.map((d) => norm(d.name)));
        return [
            ...domains.map((d) => {
                const p = providerByDomain.get(norm(d.name));
                return {
                    ...d,
                    key: `app:${d.id}`,
                    source: 'app',
                    provider: p?.provider || null,
                    config_id: p?.config_id ?? null,
                    config_name: p?.config_name ?? null,
                    provider_zone_id: p?.provider_zone_id ?? null,
                    adopted: p?.adopted ?? false,
                    zone_id: p?.zone_id ?? null,
                    expires_at: p?.expires_at ?? null,
                    auto_renew: p?.auto_renew ?? null,
                    registrar: p?.registrar ?? null,
                };
            }),
            ...portfolio
                .filter((z) => !appNames.has(norm(z.domain)))
                .map((z) => ({
                    key: `prov:${z.provider}:${z.domain}`,
                    source: 'provider',
                    name: z.domain,
                    provider: z.provider,
                    config_id: z.config_id,
                    config_name: z.config_name,
                    provider_zone_id: z.provider_zone_id,
                    adopted: z.adopted,
                    zone_id: z.zone_id,
                    cfStatus: z.status,
                    expires_at: z.expires_at,
                    auto_renew: z.auto_renew,
                    registrar: z.registrar,
                    application_id: null,
                    ssl_enabled: false,
                    is_primary: false,
                })),
        ].sort((a, b) => a.name.localeCompare(b.name));
    }, [domains, portfolio]);

    // ── columns ───────────────────────────────────────────────
    // `type` picks the operator set and the filter UI in the header menu;
    // `width` is a CSS grid track. Only fields the API actually returns are
    // listed — there is no DNSSEC or record-count column because nothing in
    // /domains or /dns/portfolio carries them.
    const columns = useMemo(() => [
        {
            key: 'name',
            header: 'Domain',
            type: 'text',
            width: 'minmax(250px,1.8fr)',
            locked: true,
            value: (d) => d.name,
            render: (d) => (
                <>
                    {d.name}
                    {d.is_primary && <span className="dom-primary">Primary</span>}
                    {d.source === 'provider' && d.adopted && <span className="dom-managed">Managed</span>}
                </>
            ),
        },
        {
            key: 'site',
            header: 'Linked site',
            type: 'enum',
            width: 'minmax(140px,1fr)',
            value: (d) => (d.application_id ? appName(d.application_id) : '—'),
            render: (d) => (d.application_id
                ? <span className="sk-tag">{appName(d.application_id)}</span>
                : <span className="dom-dash">unlinked</span>),
        },
        {
            key: 'provider',
            header: 'DNS provider',
            type: 'enum',
            width: '150px',
            defaultVisible: false,
            value: (d) => d.config_name || d.provider || '—',
        },
        {
            key: 'registrar',
            header: 'Registrar',
            type: 'enum',
            width: '150px',
            defaultVisible: false,
            value: (d) => d.registrar || '—',
        },
        {
            key: 'ssl',
            header: 'SSL',
            type: 'enum',
            width: '160px',
            enumOrder: ['valid', 'expiring', 'none', 'n/a'],
            value: sslState,
            render: sslPill,
        },
        {
            key: 'sslDays',
            header: 'SSL expiry',
            type: 'num',
            width: '155px',
            unit: 'd',
            defaultVisible: false,
            quick: [
                { op: 'lt', value: 15, label: 'under 15' },
                { op: 'lt', value: 30, label: 'under 30' },
            ],
            // -1 keeps "no certificate" sorting as the most urgent thing, which
            // is what someone sorting by SSL expiry is looking for.
            value: (d) => (sslDays(d) == null ? -1 : sslDays(d)),
            render: (d) => {
                const days = sslDays(d);
                if (days == null) return <span className="dom-dash">—</span>;
                const pct = Math.max(4, Math.min(100, (days / 90) * 100));
                const tone = days < 15 ? 'var(--red)' : days < 40 ? 'var(--amber)' : 'var(--green)';
                return (
                    <div className="dom-meter">
                        <span style={{ color: tone }}>{days}d</span>
                        <span className="dom-meter__bar">
                            <i style={{ width: `${pct}%`, background: tone }} />
                        </span>
                    </div>
                );
            },
        },
        {
            key: 'expiry',
            header: 'Registration',
            type: 'date',
            width: '165px',
            value: (d) => d.expires_at || null,
            render: (d) => {
                const exp = formatExpiry(d.expires_at);
                if (!exp) return <span className="dom-dash">—</span>;
                return (
                    <div>
                        <div className={`dom-expiry dom-expiry--${exp.tone}`}>{exp.absolute}</div>
                        <div className="dom-expiry__rel">{exp.relative}</div>
                    </div>
                );
            },
        },
        {
            key: 'expDays',
            header: 'Renews in',
            type: 'num',
            width: '135px',
            unit: 'd',
            align: 'right',
            defaultVisible: false,
            quick: [
                { op: 'lt', value: 30, label: 'under 30' },
                { op: 'lt', value: 60, label: 'under 60' },
            ],
            value: (d) => daysUntil(d.expires_at),
            render: (d) => {
                const days = daysUntil(d.expires_at);
                if (days == null) return <span className="dom-dash">—</span>;
                return <span style={days < 40 ? { color: 'var(--amber)' } : undefined}>{days}d</span>;
            },
        },
        {
            key: 'autoRenew',
            header: 'Auto-renew',
            type: 'bool',
            width: '142px',
            value: (d) => d.auto_renew,
            render: (d) => (d.auto_renew == null
                ? <span className="dom-dash">—</span>
                : d.auto_renew ? <Pill kind="green">on</Pill> : <Pill kind="gray">off</Pill>),
        },
        {
            key: 'status',
            header: 'Status',
            type: 'enum',
            width: '135px',
            value: rowStatus,
            render: (d) => {
                const state = rowStatus(d);
                return <Pill kind={state === 'active' ? 'green' : 'amber'}>{state}</Pill>;
            },
        },
    ], [appName]);

    const grid = useGridConfig({
        page: 'domains',
        columns,
        builtinViews: BUILTIN_VIEWS,
        initial: {
            cols: ['name', 'site', 'ssl', 'expiry', 'autoRenew', 'status'],
            sort: { key: 'name', dir: 'asc' },
            sub: ['registrar'],
        },
    });
    const { cfg } = grid;

    const view = useGridRows({
        rows,
        columns,
        cfg,
        search,
        searchFields: SEARCH_FIELDS,
        page,
        perPage,
    });

    // Any change to what is being shown resets to page 1 — otherwise a filter
    // that shrinks the set below the current page leaves you on a blank page.
    const filterSig = JSON.stringify(cfg.filters);
    useEffect(() => { setPage(1); }, [filterSig, search, perPage, cfg.group]);

    // ⌘F / Ctrl+F opens the filter drawer; "/" focuses the top-bar search.
    useEffect(() => {
        const onKey = (e) => {
            if (e.key === 'f' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                setFilterOpen(true);
            }
            if (e.key === '/' && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName)) {
                e.preventDefault();
                document.querySelector('.sk-topbar .sk-searchfield__input')?.focus();
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, []);

    // Deep-link: /domains?open=<domain> opens that domain's drawer once data has
    // loaded — keeps links sensible now that this is the single DNS surface.
    useEffect(() => {
        const want = searchParams.get('open');
        if (!want || loading || drawerDomain) return;
        const row = rows.find((d) => norm(d.name) === norm(want));
        if (row) {
            setDrawerDomain(row);
            const next = new URLSearchParams(searchParams);
            next.delete('open');
            setSearchParams(next, { replace: true });
        }
    }, [loading, searchParams]); // eslint-disable-line react-hooks/exhaustive-deps

    const pickedRows = useMemo(
        () => view.filtered.filter((d) => picked.includes(d.key)),
        [view.filtered, picked],
    );

    const toggleRow = useCallback((key, on) => {
        setPicked((prev) => (on ? [...new Set([...prev, key])] : prev.filter((k) => k !== key)));
    }, []);
    const toggleAll = useCallback((on, keys) => {
        setPicked((prev) => (on ? [...new Set([...prev, ...keys])] : prev.filter((k) => !keys.includes(k))));
    }, []);

    const createView = (name, fromCurrent) => {
        if (!fromCurrent) grid.setCfg(grid.base);
        grid.views.saveView(name)
            .then(() => toast.success(`View “${name}” saved`))
            .catch(() => toast.error('Could not save the view'));
    };

    // ── top bar ──────────────────────────────────────────────
    // Fixed shape on every page: page actions, then search, then the filter
    // icon, then the overflow "⋮". The search box must not move when a page
    // adds or removes an action, so it sits AFTER the actions and before the
    // two fixed-width icon buttons.
    useTopbarActions(() => (
        <>
            <Button size="sm" onClick={() => setShowAddModal(true)}>
                <Plus size={15} /> Add domain
            </Button>
            <Button variant="outline" size="sm" onClick={loadData}>
                <RefreshCw size={15} /> Check DNS
            </Button>
            <SearchField value={search} onSearch={setSearch} placeholder="Search domains…" />
            <GridFilterButton count={cfg.filters.rules.length} onClick={() => setFilterOpen(true)} />
            <GridToolsMenu
                cfg={cfg}
                columns={columns}
                rows={view.filtered}
                selectedRows={pickedRows}
                viewName={grid.views.activeView?.name || 'domains'}
                noun="domains"
                onRefresh={loadData}
                onReset={grid.resetToView}
                onCopyLink={grid.copyLink}
                onDensity={grid.setDensity}
                onExported={(n, fields, format) => toast.success(`${n} rows · ${fields} fields · ${format.toUpperCase()}`)}
            />
        </>
    ), [search, cfg, columns, view.filtered, pickedRows, grid.views.activeView]);

    return (
        <div className="sk-tabgroup__inner domains-page">
            <RegistrarPortfolio />

            {error && (
                <div className="error-banner">
                    {error}
                    <button type="button" className="error-banner__close" onClick={() => setError('')} aria-label="Dismiss error">×</button>
                </div>
            )}

            {loading ? (
                <EmptyState loading loadingVariant="table" title="Loading domains..." />
            ) : rows.length === 0 ? (
                <EmptyState
                    icon={Globe}
                    title="No domains yet"
                    description="Attach a domain to an application, or connect a DNS provider to see its zones here."
                    action={<Button onClick={() => setShowAddModal(true)}><Plus size={16} /> Add Domain</Button>}
                />
            ) : (
                <div className="domains-body">
                    <GridViewPicker
                        views={grid.views}
                        label="domains"
                        onCreate={createView}
                    />

                    <GridChips
                        cfg={cfg}
                        columns={columns}
                        onRemove={grid.removeRule}
                        onClear={grid.clearRules}
                        onMatchChange={grid.setMatch}
                    />

                    <GridBulkBar count={picked.length} noun="domain" onClear={() => setPicked([])}>
                        <button type="button" onClick={loadData}>
                            <RefreshCw size={13} /> Check DNS
                        </button>
                        <button
                            type="button"
                            onClick={() => {
                                const n = exportRows(
                                    pickedRows,
                                    cfg.cols.map((k) => columns.find((c) => c.key === k)).filter(Boolean),
                                    'csv',
                                    'domains',
                                );
                                toast.success(`${n} rows · CSV`);
                            }}
                        >
                            <ExternalLink size={13} /> Export CSV
                        </button>
                    </GridBulkBar>

                    {portfolioErrors.length > 0 && (
                        <div className="dom-portfolio-note">
                            <AlertTriangle size={14} />
                            <span>
                                {portfolioErrors.length === 1
                                    ? `${portfolioErrors[0].config_name}: ${portfolioErrors[0].error}`
                                    : `${portfolioErrors.length} DNS connections couldn't list their zones`}
                                {' — '}a Cloudflare token needs <strong>Zone:Read</strong> on all zones to list the whole account.
                            </span>
                        </div>
                    )}

                    <DataGrid
                        columns={columns}
                        groups={view.groups}
                        allRows={rows}
                        cfg={cfg}
                        grid={grid}
                        keyField="key"
                        selectable
                        selectedKeys={picked}
                        onToggleRow={toggleRow}
                        onToggleAll={toggleAll}
                        onRowClick={setDrawerDomain}
                        rowLeading={(d) => (d.provider
                            ? <ProviderBrandIcon provider={d.provider} size={15} />
                            : <Globe size={15} />)}
                        rowActions={() => <ChevronRight size={15} className="dom-chev" />}
                        empty={(
                            <EmptyState
                                icon={Globe}
                                title={search ? `No domains match “${search.trim()}”.` : 'No domains match this view.'}
                                action={(
                                    <Button variant="outline" onClick={() => { setSearch(''); grid.clearRules(); }}>
                                        Clear filters
                                    </Button>
                                )}
                            />
                        )}
                        footer={(
                            <GridFooter
                                from={view.from}
                                to={view.to}
                                total={view.total}
                                noun="domains"
                                cfg={cfg}
                                columns={columns}
                                page={view.page}
                                pageCount={view.pageCount}
                                perPage={perPage}
                                onPage={setPage}
                                onPerPage={setPerPage}
                            />
                        )}
                    />
                </div>
            )}

            <GridFilterDrawer
                open={filterOpen}
                onOpenChange={setFilterOpen}
                columns={columns}
                rows={rows}
                cfg={cfg}
                grid={grid}
                noun="domains"
            />

            {/* ── Detail drawer ──────────────────────────────── */}
            <Drawer
                open={!!drawerDomain}
                onOpenChange={(open) => { if (!open) setDrawerDomain(null); }}
                icon={drawerDomain?.provider ? <ProviderBrandIcon provider={drawerDomain.provider} size={18} /> : <Globe size={18} />}
                iconColor="var(--accent-bright)"
                title={drawerDomain?.name || ''}
                subtitle={drawerDomain
                    ? (drawerDomain.source === 'app'
                        ? `${drawerDomain.application_id ? appName(drawerDomain.application_id) : 'unlinked'} · ${sslState(drawerDomain)}`
                        : `${drawerDomain.config_name || drawerDomain.provider || 'DNS'} zone${drawerDomain.cfStatus ? ` · ${drawerDomain.cfStatus}` : ''}`)
                    : ''}
                width={1100}
                headerExtra={drawerDomain && (
                    <div className="dom-drawer__headeractions">
                        <Button variant="outline" size="sm" asChild>
                            <a href={`${drawerDomain.ssl_enabled ? 'https' : 'http'}://${drawerDomain.name}`} target="_blank" rel="noopener noreferrer">
                                <ExternalLink size={14} /> Visit
                            </a>
                        </Button>
                        {drawerDomain.source === 'app' && (
                            <>
                                <Button variant="outline" size="sm" onClick={() => handleVerifyDomain(drawerDomain)}>
                                    <Search size={14} /> Verify DNS
                                </Button>
                                {drawerDomain.ssl_enabled ? (
                                    <>
                                        <Button variant="outline" size="sm" disabled={actionLoading} onClick={() => handleRenewSsl(drawerDomain)}>
                                            <RefreshCw size={14} /> Renew SSL
                                        </Button>
                                        <Button variant="outline" size="sm" onClick={() => handleDisableSsl(drawerDomain)}>
                                            <Lock size={14} /> Disable SSL
                                        </Button>
                                    </>
                                ) : (
                                    <Button size="sm" onClick={() => { setSelectedDomain(drawerDomain); setShowSslModal(true); setDrawerDomain(null); }}>
                                        <Lock size={14} /> Enable SSL
                                    </Button>
                                )}
                            </>
                        )}
                    </div>
                )}
            >
                {drawerDomain && (
                    <div className="dom-drawer">
                        <div className="dom-specs">
                            {drawerDomain.source === 'app' ? (
                                <>
                                    <div className="sk-spec-card">
                                        <div className="sk-spec-card__label">SSL certificate</div>
                                        <div style={{ marginTop: 8 }}>{sslPill(drawerDomain)}</div>
                                        <div className="sk-spec-card__sub">
                                            {drawerDomain.ssl_enabled
                                                ? (drawerDomain.ssl_expires_at ? `Expires ${new Date(drawerDomain.ssl_expires_at).toLocaleDateString()}` : "Let's Encrypt")
                                                : 'Not issued'}
                                        </div>
                                    </div>
                                    <div className="sk-spec-card">
                                        <div className="sk-spec-card__label">Linked site</div>
                                        <div className="sk-spec-card__value">{drawerDomain.application_id ? appName(drawerDomain.application_id) : 'Unlinked'}</div>
                                        <div className="sk-spec-card__sub">{drawerDomain.is_primary ? 'Primary domain' : 'Alias'}</div>
                                    </div>
                                    <div className="sk-spec-card">
                                        <div className="sk-spec-card__label">Status</div>
                                        <div style={{ marginTop: 8 }}>
                                            <Pill kind={drawerDomain.ssl_enabled ? 'green' : 'amber'}>{drawerDomain.ssl_enabled ? 'active' : 'unconfigured'}</Pill>
                                        </div>
                                        <div className="sk-spec-card__sub">Auto-renew {drawerDomain.ssl_auto_renew ? 'on' : 'off'}</div>
                                    </div>
                                </>
                            ) : (
                                <>
                                    <div className="sk-spec-card">
                                        <div className="sk-spec-card__label">DNS provider</div>
                                        <div className="sk-spec-card__value">{drawerDomain.config_name || drawerDomain.provider}</div>
                                        <div className="sk-spec-card__sub">{drawerDomain.adopted ? 'Managed in ServerKit' : 'Read-only'}</div>
                                    </div>
                                    <div className="sk-spec-card">
                                        <div className="sk-spec-card__label">Zone status</div>
                                        <div style={{ marginTop: 8 }}>
                                            <Pill kind={drawerDomain.cfStatus === 'active' ? 'green' : 'amber'}>{drawerDomain.cfStatus || 'active'}</Pill>
                                        </div>
                                        <div className="sk-spec-card__sub">{drawerDomain.provider}</div>
                                    </div>
                                    <div className="sk-spec-card">
                                        <div className="sk-spec-card__label">Registration</div>
                                        <div className="sk-spec-card__value">
                                            {regInfo?.loading ? 'Looking up…' : (formatExpiry(regInfo?.expires_at)?.relative || '—')}
                                        </div>
                                        <div className="sk-spec-card__sub">
                                            {regInfo?.loading ? 'WHOIS / RDAP lookup' : (() => {
                                                const exp = formatExpiry(regInfo?.expires_at);
                                                if (!exp) return regInfo?.error ? 'Lookup unavailable' : '—';
                                                return [exp.absolute, regInfo?.registrar].filter(Boolean).join(' · ');
                                            })()}
                                        </div>
                                    </div>
                                </>
                            )}
                        </div>

                        <div className="dom-drawer__section">
                            <DomainDnsPanel domain={drawerDomain} isAdmin={isAdmin} />
                        </div>

                        {drawerDomain.source === 'app' && (
                            <div className="dom-drawer__danger">
                                <Button variant="outline" size="sm" className="dom-delete-btn" onClick={() => { handleDeleteDomain(drawerDomain); setDrawerDomain(null); }}>
                                    <Trash2 size={14} /> Delete domain
                                </Button>
                            </div>
                        )}

                        {/* Extension slot: panels contributed to the domain drawer */}
                        <PluginSlot name="domain.drawer.panel" context={{ domain: drawerDomain }} />
                    </div>
                )}
            </Drawer>

            {/* ── Add Domain Modal ───────────────────────────── */}
            <Modal open={showAddModal} onClose={() => setShowAddModal(false)} title="Add Domain">
                <form onSubmit={handleAddDomain}>
                    <div className="form-group">
                        <Label>Domain Name</Label>
                        <Input type="text" placeholder="example.com" value={domainName} onChange={e => setDomainName(e.target.value)} required />
                    </div>
                    <div className="form-group">
                        <Label>Application</Label>
                        <Select value={selectedAppId} onValueChange={setSelectedAppId} required>
                            <SelectTrigger><SelectValue placeholder="Select an application" /></SelectTrigger>
                            <SelectContent>
                                {apps.map(app => (
                                    <SelectItem key={app.id} value={String(app.id)}>{app.name}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="form-group">
                        <label className="checkbox-label">
                            <Checkbox checked={isPrimary} onCheckedChange={setIsPrimary} />
                            Set as primary domain
                        </label>
                    </div>
                    <div className="modal-actions">
                        <Button type="button" variant="outline" onClick={() => setShowAddModal(false)}>Cancel</Button>
                        <Button type="submit" disabled={actionLoading}>{actionLoading ? 'Adding...' : 'Add Domain'}</Button>
                    </div>
                </form>
            </Modal>

            {/* ── Enable SSL Modal ───────────────────────────── */}
            <Modal open={showSslModal && Boolean(selectedDomain)} onClose={() => setShowSslModal(false)} title="Enable SSL Certificate">
                {selectedDomain && (
                    <form onSubmit={handleEnableSsl}>
                        <div className="ssl-info-box">
                            <ShieldCheck size={32} />
                            <div>
                                <h4>Free SSL from Let&apos;s Encrypt</h4>
                                <p>A free SSL certificate will be obtained for <strong>{selectedDomain.name}</strong></p>
                            </div>
                        </div>
                        <div className="form-group">
                            <Label>Email Address</Label>
                            <Input type="email" placeholder="admin@example.com" value={sslEmail} onChange={e => setSslEmail(e.target.value)} required />
                            <p className="hint">Required for certificate expiration notifications</p>
                        </div>
                        <div className="modal-actions">
                            <Button type="button" variant="outline" onClick={() => setShowSslModal(false)}>Cancel</Button>
                            <Button type="submit" disabled={actionLoading}>{actionLoading ? 'Obtaining Certificate...' : 'Enable SSL'}</Button>
                        </div>
                    </form>
                )}
            </Modal>
        </div>
    );
};

export default Domains;
