import { useState, useEffect } from 'react';
import api from '../../services/api';
import InviteModal from './InviteModal';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { DataTable, DataTableFooter } from '@/components/ds';
import EmptyState from '../EmptyState';

const InvitationsTab = () => {
    const [invitations, setInvitations] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showInviteModal, setShowInviteModal] = useState(false);
    const [copied, setCopied] = useState(null);

    useEffect(() => {
        loadInvitations();
    }, []);

    async function loadInvitations() {
        try {
            setLoading(true);
            const data = await api.getInvitations();
            setInvitations(data.invitations || []);
        } catch {
            // Silently handle
        } finally {
            setLoading(false);
        }
    }

    async function handleRevoke(id) {
        try {
            await api.revokeInvitation(id);
            await loadInvitations();
        } catch {
            // Silently handle
        }
    }

    async function handleResend(id) {
        try {
            await api.resendInvitation(id);
        } catch {
            // Silently handle
        }
    }

    function copyLink(token) {
        const url = `${window.location.origin}/register?invite=${token}`;
        navigator.clipboard.writeText(url);
        setCopied(token);
        setTimeout(() => setCopied(null), 2000);
    }

    function formatDate(dateString) {
        if (!dateString) return 'Never';
        return new Date(dateString).toLocaleDateString('en-US', {
            year: 'numeric', month: 'short', day: 'numeric'
        });
    }

    function getRoleBadgeVariant(role) {
        switch (role) {
            case 'admin': return 'destructive';
            case 'developer': return 'default';
            default: return 'secondary';
        }
    }

    function getStatusBadgeVariant(status, isExpired) {
        if (isExpired && status === 'pending') return 'warning';
        switch (status) {
            case 'pending': return 'info';
            case 'accepted': return 'success';
            case 'expired': return 'warning';
            case 'revoked': return 'secondary';
            default: return 'secondary';
        }
    }

    // Columns for the shared DataTable. Cell markup and classNames are
    // identical to the hand-rolled table they replace, so _users.scss keeps
    // applying (.users-table, .date-cell, .actions-cell).
    const columns = [
        {
            key: 'recipient',
            header: 'Recipient',
            sortable: true,
            hideable: false,
            sortValue: (inv) => inv.email || '',
            render: (inv) => inv.email || <span className="text-muted">Link only</span>,
        },
        {
            key: 'role',
            header: 'Role',
            render: (inv) => (
                <Badge variant={getRoleBadgeVariant(inv.role)}>
                    {inv.role}
                </Badge>
            ),
        },
        {
            key: 'status',
            header: 'Status',
            sortable: true,
            sortValue: (inv) => (inv.is_expired && inv.status === 'pending' ? 'expired' : inv.status || ''),
            render: (inv) => (
                <Badge variant={getStatusBadgeVariant(inv.status, inv.is_expired)}>
                    {inv.is_expired && inv.status === 'pending' ? 'expired' : inv.status}
                </Badge>
            ),
        },
        {
            key: 'created',
            header: 'Created',
            sortable: true,
            sortValue: (inv) => (inv.created_at ? new Date(inv.created_at).getTime() : null),
            cellClassName: 'date-cell',
            render: (inv) => formatDate(inv.created_at),
        },
        {
            key: 'expires',
            header: 'Expires',
            cellClassName: 'date-cell',
            render: (inv) => formatDate(inv.expires_at),
        },
        {
            key: 'actions',
            header: 'Actions',
            sortable: false,
            hideable: false,
            cellClassName: 'actions-cell',
            render: (inv) => (
                inv.status === 'pending' && !inv.is_expired && (
                    <>
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => copyLink(inv.token)}
                            title="Copy invite link"
                        >
                            {copied === inv.token ? 'Copied!' : 'Copy Link'}
                        </Button>
                        {inv.email && (
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleResend(inv.id)}
                                title="Resend email"
                            >
                                Resend
                            </Button>
                        )}
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleRevoke(inv.id)}
                            title="Revoke invitation"
                            className="text-destructive hover:text-destructive"
                        >
                            Revoke
                        </Button>
                    </>
                )
            ),
        },
    ];

    return (
        <div className="invitations-section">
            <div className="tab-header">
                <div className="tab-header-content">
                    <h4>Invitations</h4>
                    <p>Manage team invitations</p>
                </div>
                <Button variant="default" size="sm" onClick={() => setShowInviteModal(true)}>
                    <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" fill="none" strokeWidth="2">
                        <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                        <circle cx="8.5" cy="7" r="4"/>
                        <line x1="20" y1="8" x2="20" y2="14"/>
                        <line x1="23" y1="11" x2="17" y2="11"/>
                    </svg>
                    Invite User
                </Button>
            </div>

            {loading ? (
                <div className="loading-state">Loading invitations...</div>
            ) : invitations.length === 0 ? (
                <EmptyState title="No invitations yet" />
            ) : (
                <div className="users-table-container">
                    <DataTable
                        columns={columns}
                        data={invitations}
                        keyField="id"
                        storageKey="serverkit-table-settings-invitations"
                        tableClassName="users-table"
                        footer={(
                            <DataTableFooter
                                shown={invitations.length}
                                total={invitations.length}
                                noun="invitation"
                            />
                        )}
                    />
                </div>
            )}

            {showInviteModal && (
                <InviteModal
                    onClose={() => setShowInviteModal(false)}
                    onCreated={loadInvitations}
                />
            )}
        </div>
    );
};

export default InvitationsTab;
