import { useState, useEffect } from 'react';
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
import { SegControl, SearchField, Pill, Drawer, DataTable, SortMenu, ColumnsMenu, DataTableFooter } from '@/components/ds';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import RegistrarPortfolio from '../components/domains/RegistrarPortfolio';
import { ProviderBrandIcon } from '../components/icons/ProviderBrands';
import DomainDnsPanel from '../components/domains/DomainDnsPanel';
import PluginSlot from '../components/PluginSlot';
import { formatExpiry } from '../utils/expiry';

const Domains = () => {
    const toast = useToast();
    const { isAdmin } = useAuth();
    const [domains, setDomains] = useState([]);
    const [apps, setApps] = useState([]);
    const [portfolio, setPortfolio] = useState([]);          // zones across connected DNS providers
    const [portfolioErrors, setPortfolioErrors] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [filter, setFilter] = useState('all');
    const [search, setSearch] = useState('');

    // Table sort + column visibility (persisted, mirrored by the toolbar menus)
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-domains-sort' });
    const { hiddenKeys, toggleColumn, showAllColumns } = useColumnVisibility({
        storageKey: 'serverkit-table-domains-cols',
    });
    const [drawerDomain, setDrawerDomain] = useState(null);
    const [regInfo, setRegInfo] = useState(null);            // lazy registration lookup for the open drawer
    const [searchParams, setSearchParams] = useSearchParams();

    // Modal states
    const [showAddModal, setShowAddModal] = useState(false);
    const [showSslModal, setShowSslModal] = useState(false);
    const [selectedDomain, setSelectedDomain] = useState(null);

    // Form states
    const [domainName, setDomainName] = useState('');
    const [selectedAppId, setSelectedAppId] = useState('');
    const [isPrimary, setIsPrimary] = useState(false);
    const [sslEmail, setSslEmail] = useState('');
    const [actionLoading, setActionLoading] = useState(false);

    useEffect(() => {
        loadData();
    }, []);

    // Lazily resolve registration (expiry/registrar) for the open provider domain:
    // use the provider value if present, else fall back to a one-off RDAP lookup.
    useEffect(() => {
        if (!drawerDomain || drawerDomain.source === 'app') { setRegInfo(null); return; }
        if (drawerDomain.expires_at) {
            setRegInfo({
                expires_at: drawerDomain.expires_at,
                auto_renew: drawerDomain.auto_renew,
                registrar: drawerDomain.registrar,
                source: drawerDomain.registrar ? 'cache' : 'provider',
            });
            return;
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
                application_id: parseInt(selectedAppId),
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
            if (result.verified) {
                toast.success(`Domain verified! IP: ${result.ip_address}`);
            } else {
                toast.error(`Domain verification failed: ${result.error}`);
            }
        } catch (err) {
            setError(err.message);
        }
    }

    function getAppName(appId) {
        const app = apps.find(a => a.id === appId);
        return app ? app.name : 'Unknown';
    }

    // ── SSL state helpers ────────────────────────────────────
    function sslDays(d) {
        if (!d.ssl_enabled || !d.ssl_expires_at) return null;
        const ms = new Date(d.ssl_expires_at).getTime() - Date.now();
        if (Number.isNaN(ms)) return null;
        return Math.max(0, Math.round(ms / 86400000));
    }
    function sslState(d) {
        if (!d.ssl_enabled) return 'none';
        const days = sslDays(d);
        return days != null && days < 30 ? 'expiring' : 'valid';
    }
    function sslPill(d) {
        const st = sslState(d);
        const days = sslDays(d);
        if (st === 'valid') return <Pill kind="green">{days != null ? `Valid · ${days}d` : 'Valid'}</Pill>;
        if (st === 'expiring') return <Pill kind="amber">Expires {days}d</Pill>;
        return <Pill kind="gray">No SSL</Pill>;
    }

    // One unified list: ServerKit's app-linked domains + every zone in a connected
    // DNS provider. A domain that is both keeps its app row and gains the provider
    // badge, expiry, and quick actions; provider-only zones become their own rows.
    const norm = (s) => (s || '').toLowerCase().replace(/\.$/, '');
    const providerByDomain = new Map(portfolio.map((z) => [norm(z.domain), z]));
    const appNames = new Set(domains.map((d) => norm(d.name)));
    const mergedRows = [
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

    // Search narrows the set the filter counts are taken from, so each number
    // always describes what a click on that segment would actually show.
    const query = search.trim().toLowerCase();
    const searched = query
        ? mergedRows.filter(d => (
            norm(d.name).includes(query)
            || (d.registrar || '').toLowerCase().includes(query)
            || (d.config_name || d.provider || '').toLowerCase().includes(query)
            || (d.application_id ? getAppName(d.application_id) : '').toLowerCase().includes(query)
        ))
        : mergedRows;

    // The segmented control carries the numbers the KPI strip used to: an
    // "Expiring SSL (2)" segment says the same thing as a tile, and is the
    // control you'd click next anyway.
    const isExpiring = (d) => sslState(d) === 'expiring';
    const needsAttention = (d) => d.source !== 'provider' && !d.ssl_enabled;
    const filterOptions = [
        { value: 'all', label: 'All', count: searched.length },
        { value: 'ssl', label: 'Expiring SSL', count: searched.filter(isExpiring).length },
        { value: 'issues', label: 'Attention', count: searched.filter(needsAttention).length },
    ];

    const shown = searched.filter(d => (
        filter === 'ssl' ? isExpiring(d)
            : filter === 'issues' ? needsAttention(d) : true
    ));

    // Deep-link: /domains?open=<domain> opens that domain's drawer once data has
    // loaded — keeps links sensible now that this is the single DNS surface.
    useEffect(() => {
        const want = searchParams.get('open');
        if (!want || loading || drawerDomain) return;
        const row = mergedRows.find((d) => norm(d.name) === norm(want));
        if (row) {
            setDrawerDomain(row);
            const next = new URLSearchParams(searchParams);
            next.delete('open');
            setSearchParams(next, { replace: true });
        }
    }, [loading, searchParams]); // eslint-disable-line react-hooks/exhaustive-deps

    const domainColumns = [
        {
            key: 'name',
            header: 'Domain',
            sortable: true,
            hideable: false,
            sortValue: (d) => norm(d.name),
            render: (d) => (
                <div className="sk-cell-name">
                    <span className="dom-fav">
                        {d.provider
                            ? <ProviderBrandIcon provider={d.provider} size={15} />
                            : <Globe size={15} />}
                    </span>
                    <span>
                        {d.name}
                        {d.is_primary && <span className="dom-primary">Primary</span>}
                        {d.source === 'provider' && d.adopted && <span className="dom-managed">Managed</span>}
                    </span>
                </div>
            ),
        },
        {
            key: 'site',
            header: 'Linked site',
            sortable: true,
            sortValue: (d) => (d.application_id ? getAppName(d.application_id) : null),
            render: (d) => (
                d.application_id
                    ? <span className="sk-tag">{getAppName(d.application_id)}</span>
                    : <span className="dom-dash">—</span>
            ),
        },
        {
            key: 'expiry',
            header: 'Expires',
            sortable: true,
            sortValue: (d) => {
                if (!d.expires_at) return null;
                const t = new Date(d.expires_at).getTime();
                return Number.isNaN(t) ? null : t;
            },
            render: (d) => {
                const exp = formatExpiry(d.expires_at);
                if (!exp) return <span className="dom-dash">—</span>;
                return (
                    <span className={`dom-expiry dom-expiry--${exp.tone}`} title={exp.relative}>
                        {exp.absolute}
                    </span>
                );
            },
        },
        {
            key: 'ssl',
            header: 'SSL',
            sortable: true,
            sortValue: (d) => sslState(d),
            render: (d) => d.source === 'provider' ? <span className="dom-dash">—</span> : sslPill(d),
        },
        {
            key: 'autoRenew',
            header: 'Auto-renew',
            sortable: true,
            sortValue: (d) => (d.auto_renew == null ? null : d.auto_renew ? 1 : 0),
            render: (d) => (
                d.auto_renew == null
                    ? <span className="dom-dash">—</span>
                    : d.auto_renew ? <Pill kind="green">on</Pill> : <Pill kind="gray">off</Pill>
            ),
        },
        {
            key: 'chevron',
            header: '',
            width: 30,
            hideable: false,
            render: () => <ChevronRight size={16} className="dom-chev" />,
        },
    ];

    useTopbarActions(() =>
        <>
            <Button variant="outline" size="sm" onClick={loadData}>
                <RefreshCw size={15} /> Check DNS
            </Button>
            <Button size="sm" onClick={() => setShowAddModal(true)}>
                <Plus size={15} /> Add domain
            </Button>
            <SearchField
                value={search}
                onSearch={setSearch}
                placeholder="Search domains…"
            />
        </>,
        [search],
    );

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
            ) : mergedRows.length === 0 ? (
                <EmptyState
                    icon={Globe}
                    title="No domains yet"
                    description="Attach a domain to an application, or connect a DNS provider to see its zones here."
                    action={<Button onClick={() => setShowAddModal(true)}><Plus size={16} /> Add Domain</Button>}
                />
            ) : (
                <div className="domains-body">
                    {/* No KPI strip: every number it carried is already on the
                        segment you would click to act on it. */}
                    <div className="dom-listhead">
                        <SegControl
                            value={filter}
                            onChange={setFilter}
                            options={filterOptions}
                        />
                        <div className="dom-listhead__tools">
                            <SortMenu columns={domainColumns} sorts={sorts} onChange={setSorts} />
                            <ColumnsMenu
                                columns={domainColumns}
                                hiddenKeys={hiddenKeys}
                                onToggle={toggleColumn}
                                onShowAll={showAllColumns}
                            />
                        </div>
                    </div>

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

                    {shown.length === 0 ? (
                        <div className="dom-empty">
                            {query ? `No domains match “${search.trim()}”.` : 'No domains match this filter.'}
                        </div>
                    ) : (
                        <div className="dom-card">
                            <DataTable
                                tableClassName="sk-dtable"
                                data={shown}
                                keyField="key"
                                columns={domainColumns}
                                sorts={sorts}
                                onSortsChange={setSorts}
                                hiddenKeys={hiddenKeys}
                                onRowClick={setDrawerDomain}
                                footer={(
                                    <DataTableFooter
                                        shown={shown.length}
                                        total={mergedRows.length}
                                        noun="domain"
                                    />
                                )}
                            />
                        </div>
                    )}
                </div>
            )}

            {/* ── Detail drawer ──────────────────────────────── */}
            <Drawer
                open={!!drawerDomain}
                onOpenChange={(open) => { if (!open) setDrawerDomain(null); }}
                icon={drawerDomain?.provider ? <ProviderBrandIcon provider={drawerDomain.provider} size={18} /> : <Globe size={18} />}
                iconColor="var(--accent-bright)"
                title={drawerDomain?.name || ''}
                subtitle={drawerDomain
                    ? (drawerDomain.source === 'app'
                        ? `${drawerDomain.application_id ? getAppName(drawerDomain.application_id) : 'unlinked'} · ${sslState(drawerDomain)}`
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
                                        <div className="sk-spec-card__value">{drawerDomain.application_id ? getAppName(drawerDomain.application_id) : 'Unlinked'}</div>
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
