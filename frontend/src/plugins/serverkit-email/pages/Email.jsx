// Email Server — management page for the serverkit-email extension.
//
// NOTE: This file was reconstructed after a data-loss corruption. The original
// was ~63KB; this is a coherent, functional, on-style rebuild — not a
// byte-for-byte restore. It is wired to the real ApiService email methods
// (see frontend/src/services/api/system.js, the `/email/*` endpoints) and
// covers the same surface area: server/service status, mail domains with
// SPF/DKIM/DMARC/PTR presence pills + DNS verify/deploy, accounts, aliases,
// outbound relay (smarthost), SpamAssassin, webmail, and the mail queue.
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
    RefreshCw, Plus, Trash2, ShieldCheck, Server, Globe, Users,
    Send, Filter, Inbox, ExternalLink, CheckCircle2, XCircle, HelpCircle, Search,
} from 'lucide-react';
import api from '../services/email';
import {
    Pill, MetricCard, KpiBand, DataTable, DataTableFooter, ListToolbar,
    SearchField, PageLayout, Button, Input, EmptyState, useToast, useConfirm,
    useTabParam, useTableSort, useColumnVisibility, useTranslation,
    useTableChrome, GridViewPicker, GridChips, GridFilterButton,
    GridToolsMenu, GridFilterDrawer,
} from 'serverkit-sdk';

const VALID_TABS = ['overview', 'domains', 'accounts', 'relay', 'spam', 'webmail', 'queue'];

// A sort-only preset still has to say so: `apply` clears the live rules from
// whatever was selected before, and an absent `columnFilters` would leave the
// previous view's filters silently in place.
const NO_RULES = { match: 'all', rules: [] };

// DNS record checks surfaced as presence pills. `state` is one of
// 'ok' | 'missing' | 'unknown' and maps to a DS Pill colour + dot.
const DNS_RECORDS = [
    { key: 'spf', label: 'SPF' },
    { key: 'dkim', label: 'DKIM' },
    { key: 'dmarc', label: 'DMARC' },
    { key: 'ptr', label: 'PTR' },
    { key: 'mx', label: 'MX' },
];

function dnsPillKind(state) {
    if (state === 'ok') return 'green';
    if (state === 'missing') return 'red';
    return 'gray';
}

// Derive a per-record status map from a domain record and an optional live
// verify result. Falls back to "does the stored record string exist" when we
// have not run a live DNS check yet.
function deriveDnsStatus(domain, verify) {
    const out = {};
    for (const { key } of DNS_RECORDS) {
        if (verify && verify[key]) {
            out[key] = verify[key].valid || verify[key].present ? 'ok' : 'missing';
        } else if (key === 'spf') {
            out[key] = domain?.spf_record ? 'ok' : 'unknown';
        } else if (key === 'dkim') {
            out[key] = domain?.dkim_public_key ? 'ok' : 'unknown';
        } else if (key === 'dmarc') {
            out[key] = domain?.dmarc_record ? 'ok' : 'unknown';
        } else {
            out[key] = 'unknown';
        }
    }
    return out;
}

function DnsIcon({ state }) {
    if (state === 'ok') return <CheckCircle2 size={12} aria-hidden="true" />;
    if (state === 'missing') return <XCircle size={12} aria-hidden="true" />;
    return <HelpCircle size={12} aria-hidden="true" />;
}

export default function Email() {
    const { t } = useTranslation();
    const [activeTab] = useTabParam('/email', VALID_TABS);

    const [status, setStatus] = useState(null);
    const [domains, setDomains] = useState([]);
    const [loading, setLoading] = useState(true);

    const loadStatus = useCallback(async () => {
        try {
            const res = await api.getEmailStatus();
            setStatus(res?.status || res || null);
        } catch {
            setStatus(null);
        }
    }, []);

    const loadDomains = useCallback(async () => {
        try {
            const res = await api.getEmailDomains();
            setDomains(res?.domains || res || []);
        } catch {
            setDomains([]);
        }
    }, []);

    useEffect(() => {
        let alive = true;
        (async () => {
            await Promise.all([loadStatus(), loadDomains()]);
            if (alive) setLoading(false);
        })();
        return () => { alive = false; };
    }, [loadStatus, loadDomains]);

    const installed = status?.installed ?? status?.is_installed ?? (status != null && status.components != null);

    const tabs = VALID_TABS.map((t) => ({
        to: `/email/${t}`,
        label: t.charAt(0).toUpperCase() + t.slice(1),
        end: false,
    }));

    return (
        <PageLayout
            navLabel="Email Server"
            tabs={tabs}
            actions={(
                <Button variant="outline" size="sm" onClick={() => { loadStatus(); loadDomains(); }}>
                    <RefreshCw size={14} /> {t('common.actions.refresh', 'Refresh')}
                </Button>
            )}
        >
            <div className="sk-email">
                {loading ? (
                    <div className="sk-email__empty">{t('common.loading', 'Loading…')}</div>
                ) : (
                    <>
                        {activeTab === 'overview' && (
                            <OverviewTab status={status} installed={installed} onChange={loadStatus} />
                        )}
                        {activeTab === 'domains' && (
                            <DomainsTab domains={domains} onChange={loadDomains} />
                        )}
                        {activeTab === 'accounts' && (
                            <AccountsTab domains={domains} />
                        )}
                        {activeTab === 'relay' && <RelayTab />}
                        {activeTab === 'spam' && <SpamTab />}
                        {activeTab === 'webmail' && <WebmailTab />}
                        {activeTab === 'queue' && <QueueTab />}
                    </>
                )}
            </div>
        </PageLayout>
    );
}

// ---------- Overview ----------
function OverviewTab({ status, installed, onChange }) {
    const { t } = useTranslation();
    const toast = useToast();
    const [installError, setInstallError] = useState(null);
    const components = status?.components || {};
    const names = Object.keys(components);

    // install_all answers {error, results: {postfix: {success, error}, ...}},
    // and the API client hangs that body off the thrown error as err.data. Dig
    // the failing components' stderr out of `results` so the user sees WHICH
    // component failed and why instead of a bare "Install failed". More than
    // one can fail in a single call: the installer only returns early on
    // postfix and dovecot, and lets dkim/spamassassin fall through.
    const installFailures = (err) => Object.entries(err?.data?.results || {})
        .filter(([, r]) => r && r.success === false)
        .map(([component, r]) => `${component}: ${r.error || 'unknown error'}`);

    const install = async () => {
        setInstallError(null);
        try {
            await api.installEmailServer();
            toast.success(t('app.email.emailServerInstallStarted', 'Email server install started'));
            onChange();
        } catch (err) {
            // err.message is the server's top-line reason ("Postfix
            // installation failed"); the failures carry the actual stderr.
            const summary = err?.message || 'Install failed';
            const failures = installFailures(err);
            // The toast stays one line — the inline block below keeps the full
            // detail on screen after the toast has gone.
            setInstallError([summary, ...failures].join('\n'));
            toast.error(failures.length ? `${summary} — ${failures[0]}` : summary);
        }
    };

    const control = async (component, action) => {
        try {
            await api.controlEmailService(component, action);
            toast.success(`${component}: ${action}`);
            onChange();
        } catch {
            toast.error(t('app.email.failedTo', 'Failed to {{action}} {{component}}', { action: action, component: component }));
        }
    };

    if (!installed) {
        return (
            <div className="sk-email__hero">
                <EmptyState
                    icon={Server}
                    title={t('app.email.mailServerNotInstalled', 'Mail server not installed')}
                    description={t('app.email.mostPanelsNeverRunAMail', 'Most panels never run a mail server, install it when you need it.')}
                    action={(
                        <Button size="sm" onClick={install}>
                            <Plus size={14} /> {t('app.email.installMailServer', 'Install mail server')}
                        </Button>
                    )}
                />
                <p className="sk-email__hero-note">
                    {t('app.email.aDeliverabilityPreflightPtrPort25', 'A deliverability preflight (PTR, port 25, RBL) gates outbound sending before mail can leave this host.')}
                </p>
                {installError && (
                    <p className="sk-email__hero-error" role="alert">{installError}</p>
                )}
            </div>
        );
    }

    const serviceRows = names.map((name) => {
        const running = components[name]?.running ?? components[name] === 'running';
        return { id: name, name, running };
    });

    const serviceColumns = [
        { key: 'component', headerKey: 'app.email.component', header: 'Component', sortable: true, hideable: false, sortValue: (r) => r.name, render: (r) => r.name },
        {
            key: 'state',
            headerKey: 'common.labels.state', header: 'State',
            sortable: true,
            sortValue: (r) => (r.running ? 1 : 0),
            render: (r) => <Pill kind={r.running ? 'green' : 'red'}>{r.running ? 'Running' : 'Stopped'}</Pill>,
        },
        {
            key: 'actions',
            header: '',
            hideable: false,
            className: 'sk-email__actions-col',
            cellClassName: 'sk-email__actions-cell',
            render: (r) => (
                <div className="sk-email__actions">
                    <Button variant="ghost" size="sm" onClick={() => control(r.name, r.running ? 'restart' : 'start')}>
                        {r.running ? 'Restart' : 'Start'}
                    </Button>
                    {r.running && (
                        <Button variant="ghost" size="sm" onClick={() => control(r.name, 'stop')}>{t('common.actions.stop', 'Stop')}</Button>
                    )}
                </div>
            ),
        },
    ];

    return (
        <section className="sk-email__section">
            <KpiBand>
                <MetricCard label={t('common.labels.domains', 'Domains')} value={status?.domains_count ?? 0} tone="accent" icon={<Globe size={16} />} />
                <MetricCard label={t('app.email.accounts', 'Accounts')} value={status?.accounts_count ?? 0} tone="cyan" icon={<Users size={16} />} />
                <MetricCard label={t('app.email.queue', 'Queue')} value={status?.queue_count ?? 0} tone="amber" icon={<Inbox size={16} />} />
            </KpiBand>

            <h2 className="sk-email__section-title"><Server size={16} /> {t('common.labels.services', 'Services')}</h2>
            <DataTable
                columns={serviceColumns}
                data={serviceRows}
                keyField="id"
                storageKey="serverkit-table-email-components"
                footer={<DataTableFooter shown={serviceRows.length} total={serviceRows.length} noun="service" />}
                emptyTitle="No service components reported."
                emptyMessage=""
            />
        </section>
    );
}

// ---------- Domains ----------
function DomainsTab({ domains, onChange }) {
    const { t } = useTranslation();
    const toast = useToast();
    const { confirm } = useConfirm();
    const [newDomain, setNewDomain] = useState('');
    const [verifying, setVerifying] = useState({});
    const [dnsResults, setDnsResults] = useState({});

    const add = async (e) => {
        e.preventDefault();
        if (!newDomain.trim()) return;
        try {
            await api.addEmailDomain({ name: newDomain.trim() });
            toast.success(t('app.email.domainAdded', 'Domain added'));
            setNewDomain('');
            onChange();
        } catch {
            toast.error(t('app.email.couldNotAddDomain', 'Could not add domain'));
        }
    };

    const remove = async (domain) => {
        const ok = await confirm({
            title: t('app.email.deleteDomain', 'Delete domain'),
            message: t('app.email.deleteAndAllOfItsAccounts', 'Delete {{name}} and all of its accounts and aliases?', { name: domain.name }),
            confirmLabel: t('common.actions.delete', 'Delete'),
            danger: true,
        });
        if (!ok) return;
        try {
            await api.deleteEmailDomain(domain.id);
            toast.success(t('app.email.domainDeleted', 'Domain deleted'));
            onChange();
        } catch {
            toast.error(t('app.email.deleteFailed', 'Delete failed'));
        }
    };

    const verify = async (domain) => {
        setVerifying((v) => ({ ...v, [domain.id]: true }));
        try {
            const res = await api.verifyEmailDNS(domain.id);
            setDnsResults((r) => ({ ...r, [domain.id]: res?.records || res || {} }));
            toast.success(t('app.email.dnsChecked', 'DNS checked'));
        } catch {
            toast.error(t('app.email.dnsCheckFailed', 'DNS check failed'));
        } finally {
            setVerifying((v) => ({ ...v, [domain.id]: false }));
        }
    };

    const deploy = async (domain) => {
        try {
            await api.deployEmailDNS(domain.id);
            toast.success(t('app.email.dnsRecordsDeployedToProvider', 'DNS records deployed to provider'));
        } catch {
            toast.error(t('app.email.deployFailedNoLinkedDnsProvider', 'Deploy failed (no linked DNS provider?)'));
        }
    };

    return (
        <section className="sk-email__section">
            <form className="sk-email__add" onSubmit={add}>
                <Input
                    value={newDomain}
                    onChange={(e) => setNewDomain(e.target.value)}
                    placeholder="example.com"
                    aria-label={t('app.email.newMailDomain', 'New mail domain')}
                />
                <Button type="submit" size="sm"><Plus size={14} /> {t('app.email.addDomain', 'Add domain')}</Button>
            </form>

            {domains.length === 0 ? (
                <div className="sk-email__empty">
                    <Globe size={24} aria-hidden="true" />
                    <p>{t('app.email.noMailDomainsYet', 'No mail domains yet.')}</p>
                </div>
            ) : (
                <ul className="sk-email__domains">
                    {domains.map((domain) => {
                        const dns = deriveDnsStatus(domain, dnsResults[domain.id]);
                        return (
                            <li key={domain.id} className="sk-email__domain">
                                <div className="sk-email__domain-head">
                                    <span className="sk-email__domain-name">{domain.name}</span>
                                    <Pill kind={domain.is_active ? 'green' : 'gray'}>
                                        {domain.is_active ? 'Active' : 'Disabled'}
                                    </Pill>
                                </div>

                                <div className="sk-email__dns">
                                    {DNS_RECORDS.map(({ key, label }) => (
                                        <Pill key={key} kind={dnsPillKind(dns[key])} title={`${label}: ${dns[key]}`}>
                                            <DnsIcon state={dns[key]} /> {label}
                                        </Pill>
                                    ))}
                                </div>

                                <div className="sk-email__domain-meta">
                                    <span>{domain.accounts_count ?? 0} accounts</span>
                                    <span>{domain.aliases_count ?? 0} aliases</span>
                                    {domain.dkim_selector && <span>{t('app.email.dkimSelector', 'DKIM selector:')} {domain.dkim_selector}</span>}
                                </div>

                                <div className="sk-email__actions">
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => verify(domain)}
                                        disabled={verifying[domain.id]}
                                    >
                                        <ShieldCheck size={14} /> {verifying[domain.id] ? 'Checking…' : 'Verify DNS'}
                                    </Button>
                                    <Button variant="outline" size="sm" onClick={() => deploy(domain)}>
                                        <ExternalLink size={14} /> {t('app.email.deployDns', 'Deploy DNS')}
                                    </Button>
                                    <Button variant="ghost" size="sm" onClick={() => remove(domain)}>
                                        <Trash2 size={14} /> {t('common.actions.delete', 'Delete')}
                                    </Button>
                                </div>
                            </li>
                        );
                    })}
                </ul>
            )}
        </section>
    );
}

// ---------- Accounts ----------

// Percent of an account's own quota in use, so a 200 MB mailbox on a 250 MB
// quota outranks a 2 GB one on 20 GB. null — not 0 — when no quota is set:
// an unlimited mailbox can never be "nearly full", and the rule engine drops
// nulls from every numeric comparison rather than reading them as empty.
function quotaPercent(account) {
    const total = account?.quota_mb ?? 0;
    if (!total) return null;
    return Math.round(((account.quota_used_mb ?? 0) / total) * 100);
}

// Built-in saved views for the accounts table.
//
// The rules match on what the State column's `value` accessor returns (the
// label the pill shows), NOT on the 1/0 its sortValue produces — filtering a
// string against a numeric rank is the one mistake that makes a preset match
// zero rows while looking perfectly correct.
const ACCOUNT_VIEWS = [
    { name: 'Active first', state: { search: '', sorts: [{ key: 'state', direction: 'desc' }], hiddenKeys: [], columnFilters: NO_RULES } },
    { name: 'Largest quota', state: { search: '', sorts: [{ key: 'quota', direction: 'desc' }], hiddenKeys: [], columnFilters: NO_RULES } },
    {
        // A disabled mailbox still exists and still holds its mail — it just
        // cannot authenticate. This is the list you audit after an offboarding.
        name: 'Disabled',
        state: {
            search: '', hiddenKeys: [],
            sorts: [{ key: 'email', direction: 'asc' }],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'ac1', field: 'state', op: 'any', value: ['Disabled'] }],
            },
        },
    },
    {
        // Mailboxes about to start rejecting deliveries. Same 85% threshold the
        // fleet uses for disk pressure, and `gt` on a null keeps the unlimited
        // mailboxes out instead of ranking them as 0%.
        name: 'Nearly full',
        state: {
            search: '', hiddenKeys: [],
            sorts: [{ key: 'used', direction: 'desc' }],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'ac2', field: 'used', op: 'gt', value: 85 }],
            },
        },
    },
];

function AccountsTab({ domains }) {
    const { t } = useTranslation();
    const toast = useToast();
    const { confirm } = useConfirm();
    const [domainId, setDomainId] = useState(domains[0]?.id ? String(domains[0].id) : '');
    const [accounts, setAccounts] = useState([]);
    const [loading, setLoading] = useState(false);
    const [search, setSearch] = useState('');
    const [form, setForm] = useState({ username: '', password: '', quota_mb: 1024 });
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-email-accounts-sort' });
    const { hiddenKeys, setHiddenKeys } = useColumnVisibility({ storageKey: 'serverkit-table-email-accounts-cols' });

    // The only view state this tab owns privately. Everything else — sorts,
    // hidden columns, column order, the column rules — is the shared envelope
    // useTableChrome captures for us. The selected domain deliberately stays
    // OUT of it: it is which list you are looking at, not how you are looking
    // at it, and a saved view that silently jumped domains would be a trap.
    const viewPageState = useMemo(() => ({ search }), [search]);
    const applyViewPageState = useCallback((saved) => {
        if (saved.search !== undefined) setSearch(saved.search);
    }, []);

    const load = useCallback(async () => {
        if (!domainId) { setAccounts([]); return; }
        setLoading(true);
        try {
            const res = await api.getEmailAccounts(domainId);
            setAccounts(res?.accounts || res || []);
        } catch {
            setAccounts([]);
        } finally {
            setLoading(false);
        }
    }, [domainId]);

    useEffect(() => { load(); }, [load]);

    const create = async (e) => {
        e.preventDefault();
        if (!form.username.trim() || !form.password) return;
        try {
            await api.createEmailAccount(domainId, form);
            toast.success(t('app.email.accountCreated', 'Account created'));
            setForm({ username: '', password: '', quota_mb: 1024 });
            load();
        } catch {
            toast.error(t('app.email.createFailed', 'Create failed'));
        }
    };

    const remove = async (account) => {
        const ok = await confirm({
            title: t('app.email.deleteAccount', 'Delete account'),
            message: t('app.email.delete3', 'Delete {{email}}?', { email: account.email }),
            confirmLabel: t('common.actions.delete', 'Delete'),
            danger: true,
        });
        if (!ok) return;
        try {
            await api.deleteEmailAccount(account.id);
            toast.success(t('app.email.accountDeleted', 'Account deleted'));
            load();
        } catch {
            toast.error(t('app.email.deleteFailed', 'Delete failed'));
        }
    };

    const filtered = useMemo(() => {
        const q = search.trim().toLowerCase();
        if (!q) return accounts;
        return accounts.filter((a) => (a.email || '').toLowerCase().includes(q));
    }, [accounts, search]);

    const accountColumns = [
        {
            key: 'email',
            headerKey: 'app.email.address', header: 'Address',
            sortable: true,
            hideable: false,
            sortValue: (a) => a.email || '',
            render: (a) => <span className="sk-email__mono">{a.email}</span>,
        },
        {
            key: 'quota',
            headerKey: 'app.email.quota', header: 'Quota',
            sortable: true,
            type: 'num',
            unit: ' MB',
            // The allocation, which is what "Largest quota" orders by. How full
            // it is lives in its own column below.
            value: (a) => a.quota_mb ?? 0,
            sortValue: (a) => a.quota_mb ?? 0,
            render: (a) => `${a.quota_used_mb ?? 0} / ${a.quota_mb ?? 0} MB`,
        },
        {
            key: 'used',
            headerKey: 'app.email.used', header: 'Used',
            sortable: true,
            type: 'num',
            unit: '%',
            value: quotaPercent,
            sortValue: quotaPercent,
            render: (a) => {
                const pct = quotaPercent(a);
                return pct == null ? '—' : `${pct}%`;
            },
        },
        {
            key: 'state',
            headerKey: 'common.labels.state', header: 'State',
            sortable: true,
            // Filter on the label the pill shows; keep the 1/0 sortValue so
            // "Active first" still puts active first when the column sorts desc.
            type: 'enum',
            value: (a) => (a.is_active ? 'Active' : 'Disabled'),
            sortValue: (a) => (a.is_active ? 1 : 0),
            render: (a) => <Pill kind={a.is_active ? 'green' : 'gray'}>{a.is_active ? 'Active' : 'Disabled'}</Pill>,
        },
        {
            key: 'actions',
            header: '',
            hideable: false,
            className: 'sk-email__actions-col',
            cellClassName: 'sk-email__actions-cell',
            render: (a) => (
                <div className="sk-email__actions">
                    <Button variant="ghost" size="sm" onClick={() => remove(a)}>
                        <Trash2 size={14} /> {t('common.actions.delete', 'Delete')}
                    </Button>
                </div>
            ),
        },
    ];

    // Each tab is its own route, so only one picker is ever mounted — this
    // chrome is scoped to the accounts table alone and keeps its own page key.
    const chrome = useTableChrome({
        columns: accountColumns,
        rows: filtered,
        viewPageKey: 'email-accounts',
        builtinViews: ACCOUNT_VIEWS,
        noun: 'accounts',
        sorts,
        setSorts,
        hiddenKeys,
        setHiddenKeys,
        pageState: viewPageState,
        applyPage: applyViewPageState,
    });

    if (domains.length === 0) {
        return (
            <div className="sk-email__empty">
                <Users size={24} aria-hidden="true" />
                <p>{t('app.email.addAMailDomainFirst', 'Add a mail domain first.')}</p>
            </div>
        );
    }

    return (
        <section className="sk-email__section">
            {/* One row of chrome: the view name and the table's own controls.
                What stays in the toolbar below is not chrome — the domain
                select is WHICH list you are looking at. */}
            <GridViewPicker
                views={chrome.views}
                label="accounts"
                onCreate={chrome.createView}
                actions={(
                    <>
                        <GridFilterButton
                            count={chrome.filterCount}
                            onClick={() => chrome.setDrawerOpen(true)}
                        />
                        <GridToolsMenu {...chrome.toolsProps} onRefresh={load} />
                    </>
                )}
            />
            <ListToolbar className="sk-email__filters">
                <label>
                    {t('common.labels.domain', 'Domain')}
                    <select value={domainId} onChange={(e) => setDomainId(e.target.value)}>
                        {domains.map((d) => <option key={d.id} value={String(d.id)}>{d.name}</option>)}
                    </select>
                </label>
                <label className="search-box">
                    <Search size={16} />
                    <Input
                        type="text"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        placeholder={t('app.email.searchAccountsByAddress', 'Search accounts by address…')}
                        aria-label={t('app.email.searchAccounts', 'Search accounts')}
                    />
                </label>
            </ListToolbar>

            <GridChips {...chrome.chipProps} />

            <form className="sk-email__add" onSubmit={create}>
                <Input
                    value={form.username}
                    onChange={(e) => setForm({ ...form, username: e.target.value })}
                    placeholder="username"
                    aria-label={t('app.email.mailboxUsername', 'Mailbox username')}
                />
                <Input
                    type="password"
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    placeholder="password"
                    aria-label={t('app.email.mailboxPassword', 'Mailbox password')}
                />
                <Input
                    type="number"
                    value={form.quota_mb}
                    onChange={(e) => setForm({ ...form, quota_mb: Number(e.target.value) })}
                    placeholder={t('app.email.quotaMb', 'Quota (MB)')}
                    aria-label={t('app.email.quotaInMb', 'Quota in MB')}
                />
                <Button type="submit" size="sm"><Plus size={14} /> {t('common.actions.create', 'Create')}</Button>
            </form>

            <DataTable
                columns={chrome.columns}
                data={filtered}
                keyField="id"
                sorts={sorts}
                onSortsChange={setSorts}
                {...chrome.tableProps}
                loading={loading}
                footer={<DataTableFooter shown={filtered.length} total={accounts.length} noun="account" />}
                emptyTitle={accounts.length === 0 ? 'No accounts in this domain.' : 'No accounts match this search.'}
                emptyMessage=""
            />

            <GridFilterDrawer {...chrome.drawerProps} />
        </section>
    );
}

// ---------- Relay (smarthost) ----------
function RelayTab() {
    const { t } = useTranslation();
    const toast = useToast();
    const [relay, setRelay] = useState({ host: '', port: 587, username: '', password: '', enabled: false });
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let alive = true;
        api.getEmailRelay()
            .then((res) => { if (alive) setRelay((r) => ({ ...r, ...(res?.relay || res || {}) })); })
            .catch(() => { /* defaults */ })
            .finally(() => { if (alive) setLoading(false); });
        return () => { alive = false; };
    }, []);

    const save = async (e) => {
        e.preventDefault();
        try {
            await api.updateEmailRelay(relay);
            toast.success(t('app.email.relaySaved', 'Relay saved'));
        } catch {
            toast.error(t('app.email.saveFailed', 'Save failed'));
        }
    };

    const test = async () => {
        try {
            await api.testEmailRelay(relay);
            toast.success(t('app.email.relayReachable', 'Relay reachable'));
        } catch {
            toast.error(t('app.email.relayTestFailed', 'Relay test failed'));
        }
    };

    const disable = async () => {
        try {
            await api.disableEmailRelay();
            setRelay((r) => ({ ...r, enabled: false }));
            toast.success(t('app.email.relayDisabled', 'Relay disabled'));
        } catch {
            toast.error(t('app.email.failedToDisableRelay', 'Failed to disable relay'));
        }
    };

    if (loading) return <div className="sk-email__empty">{t('common.loading', 'Loading…')}</div>;

    return (
        <section className="sk-email__section">
            <h2 className="sk-email__section-title"><Send size={16} /> {t('app.email.outboundRelaySmarthost', 'Outbound relay (smarthost)')}</h2>
            <form className="sk-email__form" onSubmit={save}>
                <label>{t('app.email.host', 'Host')}<Input value={relay.host || ''} onChange={(e) => setRelay({ ...relay, host: e.target.value })} placeholder="smtp.provider.com" /></label>
                <label>{t('common.labels.port', 'Port')}<Input type="number" value={relay.port || 587} onChange={(e) => setRelay({ ...relay, port: Number(e.target.value) })} /></label>
                <label>{t('common.labels.username', 'Username')}<Input value={relay.username || ''} onChange={(e) => setRelay({ ...relay, username: e.target.value })} /></label>
                <label>{t('common.labels.password', 'Password')}<Input type="password" value={relay.password || ''} onChange={(e) => setRelay({ ...relay, password: e.target.value })} /></label>
                <label className="sk-email__check">
                    <input type="checkbox" checked={!!relay.enabled} onChange={(e) => setRelay({ ...relay, enabled: e.target.checked })} />
                    {t('app.email.enableRelay', 'Enable relay')}
                </label>
                <div className="sk-email__actions">
                    <Button type="submit" size="sm">{t('common.actions.save', 'Save')}</Button>
                    <Button type="button" variant="outline" size="sm" onClick={test}>{t('common.actions.test', 'Test')}</Button>
                    <Button type="button" variant="ghost" size="sm" onClick={disable}>{t('common.actions.disable', 'Disable')}</Button>
                </div>
            </form>
        </section>
    );
}

// ---------- Spam ----------
function SpamTab() {
    const { t } = useTranslation();
    const toast = useToast();
    const [config, setConfig] = useState({ enabled: true, required_score: 5 });
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let alive = true;
        api.getSpamConfig()
            .then((res) => { if (alive) setConfig((c) => ({ ...c, ...(res?.config || res || {}) })); })
            .catch(() => { /* defaults */ })
            .finally(() => { if (alive) setLoading(false); });
        return () => { alive = false; };
    }, []);

    const save = async (e) => {
        e.preventDefault();
        try {
            await api.updateSpamConfig(config);
            toast.success(t('app.email.spamConfigSaved', 'Spam config saved'));
        } catch {
            toast.error(t('app.email.saveFailed', 'Save failed'));
        }
    };

    const updateRules = async () => {
        try {
            await api.updateSpamRules();
            toast.success(t('app.email.ruleUpdateStarted', 'Rule update started'));
        } catch {
            toast.error(t('app.email.ruleUpdateFailed', 'Rule update failed'));
        }
    };

    if (loading) return <div className="sk-email__empty">{t('common.loading', 'Loading…')}</div>;

    return (
        <section className="sk-email__section">
            <h2 className="sk-email__section-title"><Filter size={16} /> {t('app.email.spamassassin', 'SpamAssassin')}</h2>
            <form className="sk-email__form" onSubmit={save}>
                <label className="sk-email__check">
                    <input type="checkbox" checked={!!config.enabled} onChange={(e) => setConfig({ ...config, enabled: e.target.checked })} />
                    {t('app.email.enableSpamFiltering', 'Enable spam filtering')}
                </label>
                <label>{t('app.email.requiredScore', 'Required score')}<Input type="number" step="0.1" value={config.required_score ?? 5} onChange={(e) => setConfig({ ...config, required_score: Number(e.target.value) })} /></label>
                <div className="sk-email__actions">
                    <Button type="submit" size="sm">{t('common.actions.save', 'Save')}</Button>
                    <Button type="button" variant="outline" size="sm" onClick={updateRules}>{t('app.email.updateRules', 'Update rules')}</Button>
                </div>
            </form>
        </section>
    );
}

// ---------- Webmail ----------
function WebmailTab() {
    const { t } = useTranslation();
    const toast = useToast();
    const [state, setState] = useState(null);
    const [loading, setLoading] = useState(true);

    const load = useCallback(async () => {
        try {
            const res = await api.getWebmailStatus();
            setState(res?.status || res || null);
        } catch {
            setState(null);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const install = async () => {
        try {
            await api.installWebmail();
            toast.success(t('app.email.webmailInstallStarted', 'Webmail install started'));
            load();
        } catch {
            toast.error(t('app.email.installFailed', 'Install failed'));
        }
    };

    const control = async (action) => {
        try {
            await api.controlWebmail(action);
            toast.success(t('app.email.webmail', 'Webmail: {{action}}', { action: action }));
            load();
        } catch {
            toast.error(t('app.email.failedToWebmail', 'Failed to {{action}} webmail', { action: action }));
        }
    };

    if (loading) return <div className="sk-email__empty">{t('common.loading', 'Loading…')}</div>;

    const installed = state?.installed ?? state?.is_installed;
    const running = state?.running;

    return (
        <section className="sk-email__section">
            <h2 className="sk-email__section-title"><Inbox size={16} /> {t('app.email.roundcubeWebmail', 'Roundcube webmail')}</h2>
            {!installed ? (
                <div className="sk-email__empty">
                    <p>{t('app.email.webmailIsNotInstalled', 'Webmail is not installed.')}</p>
                    <Button size="sm" onClick={install}><Plus size={14} /> {t('app.email.installWebmail', 'Install webmail')}</Button>
                </div>
            ) : (
                <div className="sk-email__actions">
                    <Pill kind={running ? 'green' : 'red'}>{running ? 'Running' : 'Stopped'}</Pill>
                    <Button variant="outline" size="sm" onClick={() => control(running ? 'restart' : 'start')}>
                        {running ? 'Restart' : 'Start'}
                    </Button>
                    {running && <Button variant="ghost" size="sm" onClick={() => control('stop')}>{t('common.actions.stop', 'Stop')}</Button>}
                </div>
            )}
        </section>
    );
}

// ---------- Mail queue ----------

// Built-in saved views for the queue.
//
// The queue payload is `mailq` output — a queue id, a byte size, a sender and
// its recipients. There is no status field, so nothing here pretends there is
// one: the only rule-based preset filters on `size`, which is a real integer on
// every row (see PostfixService.get_queue).
const QUEUE_VIEWS = [
    { name: 'Largest first', state: { search: '', sorts: [{ key: 'size', direction: 'desc' }], hiddenKeys: [], columnFilters: NO_RULES } },
    { name: 'By sender', state: { search: '', sorts: [{ key: 'sender', direction: 'asc' }], hiddenKeys: [], columnFilters: NO_RULES } },
    {
        // What a backed-up queue is usually full of. 100 KB is the line between
        // a plain message (a few KB) and one carrying an attachment; Postfix's
        // own message_size_limit is 25 MB, so this is well inside real traffic.
        name: 'Large messages',
        state: {
            search: '', hiddenKeys: [],
            sorts: [{ key: 'size', direction: 'desc' }],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'q1', field: 'size', op: 'gt', value: 102400 }],
            },
        },
    },
];

function QueueTab() {
    const { t } = useTranslation();
    const toast = useToast();
    const [queue, setQueue] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-email-queue-sort' });
    const { hiddenKeys, setHiddenKeys } = useColumnVisibility({ storageKey: 'serverkit-table-email-queue-cols' });

    // Search is all this tab owns privately; the rest of the view state is the
    // shared envelope useTableChrome captures.
    const viewPageState = useMemo(() => ({ search }), [search]);
    const applyViewPageState = useCallback((saved) => {
        if (saved.search !== undefined) setSearch(saved.search);
    }, []);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const res = await api.getMailQueue();
            setQueue(res?.queue || res || []);
        } catch {
            setQueue([]);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const flush = async () => {
        try {
            await api.flushMailQueue();
            toast.success(t('app.email.queueFlushed', 'Queue flushed'));
            load();
        } catch {
            toast.error(t('app.email.flushFailed', 'Flush failed'));
        }
    };

    const remove = async (id) => {
        try {
            await api.deleteMailQueueItem(id);
            load();
        } catch {
            toast.error(t('app.email.deleteFailed', 'Delete failed'));
        }
    };

    const filtered = queue.filter((item) => {
        const q = search.trim().toLowerCase();
        if (!q) return true;
        const id = String(item.id || item.queue_id || '').toLowerCase();
        const sender = String(item.sender || '').toLowerCase();
        const recipient = String(item.recipient || '').toLowerCase();
        return id.includes(q) || sender.includes(q) || recipient.includes(q);
    });

    const queueColumns = [
        {
            key: 'id',
            header: 'ID',
            sortable: true,
            hideable: false,
            sortValue: (item) => item.id || item.queue_id || '',
            render: (item) => <span className="sk-email__mono">{item.id || item.queue_id}</span>,
        },
        { key: 'sender', headerKey: 'app.email.sender', header: 'Sender', sortable: true, sortValue: (item) => item.sender || null, render: (item) => item.sender || '-' },
        { key: 'recipient', headerKey: 'app.email.recipient', header: 'Recipient', sortable: true, sortValue: (item) => item.recipient || null, render: (item) => item.recipient || '-' },
        {
            key: 'size',
            headerKey: 'common.labels.size', header: 'Size',
            sortable: true,
            // Bytes, straight off mailq. Typed explicitly because a preset
            // filters on it — inference would land on 'num' here anyway, but
            // only for as long as every loaded row happens to carry a size.
            type: 'num',
            unit: ' bytes',
            value: (item) => item.size ?? null,
            sortValue: (item) => item.size ?? null,
            render: (item) => item.size || '-',
        },
        {
            key: 'actions',
            header: '',
            hideable: false,
            className: 'sk-email__actions-col',
            cellClassName: 'sk-email__actions-cell',
            render: (item) => (
                <div className="sk-email__actions">
                    <Button variant="ghost" size="sm" onClick={() => remove(item.id || item.queue_id)}>
                        <Trash2 size={14} /> {t('common.actions.delete', 'Delete')}
                    </Button>
                </div>
            ),
        },
    ];

    const chrome = useTableChrome({
        columns: queueColumns,
        rows: filtered,
        viewPageKey: 'email-queue',
        builtinViews: QUEUE_VIEWS,
        noun: 'messages',
        sorts,
        setSorts,
        hiddenKeys,
        setHiddenKeys,
        pageState: viewPageState,
        applyPage: applyViewPageState,
    });

    return (
        <section className="sk-email__section">
            {/* Everything that acts on the queue rides the view line, in the
                same order the topbar pages use: action, search, filter, "⋮".
                Refresh is not repeated as a button — it is in the "⋮". */}
            <GridViewPicker
                views={chrome.views}
                label="messages"
                onCreate={chrome.createView}
                actions={(
                    <>
                        <Button variant="outline" size="sm" onClick={flush}>{t('app.email.flushQueue', 'Flush queue')}</Button>
                        <SearchField
                            value={search}
                            onSearch={setSearch}
                            placeholder={t('app.email.searchQueueBySenderRecipientOr', 'Search queue by sender, recipient, or ID…')}
                        />
                        <GridFilterButton
                            count={chrome.filterCount}
                            onClick={() => chrome.setDrawerOpen(true)}
                        />
                        <GridToolsMenu {...chrome.toolsProps} onRefresh={load} />
                    </>
                )}
            />

            <GridChips {...chrome.chipProps} />

            <DataTable
                columns={chrome.columns}
                data={filtered}
                keyField={(item) => item.id || item.queue_id}
                sorts={sorts}
                onSortsChange={setSorts}
                {...chrome.tableProps}
                loading={loading}
                footer={<DataTableFooter shown={filtered.length} total={queue.length} noun="message" />}
                emptyTitle={queue.length === 0 ? 'The mail queue is empty.' : 'No messages match this search.'}
                emptyMessage=""
            />

            <GridFilterDrawer {...chrome.drawerProps} />
        </section>
    );
}
