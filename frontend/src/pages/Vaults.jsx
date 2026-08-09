import { useEffect, useState } from 'react';
import api from '../services/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import Modal from '@/components/Modal';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { useToast } from '../contexts/ToastContext';
import { Plus, MoreVertical, Copy, Eye, EyeOff, Trash2 } from 'lucide-react';
import EmptyState from '../components/EmptyState';

const formatDate = (d) => (d ? new Date(d).toLocaleString() : '—');

/**
 * Vaults — encrypted key/value stores for credentials and tokens. Rendered
 * inside the Organization tab group (alongside Projects / Shared Variables /
 * Workspaces), so it shows no PageTopbar of its own — TabGroupLayout supplies
 * the shared header and tabs. Inbound webhooks live on their own /webhooks page.
 */
export default function Vaults() {
    const toast = useToast();

    const [vaults, setVaults] = useState([]);
    const [workspaces, setWorkspaces] = useState([]);
    const [loading, setLoading] = useState(true);

    const activeWorkspaceId = localStorage.getItem('active_workspace_id') || '';
    const [vaultForm, setVaultForm] = useState({ open: false, name: '', description: '', workspace_id: activeWorkspaceId });
    const [selectedVault, setSelectedVault] = useState(null);
    const [secretForm, setSecretForm] = useState({ open: false, name: '', value: '', description: '' });
    const [revealSecretId, setRevealSecretId] = useState(null);
    const [revealedValue, setRevealedValue] = useState('');

    useEffect(() => {
        loadAll();
    }, []);

    async function loadAll() {
        setLoading(true);
        try {
            const [v, w] = await Promise.all([
                api.listVaults(),
                api.getWorkspaces().catch(() => ({ workspaces: [] })),
            ]);
            setVaults(v.vaults || []);
            setWorkspaces(w.workspaces || []);
        } catch (err) {
            toast.error(`Load failed: ${err.message}`);
        } finally {
            setLoading(false);
        }
    }

    async function createVault(e) {
        e.preventDefault();
        try {
            const payload = {
                name: vaultForm.name,
                description: vaultForm.description,
                workspace_id: vaultForm.workspace_id || undefined,
            };
            await api.createVault(payload);
            setVaultForm({ open: false, name: '', description: '', workspace_id: activeWorkspaceId });
            loadAll();
            toast.success('Vault created');
        } catch (err) {
            toast.error(`Failed to create vault: ${err.message}`);
        }
    }

    async function deleteVault(id) {
        if (!confirm('Delete this vault and all its secrets?')) return;
        try {
            await api.deleteVault(id);
            if (selectedVault?.id === id) setSelectedVault(null);
            loadAll();
            toast.success('Vault deleted');
        } catch (err) {
            toast.error(`Failed to delete vault: ${err.message}`);
        }
    }

    async function createSecret(e) {
        e.preventDefault();
        try {
            await api.createSecret(selectedVault.id, {
                name: secretForm.name,
                value: secretForm.value,
                description: secretForm.description,
            });
            setSecretForm({ open: false, name: '', value: '', description: '' });
            openVault(selectedVault.id);
            toast.success('Secret created');
        } catch (err) {
            toast.error(`Failed to create secret: ${err.message}`);
        }
    }

    async function openVault(id) {
        try {
            const { vault } = await api.getVault(id);
            const { secrets } = await api.listSecrets(id);
            setSelectedVault({ ...vault, secrets });
        } catch (err) {
            toast.error(`Failed to load vault: ${err.message}`);
        }
    }

    async function revealSecret(secret) {
        try {
            const { secret: data } = await api.revealSecret(secret.id);
            setRevealSecretId(secret.id);
            setRevealedValue(data.value || '');
        } catch (err) {
            toast.error(`Reveal failed: ${err.message}`);
        }
    }

    async function deleteSecret(id) {
        if (!confirm('Delete this secret?')) return;
        try {
            await api.deleteSecret(id);
            openVault(selectedVault.id);
            toast.success('Secret deleted');
        } catch (err) {
            toast.error(`Failed to delete secret: ${err.message}`);
        }
    }

    if (loading) {
        return (
            <div className="sk-tabgroup__inner secrets-page">
                <EmptyState loading loadingVariant="table" title="Loading vaults..." />
            </div>
        );
    }

    return (
        <div className="sk-tabgroup__inner secrets-page">
            {!selectedVault ? (
                <Card>
                    <CardHeader>
                        <div className="secrets__header">
                            <div>
                                <CardTitle>Secret Vaults</CardTitle>
                                <CardDescription>Encrypted key/value stores for credentials and tokens.</CardDescription>
                            </div>
                            <Button onClick={() => setVaultForm({ open: true, name: '', description: '', workspace_id: activeWorkspaceId })}>
                                <Plus size={14} /> New Vault
                            </Button>
                        </div>
                    </CardHeader>
                    <CardContent>
                        {vaults.length === 0 ? (
                            <EmptyState title="No vaults yet" description="Create a vault to start storing secrets." />
                        ) : (
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Name</TableHead>
                                        <TableHead>Description</TableHead>
                                        <TableHead>Secrets</TableHead>
                                        <TableHead className="text-right">Actions</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {vaults.map(vault => (
                                        <TableRow key={vault.id} className="cursor-pointer" onClick={() => openVault(vault.id)}>
                                            <TableCell className="font-medium">{vault.name}</TableCell>
                                            <TableCell>{vault.description || '—'}</TableCell>
                                            <TableCell>{vault.secret_count ?? '—'}</TableCell>
                                            <TableCell className="text-right">
                                                <DropdownMenu>
                                                    <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                                                        <Button variant="ghost" size="icon"><MoreVertical size={14} /></Button>
                                                    </DropdownMenuTrigger>
                                                    <DropdownMenuContent align="end">
                                                        <DropdownMenuItem onClick={() => openVault(vault.id)}>Open</DropdownMenuItem>
                                                        <DropdownMenuItem className="text-destructive" onClick={() => deleteVault(vault.id)}>Delete</DropdownMenuItem>
                                                    </DropdownMenuContent>
                                                </DropdownMenu>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        )}
                    </CardContent>
                </Card>
            ) : (
                <Card>
                    <CardHeader>
                        <div className="secrets__header">
                            <div>
                                <Button variant="ghost" size="sm" onClick={() => setSelectedVault(null)}>← Back</Button>
                                <CardTitle className="mt-2">{selectedVault.name}</CardTitle>
                                <CardDescription>{selectedVault.description || 'No description'}</CardDescription>
                            </div>
                            <Button onClick={() => setSecretForm({ open: true, name: '', value: '', description: '' })}>
                                <Plus size={14} /> Add Secret
                            </Button>
                        </div>
                    </CardHeader>
                    <CardContent>
                        {(selectedVault.secrets || []).length === 0 ? (
                            <EmptyState title="No secrets yet" description="Add your first secret to this vault." />
                        ) : (
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Name</TableHead>
                                        <TableHead>Value</TableHead>
                                        <TableHead>Description</TableHead>
                                        <TableHead>Updated</TableHead>
                                        <TableHead className="text-right">Actions</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {selectedVault.secrets.map(secret => {
                                        const revealed = revealSecretId === secret.id;
                                        return (
                                            <TableRow key={secret.id}>
                                                <TableCell className="font-medium">{secret.name}</TableCell>
                                                <TableCell>
                                                    <code className="secrets__value">
                                                        {revealed ? revealedValue : secret.value}
                                                    </code>
                                                </TableCell>
                                                <TableCell>{secret.description || '—'}</TableCell>
                                                <TableCell>{formatDate(secret.updated_at)}</TableCell>
                                                <TableCell className="text-right">
                                                    <Button variant="ghost" size="icon" onClick={() => revealed ? setRevealSecretId(null) : revealSecret(secret)}>
                                                        {revealed ? <EyeOff size={14} /> : <Eye size={14} />}
                                                    </Button>
                                                    <Button variant="ghost" size="icon" onClick={() => { navigator.clipboard.writeText(revealed ? revealedValue : secret.value); toast.success('Copied') }}>
                                                        <Copy size={14} />
                                                    </Button>
                                                    <Button variant="ghost" size="icon" className="text-destructive" onClick={() => deleteSecret(secret.id)}>
                                                        <Trash2 size={14} />
                                                    </Button>
                                                </TableCell>
                                            </TableRow>
                                        );
                                    })}
                                </TableBody>
                            </Table>
                        )}
                    </CardContent>
                </Card>
            )}

            <Modal open={vaultForm.open} onClose={() => setVaultForm({ ...vaultForm, open: false })} title="New Vault">
                <p className="sk-modal__subtitle">Create an encrypted vault to group secrets.</p>
                <form onSubmit={createVault} className="space-y-4">
                        <div>
                            <Label htmlFor="vaultName">Name</Label>
                            <Input id="vaultName" value={vaultForm.name} onChange={(e) => setVaultForm({ ...vaultForm, name: e.target.value })} required />
                        </div>
                        <div>
                            <Label htmlFor="vaultDesc">Description</Label>
                            <Textarea id="vaultDesc" value={vaultForm.description} onChange={(e) => setVaultForm({ ...vaultForm, description: e.target.value })} />
                        </div>
                        {workspaces.length > 0 && (
                            <div>
                                <Label htmlFor="vaultWorkspace">Workspace</Label>
                                <Select
                                    value={vaultForm.workspace_id || 'all'}
                                    onValueChange={(value) => setVaultForm({ ...vaultForm, workspace_id: value === 'all' ? '' : value })}
                                >
                                    <SelectTrigger id="vaultWorkspace">
                                        <SelectValue placeholder="Select workspace" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="all">All workspaces</SelectItem>
                                        {workspaces.map((w) => (
                                            <SelectItem key={w.id} value={String(w.id)}>{w.name}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        )}
                        <div className="modal-actions">
                            <Button type="submit">Create Vault</Button>
                        </div>
                    </form>
            </Modal>

            <Modal open={secretForm.open} onClose={() => setSecretForm({ ...secretForm, open: false })} title="Add Secret">
                <p className="sk-modal__subtitle">Add an encrypted secret to {selectedVault?.name}.</p>
                <form onSubmit={createSecret} className="space-y-4">
                        <div>
                            <Label htmlFor="secretName">Name</Label>
                            <Input id="secretName" value={secretForm.name} onChange={(e) => setSecretForm({ ...secretForm, name: e.target.value })} required />
                        </div>
                        <div>
                            <Label htmlFor="secretValue">Value</Label>
                            <Textarea id="secretValue" value={secretForm.value} onChange={(e) => setSecretForm({ ...secretForm, value: e.target.value })} required />
                        </div>
                        <div>
                            <Label htmlFor="secretDesc">Description</Label>
                            <Textarea id="secretDesc" value={secretForm.description} onChange={(e) => setSecretForm({ ...secretForm, description: e.target.value })} />
                        </div>
                        <div className="modal-actions">
                            <Button type="submit">Save Secret</Button>
                        </div>
                    </form>
            </Modal>
        </div>
    );
}
