import { KpiBand, MetricCard } from '@/components/ds';
import { Server, Boxes, Globe, Users } from 'lucide-react';
import { useTranslation } from 'react-i18next';

const WorkspaceOverviewTab = ({ ws, since, members, srvIn, services, sites }) => {
    const { t } = useTranslation();
    return (
        <div className="ws-detail__grid">
            <section className="ws-detail__card">
                <h3>{t('app.workspaceOverviewTab.workspace', 'Workspace')}</h3>
                <div className="sk-info-row"><span className="k">{t('app.workspaceOverviewTab.slug', 'Slug')}</span><span className="v">/{ws.slug}</span></div>
                <div className="sk-info-row"><span className="k">{t('app.workspaceOverviewTab.created', 'Created')}</span><span className="v">{since || '—'}</span></div>
                <div className="sk-info-row"><span className="k">{t('app.workspaceOverviewTab.maxServers', 'Max servers')}</span><span className="v">{ws.max_servers > 0 ? ws.max_servers : 'Unlimited'}</span></div>
                <div className="sk-info-row"><span className="k">{t('app.workspaceOverviewTab.maxUsers', 'Max users')}</span><span className="v">{ws.max_users > 0 ? ws.max_users : 'Unlimited'}</span></div>
            </section>
            <section className="ws-detail__card">
                <h3>{t('app.workspaceOverviewTab.resources', 'Resources')}</h3>
                <KpiBand>
                    <MetricCard icon={<Server size={16} />} tone="accent" value={srvIn.length} label={t('app.workspaceOverviewTab.servers', 'Servers')} />
                    <MetricCard icon={<Boxes size={16} />} tone="accent" value={services.length} label={t('app.workspaceOverviewTab.services', 'Services')} />
                    <MetricCard icon={<Globe size={16} />} tone="accent" value={sites.length} label={t('app.workspaceOverviewTab.sites', 'Sites')} />
                    <MetricCard icon={<Users size={16} />} tone="accent" value={members.length} label={t('app.workspaceOverviewTab.members', 'Members')} />
                </KpiBand>
            </section>
        </div>
    );
};

export default WorkspaceOverviewTab;
