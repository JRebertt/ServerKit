import { useState, useEffect, useMemo } from 'react';
import { Ban, Shield } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { useConfirm } from '@/hooks/useConfirm';
import EmptyState from '@/components/EmptyState';
import Modal from '../Modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { DataTable, DataTableFooter, Pill } from '@/components/ds';
import {
    useTableChrome, GridViewPicker, GridChips, GridFilterButton,
    GridToolsMenu, GridFilterDrawer, applyFilters,
} from '@/components/ds/grid';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue } from '@/components/ui/select';
import { useTranslation } from 'react-i18next';

// Fail2ban's own default jail name since 0.9, and the one this tab's Ban modal
// pre-selects — so it is the value a preset can actually count on being there.
const SSH_JAIL = 'sshd';

// Built-in saved views. A ban row is only { ip, jail }, so the jail is the one
// axis worth slicing: SSH is where the internet-wide noise lands, and everything
// else is a jail someone configured on purpose and should be reading.
const FAIL2BAN_VIEWS = [
    {
        // The drive-by traffic. Usually the longest list on the page and the
        // one you scan for a source you recognise rather than act on row by row.
        name: 'SSH bans',
        state: {
            sorts: [{ key: 'ip', direction: 'asc' }],
            hiddenKeys: [],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'f2b1', field: 'jail', op: 'any', value: [SSH_JAIL] }],
            },
        },
    },
    {
        // Everything the SSH view buries: web-auth, WordPress and per-app jails.
        // A ban here means something reached an application, so it is the half
        // worth reading first. Jail before IP, so each jail stays together.
        name: 'App & web jail bans',
        state: {
            sorts: [{ key: 'jail', direction: 'asc' }, { key: 'ip', direction: 'asc' }],
            hiddenKeys: [],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'f2b2', field: 'jail', op: 'none', value: [SSH_JAIL] }],
            },
        },
    },
];

const Fail2banTab = () => {
    const { t } = useTranslation();
    const [status, setStatus] = useState(null);
    const [bans, setBans] = useState([]);
    const [jailStats, setJailStats] = useState({});
    const [loading, setLoading] = useState(true);
    const [actionLoading, setActionLoading] = useState(false);
    const [showBanModal, setShowBanModal] = useState(false);
    const [banIP, setBanIP] = useState('');
    const [banJail, setBanJail] = useState('sshd');
    const toast = useToast();
    const { confirm } = useConfirm();
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-fail2ban-bans-sort' });
    const {
        hiddenKeys, setHiddenKeys,
    } = useColumnVisibility({ storageKey: 'serverkit-table-fail2ban-bans-cols' });

    useEffect(() => {
        loadData();
    }, []);

    const loadData = async () => {
        setLoading(true);
        try {
            const [statusData, bansData] = await Promise.all([
                api.getFail2banStatus(),
                api.getAllFail2banBans().catch(() => ({ banned_ips: [] }))
            ]);
            setStatus(statusData);
            setBans(bansData.banned_ips || []);

            if (statusData?.installed && statusData.jails?.length) {
                const entries = await Promise.all(
                    statusData.jails.map(async (jail) => {
                        try {
                            return [jail, await api.getFail2banJailStatus(jail)];
                        } catch {
                            return [jail, null];
                        }
                    })
                );
                setJailStats(Object.fromEntries(entries));
            } else {
                setJailStats({});
            }
        } catch (error) {
            console.error('Failed to load Fail2ban data:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleInstall = async () => {
        setActionLoading(true);
        try {
            await api.installFail2ban();
            toast.success(t('app.fail2banTab.fail2banInstalledSuccessfully', 'Fail2ban installed successfully'));
            await loadData();
        } catch (error) {
            toast.error(t('app.fail2banTab.failedToInstall', 'Failed to install: {{message}}', { message: error.message }));
        } finally {
            setActionLoading(false);
        }
    };

    const handleBan = async () => {
        if (!banIP.trim()) return;
        setActionLoading(true);
        try {
            await api.fail2banBan(banIP, banJail);
            toast.success(t('app.fail2banTab.ipBannedIn', 'IP {{banIP}} banned in {{banJail}}', { banIP: banIP, banJail: banJail }));
            setShowBanModal(false);
            setBanIP('');
            await loadData();
        } catch (error) {
            toast.error(t('app.fail2banTab.failedToBanIp', 'Failed to ban IP: {{message}}', { message: error.message }));
        } finally {
            setActionLoading(false);
        }
    };

    const handleUnban = async (ip, jail) => {
        const confirmed = await confirm({
            title: t('app.fail2banTab.unbanIp', 'Unban IP'),
            message: t('app.fail2banTab.areYouSureYouWantTo', 'Are you sure you want to unban {{ip}} from {{jail}}?', { ip: ip, jail: jail }),
            confirmText: t('app.fail2banTab.unban', 'Unban'),
            variant: 'warning',
        });
        if (!confirmed) return;
        try {
            await api.fail2banUnban(ip, jail);
            toast.success(t('app.fail2banTab.ipUnbanned', 'IP {{ip}} unbanned', { ip: ip }));
            await loadData();
        } catch (error) {
            toast.error(t('app.fail2banTab.failedToUnban', 'Failed to unban: {{message}}', { message: error.message }));
        }
    };

    // Cell markup/classNames identical to the hand-rolled table they replace.
    // Declared above the loading guard now: the chrome below is a hook, so it
    // cannot sit behind an early return.
    const banColumns = [
        {
            key: 'ip',
            headerKey: 'common.labels.ipAddress', header: 'IP Address',
            sortable: true,
            hideable: false,
            sortValue: (ban) => ban.ip || '',
            cellClassName: 'sk-cell-mono sec-ip--red',
            render: (ban) => ban.ip,
        },
        {
            key: 'jail',
            headerKey: 'app.fail2banTab.jail', header: 'Jail',
            sortable: true,
            // Declared, not inferred: a host with two jails and two bans fails
            // the enum cardinality test and would fall back to text, which
            // turns the jail pick-list into a typed fragment and both views
            // above into no-ops. `value` is what the rules read.
            type: 'enum',
            value: (ban) => ban.jail || '',
            sortValue: (ban) => ban.jail || '',
            render: (ban) => <span className="sk-tag">{ban.jail}</span>,
        },
        {
            key: 'actions',
            headerKey: 'common.labels.actions', header: 'Actions',
            sortable: false,
            hideable: false,
            render: (ban) => (
                <Button variant="secondary" size="sm" onClick={() => handleUnban(ban.ip, ban.jail)}>
                    {t('app.fail2banTab.unban', 'Unban')}
                </Button>
            ),
        },
    ];

    // Scoped to this table, not to Security as a page: one tab is mounted at a
    // time, so a picker at the page heading would sit above whichever tab
    // happened to be open. No `urlScope` — the bans table is the only one on
    // this tab, so its links keep the plain ?view= names.
    const chrome = useTableChrome({
        columns: banColumns,
        rows: bans,
        viewPageKey: 'security-fail2ban',
        builtinViews: FAIL2BAN_VIEWS,
        noun: 'bans',
        sorts,
        setSorts,
        hiddenKeys,
        setHiddenKeys,
    });

    // DataTable applies the column rules itself, so the count has to be
    // re-derived here or a view that narrows to two rows still claims the total.
    const shownBans = useMemo(
        () => applyFilters(bans, chrome.cfg.filters, chrome.columns),
        [bans, chrome.cfg.filters, chrome.columns],
    );

    if (loading) {
        return <div className="loading-sm">{t('app.fail2banTab.loadingFail2banStatus', 'Loading Fail2ban status…')}</div>;
    }

    return (
        <div className="fail2ban-tab">
            {!status?.installed ? (
                <EmptyState
                    icon={Shield}
                    title={t('app.fail2banTab.fail2banNotInstalled', 'Fail2ban Not Installed')}
                    description={t('app.fail2banTab.installFail2banToProtectAgainstBrute', 'Install Fail2ban to protect against brute force attacks.')}
                    action={(
                        <Button variant="default" onClick={handleInstall} disabled={actionLoading}>
                            {actionLoading ? 'Installing...' : 'Install Fail2ban'}
                        </Button>
                    )}
                />
            ) : (
                <>
                    <div className="card">
                        <div className="card-header">
                            <h3>{t('app.fail2banTab.fail2banStatus', 'Fail2ban Status')}</h3>
                            <div className="card-actions">
                                <Button variant="default" size="sm" onClick={() => setShowBanModal(true)}>
                                    {t('app.fail2banTab.banIp', 'Ban IP')}
                                </Button>
                                <Button variant="outline" size="sm" onClick={loadData}>
                                    {t('common.actions.refresh', 'Refresh')}
                                </Button>
                            </div>
                        </div>
                        <div className="card-body">
                            <div className="sec-rows">
                                <div className="sk-info-row">
                                    <span className="k">{t('common.labels.service', 'Service')}</span>
                                    <Pill kind={status.service_running ? 'green' : 'red'}>
                                        {status.service_running ? 'Running' : 'Stopped'}
                                    </Pill>
                                </div>
                                <div className="sk-info-row">
                                    <span className="k">{t('common.labels.version', 'Version')}</span>
                                    <span className="v">{status.version || 'Unknown'}</span>
                                </div>
                                <div className="sk-info-row">
                                    <span className="k">{t('app.fail2banTab.activeJails', 'Active jails')}</span>
                                    {status.jails?.length > 0 ? (
                                        <span className="sec-chiprow">
                                            {status.jails.map((jail) => (
                                                <span key={jail} className="sk-tag">{jail}</span>
                                            ))}
                                        </span>
                                    ) : (
                                        <span className="v">{t('app.fail2banTab.none', 'None')}</span>
                                    )}
                                </div>
                                <div className="sk-info-row">
                                    <span className="k">{t('app.fail2banTab.totalBannedIps', 'Total banned IPs')}</span>
                                    <span className={`v ${bans.length > 0 ? 'sec-v-amber' : ''}`}>{bans.length}</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    {status.jails?.length > 0 && (
                        <div className="f2b-jails">
                            {status.jails.map((jail) => {
                                const s = jailStats[jail] || {};
                                return (
                                    <div className="f2b-jail" key={jail}>
                                        <div className="f2b-jail__name"><Ban size={15} />{jail}</div>
                                        <div className="f2b-jail__stats">
                                            <div className="f2b-jail__stat">
                                                <div className="f2b-jail__v f2b-jail__v--amber">{s.currently_banned ?? '—'}</div>
                                                <div className="f2b-jail__l">{t('app.fail2banTab.banned', 'Banned')}</div>
                                            </div>
                                            <div className="f2b-jail__stat">
                                                <div className="f2b-jail__v">{s.currently_failed ?? '—'}</div>
                                                <div className="f2b-jail__l">{t('common.state.failed', 'Failed')}</div>
                                            </div>
                                            <div className="f2b-jail__stat">
                                                <div className="f2b-jail__v">{s.total_banned ?? '—'}</div>
                                                <div className="f2b-jail__l">{t('app.fail2banTab.totalBanned', 'Total banned')}</div>
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}

                    {/* The view name replaces the old "Banned IPs" <h3>: it is
                        the same heading slot, and it now says WHICH bans you
                        are looking at rather than just that they are bans. */}
                    <GridViewPicker
                        views={chrome.views}
                        label="bans"
                        onCreate={chrome.createView}
                        actions={(
                            <>
                                <GridFilterButton
                                    count={chrome.filterCount}
                                    onClick={() => chrome.setDrawerOpen(true)}
                                />
                                <GridToolsMenu {...chrome.toolsProps} onRefresh={loadData} />
                            </>
                        )}
                    />

                    <GridChips {...chrome.chipProps} />

                    {bans.length === 0 ? (
                        <div className="card">
                            <p className="text-muted">{t('app.fail2banTab.noIpsAreCurrentlyBanned', 'No IPs are currently banned.')}</p>
                        </div>
                    ) : (
                        <div className="card sec-flush">
                            <DataTable
                                columns={chrome.columns}
                                data={bans}
                                keyField={(ban) => `${ban.ip}-${ban.jail}`}
                                sorts={sorts}
                                onSortsChange={setSorts}
                                {...chrome.tableProps}
                                footer={(
                                    <DataTableFooter
                                        shown={shownBans.length}
                                        total={bans.length}
                                        noun="banned IP"
                                    />
                                )}
                            />
                        </div>
                    )}
                </>
            )}

            <GridFilterDrawer {...chrome.drawerProps} />

            <Modal open={showBanModal} onClose={() => setShowBanModal(false)} title={t('app.fail2banTab.banIpAddress', 'Ban IP Address')}>
                <div className="form-group">
                    <Label>{t('common.labels.ipAddress', 'IP Address')}</Label>
                    <Input
                        type="text"
                        value={banIP}
                        onChange={(e) => setBanIP(e.target.value)}
                        placeholder="192.168.1.100"
                    />
                </div>
                <div className="form-group">
                    <Label>{t('app.fail2banTab.jail', 'Jail')}</Label>
                    <Select value={banJail} onValueChange={setBanJail}>
                        <SelectTrigger>
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {status?.jails?.map(jail => (
                                <SelectItem key={jail} value={jail}>{jail}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
                <div className="modal-footer">
                    <Button variant="outline" onClick={() => setShowBanModal(false)}>{t('common.actions.cancel', 'Cancel')}</Button>
                    <Button variant="destructive" onClick={handleBan} disabled={actionLoading || !banIP.trim()}>
                        {actionLoading ? 'Banning...' : 'Ban IP'}
                    </Button>
                </div>
            </Modal>
        </div>
    );
};

export default Fail2banTab;
