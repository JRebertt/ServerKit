import { useState, useEffect } from 'react';
import { Ban } from 'lucide-react';
import api from '../../services/api';
import ConfirmDialog from '../ConfirmDialog';
import { useToast } from '../../contexts/ToastContext';
import Modal from '../Modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ColumnsMenu, DataTable, DataTableFooter, Pill, SortMenu } from '@/components/ds';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue } from '@/components/ui/select';

const Fail2banTab = () => {
    const [status, setStatus] = useState(null);
    const [bans, setBans] = useState([]);
    const [jailStats, setJailStats] = useState({});
    const [loading, setLoading] = useState(true);
    const [actionLoading, setActionLoading] = useState(false);
    const [showBanModal, setShowBanModal] = useState(false);
    const [banIP, setBanIP] = useState('');
    const [banJail, setBanJail] = useState('sshd');
    const [confirmDialog, setConfirmDialog] = useState(null);
    const toast = useToast();
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-fail2ban-bans-sort' });
    const {
        hiddenKeys, toggleColumn, showAllColumns,
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
            toast.success('Fail2ban installed successfully');
            await loadData();
        } catch (error) {
            toast.error(`Failed to install: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleBan = async () => {
        if (!banIP.trim()) return;
        setActionLoading(true);
        try {
            await api.fail2banBan(banIP, banJail);
            toast.success(`IP ${banIP} banned in ${banJail}`);
            setShowBanModal(false);
            setBanIP('');
            await loadData();
        } catch (error) {
            toast.error(`Failed to ban IP: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleUnban = async (ip, jail) => {
        setConfirmDialog({
            title: 'Unban IP',
            message: `Are you sure you want to unban ${ip} from ${jail}?`,
            confirmText: 'Unban',
            variant: 'warning',
            onConfirm: async () => {
                try {
                    await api.fail2banUnban(ip, jail);
                    toast.success(`IP ${ip} unbanned`);
                    await loadData();
                } catch (error) {
                    toast.error(`Failed to unban: ${error.message}`);
                }
                setConfirmDialog(null);
            },
            onCancel: () => setConfirmDialog(null)
        });
    };

    if (loading) {
        return <div className="loading-sm">Loading Fail2ban status...</div>;
    }

    // Cell markup/classNames identical to the hand-rolled table they replace.
    const banColumns = [
        {
            key: 'ip',
            header: 'IP Address',
            sortable: true,
            hideable: false,
            sortValue: (ban) => ban.ip || '',
            cellClassName: 'sk-cell-mono sec-ip--red',
            render: (ban) => ban.ip,
        },
        {
            key: 'jail',
            header: 'Jail',
            sortable: true,
            sortValue: (ban) => ban.jail || '',
            render: (ban) => <span className="sk-tag">{ban.jail}</span>,
        },
        {
            key: 'actions',
            header: 'Actions',
            sortable: false,
            hideable: false,
            render: (ban) => (
                <Button variant="secondary" size="sm" onClick={() => handleUnban(ban.ip, ban.jail)}>
                    Unban
                </Button>
            ),
        },
    ];

    return (
        <div className="fail2ban-tab">
            {!status?.installed ? (
                <div className="empty-state">
                    <svg viewBox="0 0 24 24" width="48" height="48" stroke="currentColor" fill="none" strokeWidth="1">
                        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                    </svg>
                    <h3>Fail2ban Not Installed</h3>
                    <p>Install Fail2ban to protect against brute force attacks.</p>
                    <Button variant="default" onClick={handleInstall} disabled={actionLoading}>
                        {actionLoading ? 'Installing...' : 'Install Fail2ban'}
                    </Button>
                </div>
            ) : (
                <>
                    <div className="card">
                        <div className="card-header">
                            <h3>Fail2ban Status</h3>
                            <div className="card-actions">
                                <Button variant="default" size="sm" onClick={() => setShowBanModal(true)}>
                                    Ban IP
                                </Button>
                                <Button variant="outline" size="sm" onClick={loadData}>
                                    Refresh
                                </Button>
                            </div>
                        </div>
                        <div className="card-body">
                            <div className="sec-rows">
                                <div className="sk-info-row">
                                    <span className="k">Service</span>
                                    <Pill kind={status.service_running ? 'green' : 'red'}>
                                        {status.service_running ? 'Running' : 'Stopped'}
                                    </Pill>
                                </div>
                                <div className="sk-info-row">
                                    <span className="k">Version</span>
                                    <span className="v">{status.version || 'Unknown'}</span>
                                </div>
                                <div className="sk-info-row">
                                    <span className="k">Active jails</span>
                                    {status.jails?.length > 0 ? (
                                        <span className="sec-chiprow">
                                            {status.jails.map((jail) => (
                                                <span key={jail} className="sk-tag">{jail}</span>
                                            ))}
                                        </span>
                                    ) : (
                                        <span className="v">None</span>
                                    )}
                                </div>
                                <div className="sk-info-row">
                                    <span className="k">Total banned IPs</span>
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
                                                <div className="f2b-jail__l">Banned</div>
                                            </div>
                                            <div className="f2b-jail__stat">
                                                <div className="f2b-jail__v">{s.currently_failed ?? '—'}</div>
                                                <div className="f2b-jail__l">Failed</div>
                                            </div>
                                            <div className="f2b-jail__stat">
                                                <div className="f2b-jail__v">{s.total_banned ?? '—'}</div>
                                                <div className="f2b-jail__l">Total banned</div>
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}

                    <div className="card sec-flush">
                        <div className="card-header">
                            <h3>Banned IPs {bans.length > 0 && <span className="sec-count">· {bans.length}</span>}</h3>
                            <div className="sec-tableactions">
                                <SortMenu columns={banColumns} sorts={sorts} onChange={setSorts} />
                                <ColumnsMenu
                                    columns={banColumns}
                                    hiddenKeys={hiddenKeys}
                                    onToggle={toggleColumn}
                                    onShowAll={showAllColumns}
                                />
                            </div>
                        </div>
                        {bans.length === 0 ? (
                            <div className="card-body">
                                <p className="text-muted">No IPs are currently banned.</p>
                            </div>
                        ) : (
                            <DataTable
                                columns={banColumns}
                                data={bans}
                                keyField={(ban) => `${ban.ip}-${ban.jail}`}
                                sorts={sorts}
                                onSortsChange={setSorts}
                                hiddenKeys={hiddenKeys}
                                footer={(
                                    <DataTableFooter
                                        shown={bans.length}
                                        total={bans.length}
                                        noun="banned IP"
                                    />
                                )}
                            />
                        )}
                    </div>
                </>
            )}

            <Modal open={showBanModal} onClose={() => setShowBanModal(false)} title="Ban IP Address">
                <div className="form-group">
                    <Label>IP Address</Label>
                    <Input
                        type="text"
                        value={banIP}
                        onChange={(e) => setBanIP(e.target.value)}
                        placeholder="192.168.1.100"
                    />
                </div>
                <div className="form-group">
                    <Label>Jail</Label>
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
                    <Button variant="outline" onClick={() => setShowBanModal(false)}>Cancel</Button>
                    <Button variant="destructive" onClick={handleBan} disabled={actionLoading || !banIP.trim()}>
                        {actionLoading ? 'Banning...' : 'Ban IP'}
                    </Button>
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
        </div>
    );
};

export default Fail2banTab;
