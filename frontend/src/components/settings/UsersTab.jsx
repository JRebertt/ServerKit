import { useState, useEffect } from 'react';
import api from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import UserModal from './UserModal';
import InvitationsTab from './InvitationsTab';
import LoginLinksSection from './LoginLinksSection';
import Modal from '../Modal';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { DataTable, DataTableFooter } from '@/components/ds';
import useSettingFocus from '../../hooks/useSettingFocus';

const UsersTab = () => {
    const register = useSettingFocus();
    const [users, setUsers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showModal, setShowModal] = useState(false);
    const [editingUser, setEditingUser] = useState(null);
    const [deleteConfirm, setDeleteConfirm] = useState(null);
    const { user: currentUser } = useAuth();

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

    if (loading) {
        return (
            <div className="users-tab">
                <div className="loading-state">Loading users...</div>
            </div>
        );
    }

    // Columns for the shared DataTable. Cell markup and classNames are
    // identical to the hand-rolled table they replace, so _users.scss keeps
    // applying (.user-info, .user-avatar, .status-badge, .date-cell,
    // .actions-cell, tr.inactive).
    const columns = [
        {
            key: 'user',
            header: 'User',
            sortable: true,
            hideable: false,
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
            render: (user) => (
                <span className={`status-badge ${user.is_active ? 'active' : 'inactive'}`}>
                    {user.is_active ? 'Active' : 'Disabled'}
                </span>
            ),
        },
        {
            key: 'lastLogin',
            header: 'Last Login',
            cellClassName: 'date-cell',
            render: (user) => formatDate(user.last_login_at),
        },
        {
            key: 'created',
            header: 'Created',
            sortable: true,
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

    return (
        <div className="users-tab">
            <div className="tab-header">
                <div className="tab-header-content">
                    <h3>User Management</h3>
                    <p>Manage user accounts and permissions</p>
                </div>
                <Button variant="default" onClick={handleAddUser}>
                    <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2">
                        <line x1="12" y1="5" x2="12" y2="19"/>
                        <line x1="5" y1="12" x2="19" y2="12"/>
                    </svg>
                    Add User
                </Button>
            </div>

            {error && <div className="error-message">{error}</div>}

            <div {...register('users-management', 'users-table-container')}>
                <DataTable
                    columns={columns}
                    data={users}
                    keyField="id"
                    storageKey="serverkit-table-settings-users"
                    rowClassName={(user) => (!user.is_active ? 'inactive' : '')}
                    tableClassName="users-table"
                    footer={(
                        <DataTableFooter
                            shown={users.length}
                            total={users.length}
                            noun="user"
                        />
                    )}
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
        </div>
    );
};

export default UsersTab;
