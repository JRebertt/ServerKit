import { Plus } from 'lucide-react';
import { ServiceTile, Pill, DataTable, DataTableFooter } from '@/components/ds';
import { Button } from '@/components/ui/button';

const WorkspaceMembersTab = ({ wsId, members, allUsers, onAddMember, onRemoveMember }) => {
    // DataTable columns. Cell markup and classNames are identical to the
    // hand-rolled table they replace, so _workspaces.scss keeps applying
    // (.sk-cell-name, .sk-cell-sub, .ws-row__av).
    const columns = [
        {
            key: 'name',
            header: 'Member',
            sortable: true,
            hideable: false,
            sortValue: (m) => m.username || m.email || '',
            render: (m) => (
                <div className="sk-cell-name">
                    <ServiceTile name={m.username || m.email || '?'} size={30} className="ws-row__av" />
                    <div>
                        <div>{m.username || m.email}</div>
                        {m.username && m.email && <div className="sk-cell-sub">{m.email}</div>}
                    </div>
                </div>
            ),
        },
        {
            key: 'role',
            header: 'Role',
            sortable: true,
            sortValue: (m) => m.role || '',
            render: (m) => (
                m.role === 'owner'
                    ? <Pill kind="green">{m.role}</Pill>
                    : <span className="sk-tag">{m.role}</span>
            ),
        },
        {
            key: 'actions',
            header: '',
            width: 120,
            sortable: false,
            hideable: false,
            render: (m) => (
                m.role !== 'owner' && (
                    <Button size="sm" variant="destructive" onClick={() => onRemoveMember(m.id)}>Remove</Button>
                )
            ),
        },
    ];

    return (
        <>
            <DataTable
                columns={columns}
                data={members}
                keyField="id"
                storageKey="serverkit-table-ws-members"
                className="ws-detail__tablecard"
                emptyTitle="No members"
                emptyMessage="This workspace has no members yet."
                footer={<DataTableFooter shown={members.length} total={members.length} noun="member" />}
            />
            {allUsers.filter(u => !members.find(m => m.user_id === u.id)).length > 0 && (
                <>
                    <div className="ws-pick-label">Add a member</div>
                    <div className="ws-pick">
                        {allUsers.filter(u => !members.find(m => m.user_id === u.id)).map(u => (
                            <div key={u.id} className="ws-pick__item" onClick={() => onAddMember(u.id)}>
                                <ServiceTile name={u.username || u.email || '?'} size={24} className="ws-row__av" />
                                <span className="ws-pick__name">{u.username || u.email}</span>
                                <Plus size={14} className="ws-pick__plus" />
                            </div>
                        ))}
                    </div>
                </>
            )}
        </>
    );
};

export default WorkspaceMembersTab;
