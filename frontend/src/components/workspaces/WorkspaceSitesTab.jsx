import { useNavigate } from 'react-router-dom';
import { Globe, Plus } from 'lucide-react';
import { ServiceTile, Pill, DataTable, DataTableFooter } from '@/components/ds';
import { Button } from '@/components/ui/button';
import EmptyState from '../EmptyState';

const APP_PILL = { running: 'green', stopped: 'gray', failed: 'red' };

const WorkspaceSitesTab = ({ wsId, sites, appsOut, onMoveApp, onShare }) => {
    const navigate = useNavigate();

    // DataTable columns. Cell markup and classNames are identical to the
    // hand-rolled table they replace, so _workspaces.scss keeps applying
    // (.sk-cell-name, .sk-cell-sub, .ws-detail__rowactions).
    const columns = [
        {
            key: 'name',
            header: 'Site',
            sortable: true,
            hideable: false,
            sortValue: (a) => a.name || '',
            render: (a) => (
                <div className="sk-cell-name">
                    <ServiceTile name={a.name} size={30} />
                    <div>
                        <div>{a.name}</div>
                        <div className="sk-cell-sub">{a.app_type}{a.domain ? ` · ${a.domain}` : ''}</div>
                    </div>
                </div>
            ),
        },
        {
            key: 'status',
            header: 'Status',
            sortable: true,
            sortValue: (a) => a.status || 'unknown',
            render: (a) => <Pill kind={APP_PILL[a.status] || 'amber'}>{a.status || 'unknown'}</Pill>,
        },
        {
            key: 'actions',
            header: '',
            width: 220,
            sortable: false,
            hideable: false,
            render: (a) => (
                <div className="ws-detail__rowactions" onClick={e => e.stopPropagation()}>
                    <Button size="sm" variant="outline" onClick={() => onShare(a)}>Share</Button>
                    <Button size="sm" variant="destructive" onClick={() => onMoveApp(a.id, null)}>Remove</Button>
                </div>
            ),
        },
    ];

    return (
        <>
            {sites.length === 0 ? (
                <EmptyState icon={Globe} title="No sites in this workspace yet" description="Move one in below." />
            ) : (
                <DataTable
                    columns={columns}
                    data={sites}
                    keyField="id"
                    storageKey="serverkit-table-ws-sites"
                    onRowClick={(a) => navigate(`/services/${a.id}`)}
                    className="ws-detail__tablecard"
                    footer={<DataTableFooter shown={sites.length} total={sites.length} noun="site" />}
                />
            )}
            {appsOut.length > 0 && (
                <>
                    <div className="ws-pick-label">Move a site into this workspace</div>
                    <div className="ws-pick">
                        {appsOut.map(a => (
                            <div key={a.id} className="ws-pick__item" onClick={() => onMoveApp(a.id, wsId)}>
                                <ServiceTile name={a.name} size={28} className="ws-pick__tile" />
                                <span className="ws-pick__name">{a.name}</span>
                                <span className="sk-tag">{a.app_type}</span>
                                <Plus size={16} className="ws-pick__plus" />
                            </div>
                        ))}
                    </div>
                </>
            )}
        </>
    );
};

export default WorkspaceSitesTab;
