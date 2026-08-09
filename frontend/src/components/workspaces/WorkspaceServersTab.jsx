import { useNavigate } from 'react-router-dom';
import { Server, Plus } from 'lucide-react';
import { ServiceTile, Pill, DataTable, DataTableFooter } from '@/components/ds';
import { Button } from '@/components/ui/button';
import EmptyState from '../EmptyState';

const SERVER_PILL = { online: 'green', pending: 'amber', offline: 'red' };

const WorkspaceServersTab = ({ wsId, srvIn, srvOut, onMoveServer }) => {
    const navigate = useNavigate();

    // DataTable columns. Cell markup and classNames are identical to the
    // hand-rolled table they replace, so _workspaces.scss keeps applying
    // (.sk-cell-name, .sk-cell-sub, .ws-detail__rowactions).
    const columns = [
        {
            key: 'name',
            header: 'Server',
            sortable: true,
            hideable: false,
            sortValue: (s) => s.name || '',
            render: (s) => (
                <div className="sk-cell-name">
                    <ServiceTile name={s.name} size={30} />
                    <div>
                        <div>{s.name}</div>
                        <div className="sk-cell-sub">{s.ip_address || s.hostname || ''}</div>
                    </div>
                </div>
            ),
        },
        {
            key: 'status',
            header: 'Status',
            sortable: true,
            sortValue: (s) => s.status || 'unknown',
            render: (s) => <Pill kind={SERVER_PILL[s.status] || 'gray'}>{s.status || 'unknown'}</Pill>,
        },
        {
            key: 'actions',
            header: '',
            width: 160,
            sortable: false,
            hideable: false,
            render: (s) => (
                <div className="ws-detail__rowactions" onClick={e => e.stopPropagation()}>
                    <Button size="sm" variant="destructive" onClick={() => onMoveServer(s.id, null)}>Remove</Button>
                </div>
            ),
        },
    ];

    return (
        <>
            {srvIn.length === 0 ? (
                <EmptyState icon={Server} title="No servers in this workspace yet" description="Move one in below." />
            ) : (
                <DataTable
                    columns={columns}
                    data={srvIn}
                    keyField="id"
                    storageKey="serverkit-table-ws-servers"
                    onRowClick={(s) => navigate(`/servers/${s.id}`)}
                    className="ws-detail__tablecard"
                    footer={<DataTableFooter shown={srvIn.length} total={srvIn.length} noun="server" />}
                />
            )}
            {srvOut.length > 0 && (
                <>
                    <div className="ws-pick-label">Move a server into this workspace</div>
                    <div className="ws-pick">
                        {srvOut.map(s => (
                            <div key={s.id} className="ws-pick__item" onClick={() => onMoveServer(s.id, wsId)}>
                                <ServiceTile name={s.name} size={28} className="ws-pick__tile" />
                                <span className="ws-pick__name">{s.name}</span>
                                {s.ip_address && <span className="sk-tag">{s.ip_address}</span>}
                                <Plus size={16} className="ws-pick__plus" />
                            </div>
                        ))}
                    </div>
                </>
            )}
        </>
    );
};

export default WorkspaceServersTab;
