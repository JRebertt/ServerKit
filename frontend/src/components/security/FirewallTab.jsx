import { useState, useEffect, useMemo } from 'react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { useConfirm } from '@/hooks/useConfirm';
import EmptyState from '@/components/EmptyState';
import Modal from '../Modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { DataTable, DataTableFooter, ListToolbar, Pill, SegControl } from '@/components/ds';
import {
    useTableChrome, GridViewPicker, GridChips, GridFilterButton,
    GridToolsMenu, GridFilterDrawer, applyFilters,
} from '@/components/ds/grid';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { Ban, Shield } from 'lucide-react';
import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue } from '@/components/ui/select';

const RULE_TYPE_TONES = {
    port: 'accent',
    service: 'cyan',
    rich: 'violet',
};

// UFW and firewalld describe the same rule differently: firewalld splits a port
// rule into `port` + `protocol`, while UFW hands back one printed target
// ('8080/tcp') and no protocol field at all. Reading both here is what lets a
// saved view mean the same thing whichever firewall the host runs — and stops
// the Protocol column reading '-' on every UFW box.
const ruleTarget = (rule) => rule.service || rule.port || rule.rule || '';
const ruleProtocol = (rule) => (
    rule.protocol || /\/(tcp|udp)\b/i.exec(String(ruleTarget(rule)))?.[1] || ''
).toLowerCase();

// Built-in saved views. Every rule matches a column's `value` accessor, so the
// strings below are what the Protocol cell actually shows: 'tcp' / 'udp' for a
// port opening on either firewall, and '' for a rule that opens no port at all.
// The three partition the table on that one axis, because "what is reachable"
// and "what is blocked or named" are the two questions this list answers.
const FIREWALL_VIEWS = [
    {
        // The port surface, in target order: what this host answers on. A
        // firewalld *service* rule (ssh, http) carries no protocol of its own,
        // so it is deliberately absent here — it lands under the third view.
        name: 'Port openings',
        state: {
            sorts: [{ key: 'target', direction: 'asc' }],
            hiddenKeys: [],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'fw1', field: 'protocol', op: 'any', value: ['tcp', 'udp'] }],
            },
        },
    },
    {
        // Short by design. UDP gets opened for DNS, WireGuard or QUIC and
        // almost never by accident, so any row appearing here is worth reading.
        name: 'UDP openings',
        state: {
            sorts: [{ key: 'target', direction: 'asc' }],
            hiddenKeys: [],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'fw2', field: 'protocol', op: 'any', value: ['udp'] }],
            },
        },
    },
    {
        // The half the two port views hide: firewalld services and rich
        // drop/reject rules, UFW app profiles and address-scoped rules. An IP
        // block lives here, so this is the list to read after an incident.
        name: 'Service & rich rules',
        state: {
            sorts: [{ key: 'type', direction: 'asc' }, { key: 'target', direction: 'asc' }],
            hiddenKeys: [],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'fw3', field: 'protocol', op: 'none', value: ['tcp', 'udp'] }],
            },
        },
    },
];

const FirewallTab = () => {
    const [status, setStatus] = useState(null);
    const [rules, setRules] = useState([]);
    const [blockedIPs, setBlockedIPs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [activeSubTab, setActiveSubTab] = useState('status');
    const [showBlockIPModal, setShowBlockIPModal] = useState(false);
    const [showPortModal, setShowPortModal] = useState(false);
    const [showInstallModal, setShowInstallModal] = useState(false);
    const [blockIP, setBlockIP] = useState('');
    const [newPort, setNewPort] = useState({ port: '', protocol: 'tcp' });
    const [selectedFirewall, setSelectedFirewall] = useState('ufw');
    const [actionLoading, setActionLoading] = useState(false);
    const [guard, setGuard] = useState(null);
    const [guardLoading, setGuardLoading] = useState(false);
    const toast = useToast();
    const { confirm } = useConfirm();
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-firewall-rules-sort' });
    const {
        hiddenKeys, setHiddenKeys,
    } = useColumnVisibility({ storageKey: 'serverkit-table-firewall-rules-cols' });

    const commonPorts = [
        { port: 22, name: 'SSH', protocol: 'tcp' },
        { port: 80, name: 'HTTP', protocol: 'tcp' },
        { port: 443, name: 'HTTPS', protocol: 'tcp' },
        { port: 21, name: 'FTP', protocol: 'tcp' },
        { port: 25, name: 'SMTP', protocol: 'tcp' },
        { port: 3306, name: 'MySQL', protocol: 'tcp' },
        { port: 5432, name: 'PostgreSQL', protocol: 'tcp' },
        { port: 6379, name: 'Redis', protocol: 'tcp' },
        { port: 27017, name: 'MongoDB', protocol: 'tcp' },
    ];

    useEffect(() => {
        loadData();
    }, []);

    const loadData = async () => {
        setLoading(true);
        try {
            await Promise.all([loadStatus(), loadRules(), loadBlockedIPs(), loadGuard()]);
        } catch (error) {
            console.error('Failed to load firewall data:', error);
        } finally {
            setLoading(false);
        }
    };

    const loadStatus = async () => {
        try {
            const data = await api.getFirewallStatus();
            setStatus(data);
        } catch (error) {
            console.error('Failed to load status:', error);
        }
    };

    const loadRules = async () => {
        try {
            const data = await api.getFirewallRules();
            setRules(data.rules || []);
        } catch (error) {
            console.error('Failed to load rules:', error);
        }
    };

    const loadBlockedIPs = async () => {
        try {
            const data = await api.getBlockedIPs();
            setBlockedIPs(data.blocked_ips || []);
        } catch (error) {
            console.error('Failed to load blocked IPs:', error);
        }
    };

    const loadGuard = async () => {
        try {
            const data = await api.getMetadataGuard();
            setGuard(data);
        } catch (error) {
            console.error('Failed to load metadata guard status:', error);
        }
    };

    const handleGuardToggle = async (enabled) => {
        setGuardLoading(true);
        try {
            const data = await api.setMetadataGuard(enabled);
            setGuard(data);
            toast.success(`Cloud metadata guard ${enabled ? 'enabled' : 'disabled'}`);
        } catch (error) {
            toast.error(`Failed to update metadata guard: ${error.message}`);
            await loadGuard();
        } finally {
            setGuardLoading(false);
        }
    };

    const handleEnable = async () => {
        setActionLoading(true);
        try {
            await api.enableFirewall();
            toast.success('Firewall enabled');
            await loadStatus();
        } catch (error) {
            toast.error(`Failed to enable firewall: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleDisable = async () => {
        const confirmed = await confirm({
            title: 'Disable Firewall',
            message: 'Are you sure you want to disable the firewall? This will leave your server unprotected.',
            confirmText: 'Disable',
            variant: 'danger',
        });
        if (!confirmed) return;
        setActionLoading(true);
        try {
            await api.disableFirewall();
            toast.success('Firewall disabled');
            await loadStatus();
        } catch (error) {
            toast.error(`Failed to disable firewall: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleBlockIP = async () => {
        if (!blockIP.trim()) return;
        setActionLoading(true);
        try {
            await api.blockIP(blockIP);
            toast.success(`IP ${blockIP} blocked`);
            setShowBlockIPModal(false);
            setBlockIP('');
            await loadBlockedIPs();
            await loadRules();
        } catch (error) {
            toast.error(`Failed to block IP: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleUnblockIP = async (ip) => {
        const confirmed = await confirm({
            title: 'Unblock IP',
            message: `Are you sure you want to unblock ${ip}?`,
            confirmText: 'Unblock',
            variant: 'warning',
        });
        if (!confirmed) return;
        try {
            await api.unblockIP(ip);
            toast.success(`IP ${ip} unblocked`);
            await loadBlockedIPs();
            await loadRules();
        } catch (error) {
            toast.error(`Failed to unblock IP: ${error.message}`);
        }
    };

    const handleAllowPort = async () => {
        if (!newPort.port) return;
        setActionLoading(true);
        try {
            await api.allowPort(parseInt(newPort.port), newPort.protocol);
            toast.success(`Port ${newPort.port}/${newPort.protocol} allowed`);
            setShowPortModal(false);
            setNewPort({ port: '', protocol: 'tcp' });
            await loadRules();
        } catch (error) {
            toast.error(`Failed to allow port: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleQuickAllowPort = async (port, protocol) => {
        setActionLoading(true);
        try {
            await api.allowPort(port, protocol);
            toast.success(`Port ${port}/${protocol} allowed`);
            await loadRules();
        } catch (error) {
            toast.error(`Failed to allow port: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleRemovePort = async (port, protocol) => {
        const confirmed = await confirm({
            title: 'Remove Port Rule',
            message: `Are you sure you want to remove the rule for port ${port}/${protocol}?`,
            confirmText: 'Remove',
            variant: 'danger',
        });
        if (!confirmed) return;
        try {
            await api.denyPort(parseInt(port), protocol);
            toast.success(`Port ${port}/${protocol} rule removed`);
            await loadRules();
        } catch (error) {
            toast.error(`Failed to remove port: ${error.message}`);
        }
    };

    const handleInstall = async () => {
        setActionLoading(true);
        try {
            await api.installFirewall(selectedFirewall);
            toast.success(`${selectedFirewall.toUpperCase()} installed successfully`);
            setShowInstallModal(false);
            await loadData();
        } catch (error) {
            toast.error(`Failed to install firewall: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const isActive = status?.any_active;
    const activeFirewall = status?.active_firewall;

    // Cell markup/classNames are identical to the hand-rolled table they
    // replace, so _security.scss keeps applying (.sec-state, .sec-rich-rule…).
    const ruleColumns = [
        {
            key: 'type',
            header: 'Type',
            sortable: true,
            sortValue: (rule) => rule.type || '',
            render: (rule) => (
                <span className={`sec-state sec-state--${RULE_TYPE_TONES[rule.type] || 'gray'}`}>
                    {rule.type}
                </span>
            ),
        },
        {
            key: 'target',
            header: 'Target',
            sortable: true,
            sortValue: ruleTarget,
            cellClassName: 'sk-cell-mono',
            render: (rule) => (
                <>
                    {rule.type === 'service' && rule.service}
                    {rule.type === 'port' && rule.port}
                    {rule.type === 'rich' && <span className="sec-rich-rule">{rule.rule}</span>}
                </>
            ),
        },
        {
            key: 'protocol',
            header: 'Protocol',
            sortable: true,
            // Declared, not inferred: with only tcp/udp in play a short rule
            // list fails the enum cardinality test and falls back to text,
            // which turns the pick-list into a typed fragment and every view
            // above into a no-op. `value` is what the rules read; `sortValue`
            // is what the sorter reads, and they must agree.
            type: 'enum',
            value: ruleProtocol,
            sortValue: ruleProtocol,
            cellClassName: 'sk-cell-mono sec-proto',
            render: (rule) => ruleProtocol(rule) || '-',
        },
        {
            key: 'actions',
            header: 'Actions',
            sortable: false,
            hideable: false,
            render: (rule) => (
                rule.type === 'port' && (
                    <Button variant="destructive" size="sm" onClick={() => handleRemovePort(rule.port, rule.protocol)}>
                        Remove
                    </Button>
                )
            ),
        },
    ];

    // Saved views are scoped to THIS table, not to Security as a page: only one
    // of the 13 tabs is mounted at a time, so a picker at the page heading would
    // sit above whichever tab happened to be open. No `urlScope` either — the
    // rules table is the only one on this tab, so its shareable links keep the
    // plain ?view= names every single-table page produces.
    //
    // No `pageState`: the sub-tab strip below is navigation, not a filter, and a
    // view that switched you to another sub-tab would hide the table it names.
    const chrome = useTableChrome({
        columns: ruleColumns,
        rows: rules,
        viewPageKey: 'security-firewall',
        builtinViews: FIREWALL_VIEWS,
        noun: 'rules',
        sorts,
        setSorts,
        hiddenKeys,
        setHiddenKeys,
    });

    // The count has to be the count you can SEE. DataTable applies the column
    // rules itself, so without re-applying them here a view that narrows to two
    // rows would still claim the full total.
    const shownRules = useMemo(
        () => applyFilters(rules, chrome.cfg.filters, chrome.columns),
        [rules, chrome.cfg.filters, chrome.columns],
    );

    if (loading) {
        return <div className="loading-sm">Loading firewall status...</div>;
    }

    return (
        <div className="firewall-tab">
            {!status?.any_installed ? (
                <EmptyState
                    icon={Shield}
                    title="No Firewall Installed"
                    description="Install a firewall to protect your server from unauthorized access."
                    action={(
                        <Button variant="default" onClick={() => setShowInstallModal(true)}>
                            Install Firewall
                        </Button>
                    )}
                />
            ) : (
                <>
                    <div className="firewall-header">
                        <div className="firewall-status-row">
                            <div className={`status-indicator ${isActive ? 'active' : 'inactive'}`}>
                                <span className="sec-shield">
                                    <Shield size={17} />
                                </span>
                                <span className="status-indicator__label">{isActive ? 'Firewall Active' : 'Firewall Inactive'}</span>
                                <span className="firewall-type">{activeFirewall?.toUpperCase()}</span>
                            </div>
                            <div className="firewall-actions">
                                <Button variant="outline" size="sm" onClick={() => setShowBlockIPModal(true)}>
                                    Block IP
                                </Button>
                                <Button variant="outline" size="sm" onClick={() => setShowPortModal(true)}>
                                    Allow Port
                                </Button>
                                {isActive ? (
                                    <Button variant="destructive" size="sm" onClick={handleDisable} disabled={actionLoading}>
                                        Disable
                                    </Button>
                                ) : (
                                    <Button variant="default" size="sm" onClick={handleEnable} disabled={actionLoading}>
                                        Enable
                                    </Button>
                                )}
                            </div>
                        </div>
                    </div>

                    <div className="firewall-stats">
                        <div className="stat-mini">
                            <span className="stat-value">{rules.length}</span>
                            <span className="stat-label">Rules</span>
                        </div>
                        <div className="stat-mini">
                            <span className="stat-value">{blockedIPs.length}</span>
                            <span className="stat-label">Blocked IPs</span>
                        </div>
                        <div className="stat-mini">
                            <span className="stat-value">{rules.filter(r => r.type === 'port' || r.port).length}</span>
                            <span className="stat-label">Ports Open</span>
                        </div>
                    </div>

                    <SegControl
                        className="sec-subseg"
                        value={activeSubTab}
                        onChange={setActiveSubTab}
                        options={[
                            { value: 'status', label: 'Status' },
                            { value: 'rules', label: 'Rules', count: rules.length },
                            { value: 'blocked', label: 'Blocked IPs', count: blockedIPs.length },
                            { value: 'quick', label: 'Quick Ports' },
                        ]}
                    />

                    {activeSubTab === 'status' && (
                        <div className="card">
                            <div className="card-header">
                                <h3>Firewall Information</h3>
                                <Button variant="outline" size="sm" onClick={loadData}>Refresh</Button>
                            </div>
                            <div className="card-body">
                                <div className="sec-rows">
                                    <div className="sk-info-row">
                                        <span className="k">Type</span>
                                        <span className="v">{activeFirewall?.toUpperCase()}</span>
                                    </div>
                                    <div className="sk-info-row">
                                        <span className="k">Status</span>
                                        <Pill kind={isActive ? 'green' : 'red'}>
                                            {isActive ? 'Active' : 'Inactive'}
                                        </Pill>
                                    </div>
                                    {activeFirewall === 'firewalld' && status?.firewalld?.default_zone && (
                                        <div className="sk-info-row">
                                            <span className="k">Default zone</span>
                                            <span className="v">{status.firewalld.default_zone}</span>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}

                    {activeSubTab === 'rules' && (
                        <>
                            {/* The view name IS this section's heading — the old
                                "Firewall Rules" <h3> would title the same table
                                twice, and the segment above already says Rules. */}
                            <GridViewPicker
                                views={chrome.views}
                                label="rules"
                                total={`${shownRules.length} of ${rules.length} rules`}
                                onCreate={chrome.createView}
                            />
                            <ListToolbar
                                tools={(
                                    <>
                                        <GridFilterButton
                                            count={chrome.filterCount}
                                            onClick={() => chrome.setDrawerOpen(true)}
                                        />
                                        <GridToolsMenu {...chrome.toolsProps} onRefresh={loadData} />
                                    </>
                                )}
                            >
                                <Button variant="default" size="sm" onClick={() => setShowPortModal(true)}>Add Rule</Button>
                            </ListToolbar>

                            <GridChips {...chrome.chipProps} />

                            {rules.length === 0 ? (
                                <div className="card">
                                    <p className="text-muted">No rules configured</p>
                                </div>
                            ) : (
                                <div className="card sec-flush">
                                    <DataTable
                                        columns={chrome.columns}
                                        data={rules}
                                        keyField={(rule) => `${rule.type}-${rule.service || rule.port || rule.rule}-${rule.protocol || ''}`}
                                        sorts={sorts}
                                        onSortsChange={setSorts}
                                        {...chrome.tableProps}
                                        footer={(
                                            <DataTableFooter
                                                shown={shownRules.length}
                                                total={rules.length}
                                                noun="rule"
                                            />
                                        )}
                                    />
                                </div>
                            )}
                        </>
                    )}

                    {activeSubTab === 'blocked' && (
                        <div className="card sec-flush">
                            <div className="card-header">
                                <h3>Blocked IP Addresses</h3>
                                <Button variant="default" size="sm" onClick={() => setShowBlockIPModal(true)}>Block IP</Button>
                            </div>
                            {blockedIPs.length === 0 ? (
                                <div className="card-body">
                                    <EmptyState icon={Ban} title="No blocked IPs" />
                                </div>
                            ) : (
                                <div className="blocked-list">
                                    {blockedIPs.map((item, index) => (
                                        <div key={index} className="blocked-item">
                                            <div className="blocked-info">
                                                <span className="blocked-ip">{item.ip}</span>
                                            </div>
                                            <Button variant="secondary" size="sm" onClick={() => handleUnblockIP(item.ip)}>
                                                Unblock
                                            </Button>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {activeSubTab === 'quick' && (
                        <div className="card">
                            <div className="card-header">
                                <h3>Quick Port Access</h3>
                            </div>
                            <div className="card-body">
                                <p className="sec-hint sec-hint--lead">One-click enable/disable common service ports</p>
                                <div className="quick-ports-grid">
                                    {commonPorts.map(({ port, name, protocol }) => {
                                        const isAllowed = rules.some(r =>
                                            (r.port === String(port) || r.port === port) && r.protocol === protocol
                                        );
                                        return (
                                            <div key={port} className={`quick-port-card ${isAllowed ? 'is-allowed' : ''}`}>
                                                <div className="port-info">
                                                    <span className="port-name">{name}</span>
                                                    <span className="port-number">{port}/{protocol}</span>
                                                </div>
                                                {isAllowed ? (
                                                    <Button variant="destructive" size="sm" onClick={() => handleRemovePort(port, protocol)} disabled={actionLoading}>
                                                        Block
                                                    </Button>
                                                ) : (
                                                    <Button variant="default" size="sm" onClick={() => handleQuickAllowPort(port, protocol)} disabled={actionLoading}>
                                                        Allow
                                                    </Button>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        </div>
                    )}
                </>
            )}

            {guard && (
                <div className="card">
                    <div className="card-header">
                        <h3>Cloud Metadata Guard</h3>
                        {guard.supported ? (
                            <Pill kind={guard.active ? 'green' : 'gray'}>
                                {guard.active ? 'Active' : 'Inactive'}
                            </Pill>
                        ) : (
                            <Pill kind="gray">Unsupported on this host</Pill>
                        )}
                    </div>
                    <div className="card-body">
                        <div className="sec-rows">
                            <div className="sk-info-row">
                                <span className="k">Block container access to 169.254.169.254</span>
                                <Switch
                                    checked={!!guard.enabled_setting}
                                    onCheckedChange={handleGuardToggle}
                                    disabled={guardLoading || !guard.supported}
                                    aria-label="Toggle cloud metadata guard"
                                />
                            </div>
                            {guard.supported && guard.backend && (
                                <div className="sk-info-row">
                                    <span className="k">Backend</span>
                                    <span className="v">{guard.backend}</span>
                                </div>
                            )}
                        </div>
                        <p className="sec-hint">
                            Stops app containers from reaching the cloud metadata endpoint,
                            preventing SSRF attacks from stealing instance credentials.
                        </p>
                    </div>
                </div>
            )}

            <GridFilterDrawer {...chrome.drawerProps} />

            {/* Block IP Modal */}
            <Modal open={showBlockIPModal} onClose={() => setShowBlockIPModal(false)} title="Block IP Address">
                <div className="form-group">
                    <Label>IP Address</Label>
                    <Input
                        type="text"
                        value={blockIP}
                        onChange={(e) => setBlockIP(e.target.value)}
                        placeholder="192.168.1.100 or 10.0.0.0/24"
                    />
                </div>
                <p className="text-muted">You can block a single IP or a range using CIDR notation.</p>
                <div className="modal-footer">
                    <Button variant="outline" onClick={() => setShowBlockIPModal(false)}>Cancel</Button>
                    <Button variant="destructive" onClick={handleBlockIP} disabled={actionLoading || !blockIP.trim()}>
                        {actionLoading ? 'Blocking...' : 'Block IP'}
                    </Button>
                </div>
            </Modal>

            {/* Allow Port Modal */}
            <Modal open={showPortModal} onClose={() => setShowPortModal(false)} title="Allow Port">
                <div className="form-row">
                    <div className="form-group">
                        <Label>Port Number</Label>
                        <Input
                            type="number"
                            value={newPort.port}
                            onChange={(e) => setNewPort({ ...newPort, port: e.target.value })}
                            placeholder="8080"
                            min="1"
                            max="65535"
                        />
                    </div>
                    <div className="form-group">
                        <Label>Protocol</Label>
                        <Select value={newPort.protocol} onValueChange={(value) => setNewPort({ ...newPort, protocol: value })}>
                            <SelectTrigger>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="tcp">TCP</SelectItem>
                                <SelectItem value="udp">UDP</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                </div>
                <div className="modal-footer">
                    <Button variant="outline" onClick={() => setShowPortModal(false)}>Cancel</Button>
                    <Button variant="default" onClick={handleAllowPort} disabled={actionLoading || !newPort.port}>
                        {actionLoading ? 'Adding...' : 'Allow Port'}
                    </Button>
                </div>
            </Modal>

            {/* Install Firewall Modal */}
            <Modal open={showInstallModal} onClose={() => setShowInstallModal(false)} title="Install Firewall">
                <div className="form-group">
                    <Label>Select Firewall</Label>
                    <Select value={selectedFirewall} onValueChange={setSelectedFirewall}>
                        <SelectTrigger>
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="ufw">UFW (Recommended for Ubuntu)</SelectItem>
                            <SelectItem value="firewalld">firewalld (CentOS/RHEL)</SelectItem>
                        </SelectContent>
                    </Select>
                </div>
                <div className="install-info">
                    {selectedFirewall === 'ufw' ? (
                        <p><strong>UFW (Uncomplicated Firewall)</strong> is simple and easy to use for Ubuntu/Debian systems.</p>
                    ) : (
                        <p><strong>firewalld</strong> is a dynamically managed firewall with zone-based configuration for CentOS/RHEL.</p>
                    )}
                </div>
                <div className="modal-footer">
                    <Button variant="outline" onClick={() => setShowInstallModal(false)}>Cancel</Button>
                    <Button variant="default" onClick={handleInstall} disabled={actionLoading}>
                        {actionLoading ? 'Installing...' : 'Install'}
                    </Button>
                </div>
            </Modal>
        </div>
    );
};

export default FirewallTab;
