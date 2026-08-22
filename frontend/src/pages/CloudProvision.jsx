import { useState, useEffect, useCallback } from 'react';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import { useAuth } from '../contexts/AuthContext';
import PageLoader from '../components/PageLoader';
import ConfirmDialog from '../components/ConfirmDialog';
import EmptyState from '../components/EmptyState';
import Modal from '@/components/Modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Cloud, Server } from 'lucide-react';
import { useTranslation } from 'react-i18next';

const CloudProvision = () => {
    const { t } = useTranslation();
    const toast = useToast();
    const { user } = useAuth();
    const [providers, setProviders] = useState([]);
    const [servers, setServers] = useState([]);
    const [costs, setCosts] = useState(null);
    const [loading, setLoading] = useState(true);
    const [showCreateProvider, setShowCreateProvider] = useState(false);
    const [showCreateServer, setShowCreateServer] = useState(false);
    const [providerOptions, setProviderOptions] = useState(null);
    const [deleteConfirm, setDeleteConfirm] = useState(null);

    const [providerForm, setProviderForm] = useState({ name: '', provider_type: 'digitalocean', api_key: '' });
    const [serverForm, setServerForm] = useState({ name: '', provider_id: '', region: '', size: '', image: '', install_agent: true });

    const loadData = useCallback(async () => {
        try {
            const [pData, sData, cData] = await Promise.all([
                api.getCloudProviders(),
                api.getCloudServers(),
                api.getCloudCosts(),
            ]);
            setProviders(pData.providers || []);
            setServers(sData.servers || []);
            setCosts(cData);
        } catch (err) {
            toast.error(t('app.cloudProvision.failedToLoadCloudData', 'Failed to load cloud data'));
        } finally {
            setLoading(false);
        }
    }, [toast]);

    useEffect(() => { loadData(); }, [loadData]);

    // Publish the admin actions to the shared tab-group top bar.
    useTopbarActions(() =>
        user?.is_admin ? (
            <>
                <Button size="sm" variant="outline" onClick={() => setShowCreateProvider(true)}>{t('app.cloudProvision.addProvider', 'Add Provider')}</Button>
                <Button size="sm" onClick={() => setShowCreateServer(true)}>{t('app.cloudProvision.newServer', 'New Server')}</Button>
            </>
        ) : null,
        [user?.is_admin]
    );

    const handleCreateProvider = async () => {
        try {
            await api.createCloudProvider(providerForm);
            toast.success(t('app.cloudProvision.providerAdded', 'Provider added'));
            setShowCreateProvider(false);
            loadData();
        } catch (err) { toast.error(err.message); }
    };

    const loadProviderOptions = async (type) => {
        try {
            const data = await api.getCloudProviderOptions(type);
            setProviderOptions(data);
        } catch (err) { toast.error(err.message); }
    };

    const handleCreateServer = async () => {
        try {
            await api.createCloudServer(serverForm);
            toast.success(t('app.cloudProvision.serverProvisioningInitiated', 'Server provisioning initiated'));
            setShowCreateServer(false);
            loadData();
        } catch (err) { toast.error(err.message); }
    };

    const handleDestroy = async (id) => {
        try {
            await api.destroyCloudServer(id);
            toast.success(t('app.cloudProvision.serverDestroyed', 'Server destroyed'));
            setDeleteConfirm(null);
            loadData();
        } catch (err) { toast.error(err.message); }
    };

    const providerTypes = {
        digitalocean: 'DigitalOcean', hetzner: 'Hetzner Cloud', vultr: 'Vultr', linode: 'Linode'
    };

    const serverStatusVariant = (status) => {
        if (status === 'active') return 'success';
        if (status === 'error') return 'destructive';
        return 'warning';
    };

    if (loading) return <PageLoader />;

    return (
        <div className="sk-tabgroup__inner cloud-provision-page">
            <Tabs defaultValue="servers">
                <TabsList>
                    <TabsTrigger value="servers">{t('common.labels.servers', 'Servers')}</TabsTrigger>
                    <TabsTrigger value="providers">{t('app.cloudProvision.providers', 'Providers')}</TabsTrigger>
                    <TabsTrigger value="costs">{t('app.cloudProvision.costs', 'Costs')}</TabsTrigger>
                </TabsList>

                <TabsContent value="servers">
                    <div className="cloud-servers-grid">
                        {servers.map(srv => (
                            <div key={srv.id} className="cloud-server-card card">
                                <div className="cloud-server-card__header">
                                    <h3>{srv.name}</h3>
                                    <Badge variant={serverStatusVariant(srv.status)}>{srv.status}</Badge>
                                </div>
                                <div className="cloud-server-card__meta">
                                    <span>{srv.provider_name}</span>
                                    <span>{srv.region}</span>
                                    <span>{srv.size}</span>
                                </div>
                                {srv.ip_address && <div className="text-mono">{srv.ip_address}</div>}
                                <div className="cloud-server-card__cost">
                                    ${srv.monthly_cost}/mo
                                </div>
                                <div className="cloud-server-card__actions">
                                    {srv.agent_installed && <Badge variant="success">{t('app.cloudProvision.agentInstalled', 'Agent Installed')}</Badge>}
                                    {user?.is_admin && srv.status === 'active' && (
                                        <Button size="sm" variant="destructive" onClick={() => setDeleteConfirm(srv)}>{t('app.cloudProvision.destroy', 'Destroy')}</Button>
                                    )}
                                </div>
                            </div>
                        ))}
                        {servers.length === 0 && (
                            <EmptyState
                                size="lg"
                                icon={Server}
                                title={t('app.cloudProvision.noCloudServersYet', 'No cloud servers yet')}
                                description={user?.is_admin ? t('app.cloudProvision.addAProviderThenCreateA', 'Add a provider, then create a server.') : t('app.cloudProvision.noServersHaveBeenProvisioned', 'No servers have been provisioned.')}
                                action={user?.is_admin && <Button onClick={() => setShowCreateServer(true)}>{t('app.cloudProvision.newServer', 'New Server')}</Button>}
                            />
                        )}
                    </div>
                </TabsContent>

                <TabsContent value="providers">
                    <div className="providers-list">
                        {providers.map(p => (
                            <div key={p.id} className="provider-row card">
                                <strong>{p.name}</strong>
                                <Badge variant="outline">{providerTypes[p.provider_type] || p.provider_type}</Badge>
                                <span>{p.server_count} servers</span>
                            </div>
                        ))}
                        {providers.length === 0 && (
                            <EmptyState
                                size="lg"
                                icon={Cloud}
                                title={t('app.cloudProvision.noProvidersConfigured', 'No providers configured')}
                                description={user?.is_admin ? t('app.cloudProvision.addACloudProviderToProvision', 'Add a cloud provider to provision servers.') : t('app.cloudProvision.noProvidersHaveBeenAdded', 'No providers have been added.')}
                                action={user?.is_admin && <Button variant="outline" onClick={() => setShowCreateProvider(true)}>{t('app.cloudProvision.addProvider', 'Add Provider')}</Button>}
                            />
                        )}
                    </div>
                </TabsContent>

                <TabsContent value="costs">
                    {costs && (
                        <div className="costs-panel card">
                            <h3>{t('app.cloudProvision.monthlyCostSummary', 'Monthly Cost Summary')}</h3>
                            <div className="cost-total">${costs.total_monthly}/mo across {costs.server_count} servers</div>
                            <div className="cost-breakdown">
                                {Object.entries(costs.by_provider || {}).map(([name, data]) => (
                                    <div key={name} className="cost-row">
                                        <span>{name}</span>
                                        <span>{data.count} servers</span>
                                        <span>${data.cost.toFixed(2)}/mo</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </TabsContent>
            </Tabs>

            <Modal
                open={showCreateProvider}
                onClose={() => setShowCreateProvider(false)}
                title={t('app.cloudProvision.addCloudProvider', 'Add Cloud Provider')}
                footer={(
                    <>
                        <Button variant="outline" onClick={() => setShowCreateProvider(false)}>{t('common.actions.cancel', 'Cancel')}</Button>
                        <Button onClick={handleCreateProvider}>{t('common.actions.add', 'Add')}</Button>
                    </>
                )}
            >
                <div className="form-group"><label>{t('app.cloudProvision.provider', 'Provider')}</label><select className="form-select" value={providerForm.provider_type} onChange={e => setProviderForm({...providerForm, provider_type: e.target.value})}>{Object.entries(providerTypes).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></div>
                <div className="form-group"><label>{t('common.labels.name', 'Name')}</label><Input value={providerForm.name} onChange={e => setProviderForm({...providerForm, name: e.target.value})} /></div>
                <div className="form-group"><label>{t('app.cloudProvision.apiKey', 'API Key')}</label><Input type="password" value={providerForm.api_key} onChange={e => setProviderForm({...providerForm, api_key: e.target.value})} /></div>
            </Modal>

            <Modal
                open={showCreateServer}
                onClose={() => setShowCreateServer(false)}
                title={t('app.cloudProvision.newCloudServer', 'New Cloud Server')}
                footer={(
                    <>
                        <Button variant="outline" onClick={() => setShowCreateServer(false)}>{t('common.actions.cancel', 'Cancel')}</Button>
                        <Button onClick={handleCreateServer} disabled={!serverForm.name || !serverForm.provider_id}>{t('common.actions.create', 'Create')}</Button>
                    </>
                )}
            >
                <div className="form-group"><label>{t('app.cloudProvision.provider', 'Provider')}</label><select className="form-select" value={serverForm.provider_id} onChange={e => { setServerForm({...serverForm, provider_id: parseInt(e.target.value)}); const p = providers.find(x => x.id === parseInt(e.target.value)); if (p) loadProviderOptions(p.provider_type); }}><option value="">{t('app.cloudProvision.selectProvider', 'Select provider')}</option>{providers.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
                <div className="form-group"><label>{t('app.cloudProvision.serverName', 'Server Name')}</label><Input value={serverForm.name} onChange={e => setServerForm({...serverForm, name: e.target.value})} /></div>
                {providerOptions && (
                    <>
                        <div className="form-group"><label>{t('app.cloudProvision.region', 'Region')}</label><select className="form-select" value={serverForm.region} onChange={e => setServerForm({...serverForm, region: e.target.value})}><option value="">{t('app.cloudProvision.selectRegion', 'Select region')}</option>{(providerOptions.regions || []).map(r => <option key={r} value={r}>{r}</option>)}</select></div>
                        <div className="form-group"><label>{t('common.labels.size', 'Size')}</label><select className="form-select" value={serverForm.size} onChange={e => setServerForm({...serverForm, size: e.target.value})}><option value="">{t('app.cloudProvision.selectSize', 'Select size')}</option>{(providerOptions.sizes || []).map(s => <option key={s} value={s}>{s}</option>)}</select></div>
                        <div className="form-group"><label>{t('app.cloudProvision.image', 'Image')}</label><select className="form-select" value={serverForm.image} onChange={e => setServerForm({...serverForm, image: e.target.value})}><option value="">{t('app.cloudProvision.selectImage', 'Select image')}</option>{(providerOptions.images || []).map(i => <option key={i} value={i}>{i}</option>)}</select></div>
                    </>
                )}
                <div className="form-group"><label className="checkbox-label"><input type="checkbox" checked={serverForm.install_agent} onChange={e => setServerForm({...serverForm, install_agent: e.target.checked})} /> {t('app.cloudProvision.autoInstallServerkitAgent', 'Auto-install ServerKit agent')}</label></div>
            </Modal>

            {deleteConfirm && (
                <ConfirmDialog title={t('app.cloudProvision.destroyServer', 'Destroy Server')} message={t('app.cloudProvision.destroyThisActionIsIrreversible', 'Destroy "{{name}}"? This action is irreversible.', { name: deleteConfirm.name })} onConfirm={() => handleDestroy(deleteConfirm.id)} onCancel={() => setDeleteConfirm(null)} variant="danger" />
            )}
        </div>
    );
};

export default CloudProvision;
