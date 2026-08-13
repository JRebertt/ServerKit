import { useState, useEffect } from 'react';
import api from '../../services/api';
import InviteModal from './InviteModal';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { DataTable } from '@/components/ds';
import {
    useTableChrome, GridViewPicker, GridChips, GridFilterButton,
    GridToolsMenu, GridFilterDrawer,
} from '@/components/ds/grid';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import EmptyState from '../EmptyState';

// A pending invite whose window has closed still carries status 'pending' in
// the database — the row only becomes 'expired' on screen. One accessor for
// the cell, the sort and the filter rules, so all three agree.
const effectiveStatus = (inv) => (
    inv.is_expired && inv.status === 'pending' ? 'expired' : inv.status || ''
);

// Built-in saved views. The three that matter are the three lifecycle states:
// what is still live, what lapsed, and what was taken up.
const INVITATION_VIEWS = [
    {
        // The live links — the ones that can still be used to create an
        // account. Soonest to lapse first, so a resend beats the deadline.
        name: 'Pending',
        state: {
            sorts: [{ key: 'expires', direction: 'asc' }],
            hiddenKeys: [],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'iv1', field: 'status', op: 'any', value: ['pending'] }],
            },
        },
    },
    {
        // The worklist: each of these is a person who was invited and never
        // got in. Resend or revoke, newest first.
        name: 'Expired',
        state: {
            sorts: [{ key: 'created', direction: 'desc' }],
            hiddenKeys: [],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'iv2', field: 'status', op: 'any', value: ['expired'] }],
            },
        },
    },
    {
        // Who actually joined, and when. Expires is hidden — it stopped
        // meaning anything the moment the invite was accepted.
        name: 'Accepted',
        state: {
            sorts: [{ key: 'created', direction: 'desc' }],
            hiddenKeys: ['expires'],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'iv3', field: 'status', op: 'any', value: ['accepted'] }],
            },
        },
    },
];

const InvitationsTab = () => {
    const [invitations, setInvitations] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showInviteModal, setShowInviteModal] = useState(false);
    const [copied, setCopied] = useState(null);

    // Lifted out of <DataTable> so a saved view can capture them. The storage
    // keys are the ones DataTable derived from storageKey="serverkit-table-
    // settings-invitations", so a persisted sort or hidden column survives.
    const { sorts, setSorts } = useTableSort({
        storageKey: 'serverkit-table-settings-invitations-sort',
    });
    const { hiddenKeys, setHiddenKeys } = useColumnVisibility({
        storageKey: 'serverkit-table-settings-invitations-cols',
    });

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
    //
    // `type` + `value` are declared wherever a built-in view reads a column:
    // inference falls back to `sortValue`, which on the date columns is an
    // epoch number and would have typed them numeric — a date rule against a
    // numeric column matches nothing.
    const columns = [
        {
            key: 'recipient',
            header: 'Recipient',
            sortable: true,
            hideable: false,
            type: 'text',
            value: (inv) => inv.email || '',
            sortValue: (inv) => inv.email || '',
            render: (inv) => inv.email || <span className="text-muted">Link only</span>,
        },
        {
            key: 'role',
            header: 'Role',
            type: 'enum',
            value: (inv) => inv.role || '',
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
            type: 'enum',
            value: effectiveStatus,
            sortValue: effectiveStatus,
            render: (inv) => (
                <Badge variant={getStatusBadgeVariant(inv.status, inv.is_expired)}>
                    {effectiveStatus(inv)}
                </Badge>
            ),
        },
        {
            key: 'created',
            header: 'Created',
            sortable: true,
            type: 'date',
            value: (inv) => inv.created_at || null,
            sortValue: (inv) => (inv.created_at ? new Date(inv.created_at).getTime() : null),
            cellClassName: 'date-cell',
            render: (inv) => formatDate(inv.created_at),
        },
        {
            // Sortable now: "Pending" leads with whatever lapses first, which
            // needs a real accessor behind the column rather than a render.
            key: 'expires',
            header: 'Expires',
            sortable: true,
            type: 'date',
            value: (inv) => inv.expires_at || null,
            sortValue: (inv) => (inv.expires_at ? new Date(inv.expires_at).getTime() : null),
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

    // This component is rendered INSIDE <UsersTab />, so the Users tab shows
    // two tables and both chrome instances would otherwise fight over the same
    // `?view=`/`?sort=` keys. The scope namespaces this one's link params.
    //
    // No `pageState`: the section has no search or filter of its own.
    const chrome = useTableChrome({
        columns,
        rows: invitations,
        viewPageKey: 'settings-invitations',
        urlScope: 'invites',
        builtinViews: INVITATION_VIEWS,
        noun: 'invitations',
        sorts,
        setSorts,
        hiddenKeys,
        setHiddenKeys,
    });

    return (
        <div className="invitations-section">
            {/* The view name replaces the old "Invitations" h4: it names the
                section AND says which slice of it you are looking at. */}
            <GridViewPicker
                views={chrome.views}
                label="invitations"
                onCreate={chrome.createView}
                actions={(
                    <>
                        {/* Same shape as the users table above it — the two sit
                            on one screen, so the primary action has to land in
                            the same place on both lines. */}
                        <Button variant="default" size="sm" onClick={() => setShowInviteModal(true)}>
                            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" fill="none" strokeWidth="2">
                                <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                                <circle cx="8.5" cy="7" r="4"/>
                                <line x1="20" y1="8" x2="20" y2="14"/>
                                <line x1="23" y1="11" x2="17" y2="11"/>
                            </svg>
                            Invite User
                        </Button>
                        <GridFilterButton
                            count={chrome.filterCount}
                            onClick={() => chrome.setDrawerOpen(true)}
                        />
                        <GridToolsMenu {...chrome.toolsProps} onRefresh={loadInvitations} />
                    </>
                )}
            />

            <GridChips {...chrome.chipProps} />

            {loading ? (
                <div className="loading-state">Loading invitations...</div>
            ) : invitations.length === 0 ? (
                <EmptyState title="No invitations yet" />
            ) : (
                <div className="users-table-container">
                    <DataTable
                        columns={chrome.columns}
                        data={invitations}
                        keyField="id"
                        sorts={sorts}
                        onSortsChange={setSorts}
                        {...chrome.tableProps}
                        tableClassName="users-table"
                    />
                </div>
            )}

            {showInviteModal && (
                <InviteModal
                    onClose={() => setShowInviteModal(false)}
                    onCreated={loadInvitations}
                />
            )}

            <GridFilterDrawer {...chrome.drawerProps} />
        </div>
    );
};

export default InvitationsTab;
