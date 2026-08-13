import { useState, useEffect } from 'react';
import api from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import UserModal from './UserModal';
import InvitationsTab from './InvitationsTab';
import LoginLinksSection from './LoginLinksSection';
import Modal from '../Modal';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { DataTable, ListToolbar } from '@/components/ds';
import {
    useTableChrome, GridViewPicker, GridChips, GridFilterButton,
    GridToolsMenu, GridFilterDrawer,
} from '@/components/ds/grid';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import useSettingFocus from '../../hooks/useSettingFocus';

// The label the Status cell shows, in one place: the built-in view below
// filters on it, and a rule matches a column's `value`, not the row's
// `is_active` boolean.
const statusLabel = (user) => (user.is_active ? 'Active' : 'Disabled');

// Built-in saved views. Every rule matches a column's `value` accessor, so the
// strings here are the LABELS the cells render ('Disabled', 'admin') rather
// than whatever the API happens to call the field.
const USER_VIEWS = [
    {
        // Who can do anything on this panel. It is the first question of an
        // access review and the one a flat alphabetical list buries as soon as
        // the team is bigger than a screen.
        name: 'Admins',
        state: {
            sorts: [{ key: 'user', direction: 'asc' }],
            hiddenKeys: [],
            groupBy: null,
            columnFilters: {
                match: 'all',
                rules: [{ id: 'uv1', field: 'role', op: 'any', value: ['admin'] }],
            },
        },
    },
    {
        // Offboarding check: a disabled account keeps its role and its history,
        // so it is still worth looking at. Most recently created first, because
        // the one you just switched off is the one you are verifying.
        name: 'Disabled accounts',
        state: {
            sorts: [{ key: 'created', direction: 'desc' }],
            hiddenKeys: [],
            groupBy: null,
            columnFilters: {
                match: 'all',
                rules: [{ id: 'uv2', field: 'status', op: 'any', value: ['Disabled'] }],
            },
        },
    },
    {
        // No rules: the whole team, bucketed by privilege. The group headers
        // carry the per-role counts, which is what "who has what" is asking.
        name: 'By role',
        state: {
            sorts: [{ key: 'user', direction: 'asc' }],
            hiddenKeys: [],
            groupBy: 'role',
            columnFilters: { match: 'all', rules: [] },
        },
    },
];

const UsersTab = () => {
    const register = useSettingFocus();
    const [users, setUsers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showModal, setShowModal] = useState(false);
    const [editingUser, setEditingUser] = useState(null);
    const [deleteConfirm, setDeleteConfirm] = useState(null);
    const { user: currentUser } = useAuth();

    // Lifted out of <DataTable> so a saved view can capture them. The storage
    // keys are the ones DataTable derived from storageKey="serverkit-table-
    // settings-users", so everyone's persisted sort and hidden columns survive.
    const { sorts, setSorts } = useTableSort({
        storageKey: 'serverkit-table-settings-users-sort',
    });
    const { hiddenKeys, setHiddenKeys } = useColumnVisibility({
        storageKey: 'serverkit-table-settings-users-cols',
    });
    // Not persisted on its own: a grouping worth keeping is a saved view.
    const [groupBy, setGroupBy] = useState(null);

    useEffect(() => {
        loadUsers();
    }, []);

    async function loadUsers() {
        try {
            setLoading(true);
            const data = await api.getUsers();
            setUsers(data.users);
            setError('');
        } catch (err) {
            setError(err.message || 'Failed to load users');
        } finally {
            setLoading(false);
        }
    }

    function handleAddUser() {
        setEditingUser(null);
        setShowModal(true);
    }

    function handleEditUser(user) {
        setEditingUser(user);
        setShowModal(true);
    }

    function handleCloseModal() {
        setShowModal(false);
        setEditingUser(null);
    }

    async function handleSaveUser(userData) {
        if (editingUser) {
            await api.updateUser(editingUser.id, userData);
        } else {
            await api.createUser(userData);
        }
        await loadUsers();
        handleCloseModal();
    }

    async function handleDeleteUser(user) {
        try {
            await api.deleteUser(user.id);
            setDeleteConfirm(null);
            await loadUsers();
        } catch (err) {
            setError(err.message || 'Failed to delete user');
        }
    }

    async function handleToggleActive(user) {
        try {
            await api.updateUser(user.id, { is_active: !user.is_active });
            await loadUsers();
        } catch (err) {
            setError(err.message || 'Failed to update user status');
        }
    }

    function getRoleBadgeVariant(role) {
        switch (role) {
            case 'admin': return 'destructive';
            case 'developer': return 'default';
            default: return 'secondary';
        }
    }

    function formatDate(dateString) {
        if (!dateString) return 'Never';
        return new Date(dateString).toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    // Columns for the shared DataTable. Cell markup and classNames are
    // identical to the hand-rolled table they replace, so _users.scss keeps
    // applying (.user-info, .user-avatar, .status-badge, .date-cell,
    // .actions-cell, tr.inactive).
    //
    // `type` + `value` are declared on every column a built-in view touches.
    // Inference reads `sortValue` when a column has no `value`, and both ways
    // it lands on the wrong type here: Created's epoch number would type that
    // column numeric, and three distinct roles across three users is over the
    // enum cardinality ratio, so Role would degrade to free text. Either way
    // the preset's rule would match zero rows.
    const columns = [
        {
            key: 'user',
            header: 'User',
            sortable: true,
            hideable: false,
            type: 'text',
            value: (user) => user.username || '',
            sortValue: (user) => user.username || '',
            cellClassName: 'user-info',
            render: (user) => (
                <>
                    <div className="user-avatar">
                        {user.username.charAt(0).toUpperCase()}
                    </div>
                    <div className="user-details">
                        <span className="username">
                            {user.username}
                            {user.id === currentUser?.id && (
                                <span className="you-badge">You</span>
                            )}
                        </span>
                        <span className="email">{user.email}</span>
                    </div>
                </>
            ),
        },
        {
            key: 'role',
            header: 'Role',
            sortable: true,
            type: 'enum',
            groupable: true,
            // All three accessors spelled out so the "By role" view groups,
            // filters and sorts on the same string. Grouping otherwise falls
            // back to row[key], which only works here by luck of naming.
            value: (user) => user.role || '',
            groupValue: (user) => user.role || '',
            sortValue: (user) => user.role || '',
            render: (user) => (
                <Badge variant={getRoleBadgeVariant(user.role)}>
                    {user.role}
                </Badge>
            ),
        },
        {
            key: 'status',
            header: 'Status',
            type: 'enum',
            value: statusLabel,
            render: (user) => (
                <span className={`status-badge ${user.is_active ? 'active' : 'inactive'}`}>
                    {statusLabel(user)}
                </span>
            ),
        },
        {
            // Sortable and typed rather than render-only: "when did this person
            // last sign in" is the access-review question, and without an
            // accessor the column had nothing behind it to sort or filter on.
            key: 'lastLogin',
            header: 'Last Login',
            sortable: true,
            type: 'date',
            value: (user) => user.last_login_at || null,
            sortValue: (user) => (user.last_login_at ? new Date(user.last_login_at).getTime() : null),
            cellClassName: 'date-cell',
            render: (user) => formatDate(user.last_login_at),
        },
        {
            key: 'created',
            header: 'Created',
            sortable: true,
            // Declared, not inferred: the sorter wants epoch ms, and letting
            // that number type the column would offer "is under 1754…" instead
            // of a date picker.
            type: 'date',
            value: (user) => user.created_at || null,
            sortValue: (user) => (user.created_at ? new Date(user.created_at).getTime() : null),
            cellClassName: 'date-cell',
            render: (user) => formatDate(user.created_at),
        },
        {
            key: 'actions',
            header: 'Actions',
            sortable: false,
            hideable: false,
            cellClassName: 'actions-cell',
            render: (user) => (
                <>
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleEditUser(user)}
                        title="Edit user"
                    >
                        <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                        </svg>
                    </Button>
                    {user.id !== currentUser?.id && (
                        <>
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleToggleActive(user)}
                                title={user.is_active ? 'Disable user' : 'Enable user'}
                                className={user.is_active ? 'text-warning' : 'text-success'}
                            >
                                {user.is_active ? (
                                    <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2">
                                        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
                                        <line x1="1" y1="1" x2="23" y2="23"/>
                                    </svg>
                                ) : (
                                    <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2">
                                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                                        <circle cx="12" cy="12" r="3"/>
                                    </svg>
                                )}
                            </Button>
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => setDeleteConfirm(user)}
                                title="Delete user"
                                className="text-destructive hover:text-destructive"
                            >
                                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2">
                                    <polyline points="3 6 5 6 21 6"/>
                                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                                </svg>
                            </Button>
                        </>
                    )}
                </>
            ),
        },
    ];

    // This tab renders TWO tables — the users list and, below it, the whole of
    // <InvitationsTab /> — so both chrome instances need their own URL
    // namespace. Unscoped they would read and write the same `?view=`/`?sort=`
    // and each would arrive as the other's.
    //
    // No `pageState`: the list is /users' whole response, with no search or
    // server-side filter of its own, so there is nothing page-private to carry.
    const chrome = useTableChrome({
        columns,
        rows: users,
        viewPageKey: 'settings-users',
        urlScope: 'users',
        builtinViews: USER_VIEWS,
        noun: 'users',
        sorts,
        setSorts,
        hiddenKeys,
        setHiddenKeys,
        groupBy,
        setGroupBy,
    });

    if (loading) {
        return (
            <div className="users-tab">
                <div className="loading-state">Loading users...</div>
            </div>
        );
    }

    return (
        <div className="users-tab">
            {/* The view name IS the heading — the old "User Management" h3 said
                what the tab strip already said, and stacking it above the
                picker would have been two titles for one table. */}
            <GridViewPicker
                views={chrome.views}
                label="users"
                onCreate={chrome.createView}
                actions={(
                    <>
                        <GridFilterButton
                            count={chrome.filterCount}
                            onClick={() => chrome.setDrawerOpen(true)}
                        />
                        <GridToolsMenu {...chrome.toolsProps} onRefresh={loadUsers} />
                    </>
                )}
            />
            <ListToolbar>
                <Button variant="default" onClick={handleAddUser}>
                    <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2">
                        <line x1="12" y1="5" x2="12" y2="19"/>
                        <line x1="5" y1="12" x2="19" y2="12"/>
                    </svg>
                    Add User
                </Button>
            </ListToolbar>

            <GridChips {...chrome.chipProps} />

            {error && <div className="error-message">{error}</div>}

            <div {...register('users-management', 'users-table-container')}>
                <DataTable
                    columns={chrome.columns}
                    data={users}
                    keyField="id"
                    sorts={sorts}
                    onSortsChange={setSorts}
                    {...chrome.tableProps}
                    groupBy={groupBy}
                    onGroupByChange={setGroupBy}
                    rowClassName={(user) => (!user.is_active ? 'inactive' : '')}
                    tableClassName="users-table"
                />
            </div>

            {showModal && (
                <UserModal
                    user={editingUser}
                    onSave={handleSaveUser}
                    onClose={handleCloseModal}
                />
            )}

            {deleteConfirm && (
                <Modal open={true} onClose={() => setDeleteConfirm(null)} title="Delete User" size="sm">
                            <p>Are you sure you want to delete <strong>{deleteConfirm.username}</strong>?</p>
                            <p className="text-muted">This action cannot be undone.</p>
                        <div className="modal-footer">
                            <Button variant="ghost" onClick={() => setDeleteConfirm(null)}>
                                Cancel
                            </Button>
                            <Button variant="destructive" onClick={() => handleDeleteUser(deleteConfirm)}>
                                Delete User
                            </Button>
                        </div>
                </Modal>
            )}

            <LoginLinksSection users={users} currentUserId={currentUser?.id} />

            <InvitationsTab />

            <GridFilterDrawer {...chrome.drawerProps} />
        </div>
    );
};

export default UsersTab;
