import { useState, useEffect, useCallback } from 'react';
import { Copy, Plus, Trash2, UserRound } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { useConfirm } from '../../hooks/useConfirm';
import { Button } from '@/components/ui/button';
import { copyToClipboard } from '@/utils/clipboard';

// Users ServerKit created on a managed database (tracked rows merged with the
// live engine list). Create returns the password exactly once — it is shown
// until dismissed and never retrievable again.
export default function DbUsersPanel({ databaseId }) {
    const toast = useToast();
    const { confirm } = useConfirm();
    const [users, setUsers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [creating, setCreating] = useState(false);
    const [newUsername, setNewUsername] = useState('');
    const [newGrants, setNewGrants] = useState('ALL');
    const [oneTimeSecret, setOneTimeSecret] = useState(null); // { username, password }

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await api.getManagedDbUsers(databaseId);
            setUsers(data?.users || []);
        } catch (err) {
            toast.error(err.message || 'Failed to load database users');
        } finally {
            setLoading(false);
        }
    }, [databaseId, toast]);

    useEffect(() => { load(); }, [load]);

    async function createUser(e) {
        e.preventDefault();
        setCreating(true);
        try {
            const grants = newGrants.split(',').map((g) => g.trim()).filter(Boolean);
            const data = await api.createManagedDbUser(databaseId, {
                username: newUsername.trim() || undefined,
                grants: grants.length ? grants : undefined,
            });
            setOneTimeSecret({ username: data.user.username, password: data.password });
            setNewUsername('');
            setNewGrants('ALL');
            await load();
        } catch (err) {
            toast.error(err.message || 'Failed to create user');
        } finally {
            setCreating(false);
        }
    }

    async function removeUser(user) {
        const ok = await confirm({
            title: `Drop user “${user.username}”?`,
            message: 'This drops the user on the database server and stops tracking it.',
            confirmText: 'Drop user',
            danger: true,
        });
        if (!ok) return;
        try {
            await api.deleteManagedDbUser(databaseId, user.id);
            toast.success('User dropped');
            await load();
        } catch (err) {
            toast.error(err.message || 'Failed to drop user');
        }
    }

    async function copySecret() {
        if (oneTimeSecret && await copyToClipboard(oneTimeSecret.password)) {
            toast.success('Password copied');
        }
    }

    return (
        <div className="managed-db__users">
            {oneTimeSecret && (
                <div className="managed-db__secret">
                    <span className="managed-db__meta">
                        Password for <strong>{oneTimeSecret.username}</strong>:{' '}
                        <code>{oneTimeSecret.password}</code> — shown once, save it now.
                    </span>
                    <div className="managed-db__actions">
                        <Button type="button" size="sm" variant="outline" onClick={copySecret}>
                            <Copy size={14} /> Copy
                        </Button>
                        <Button type="button" size="sm" variant="ghost"
                            onClick={() => setOneTimeSecret(null)}>
                            Dismiss
                        </Button>
                    </div>
                </div>
            )}

            {loading ? (
                <p className="managed-db__hint">Loading users…</p>
            ) : users.length === 0 ? (
                <p className="managed-db__hint">No users tracked for this database yet.</p>
            ) : (
                <div className="managed-db__list">
                    {users.map((user) => (
                        <div key={user.id ?? `live-${user.username}`} className="managed-db__row">
                            <div className="managed-db__info">
                                <strong><UserRound size={13} /> {user.username}</strong>
                                <span className="managed-db__meta">
                                    {user.tracked === false
                                        ? 'exists on server, not created by ServerKit'
                                        : (user.grants || []).join(', ') || 'no grants recorded'}
                                    {user.present === false ? ' · missing on server' : ''}
                                </span>
                            </div>
                            {user.tracked !== false && (
                                <div className="managed-db__actions">
                                    <Button type="button" size="sm" variant="ghost"
                                        onClick={() => removeUser(user)}
                                        aria-label={`Drop user ${user.username}`}>
                                        <Trash2 size={14} /> Drop
                                    </Button>
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}

            <form className="managed-db__user-form" onSubmit={createUser}>
                <input
                    type="text"
                    value={newUsername}
                    onChange={(e) => setNewUsername(e.target.value)}
                    placeholder="username (blank = generated)"
                    aria-label="New user name"
                />
                <input
                    type="text"
                    value={newGrants}
                    onChange={(e) => setNewGrants(e.target.value)}
                    placeholder="grants, e.g. ALL or SELECT, INSERT"
                    aria-label="Grants"
                />
                <Button type="submit" size="sm" variant="outline" disabled={creating}>
                    <Plus size={14} /> {creating ? 'Creating…' : 'Create user'}
                </Button>
            </form>
        </div>
    );
}
