import { useState } from 'react';
import { Copy, Check, AlertTriangle } from 'lucide-react';
import Modal from '../Modal';
import ApiKeyScopesModal from '../api/ApiKeyScopesModal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { copyToClipboard } from '@/utils/clipboard';

const TIER_OPTIONS = [
    { value: 'standard', label: 'Standard', desc: '100 req/min' },
    { value: 'elevated', label: 'Elevated', desc: '500 req/min' },
    { value: 'unlimited', label: 'Unlimited', desc: '5000 req/min' },
];

const ApiKeyModal = ({ onClose, onSubmit, createdKey }) => {
    const [name, setName] = useState('');
    const [scopes, setScopes] = useState(['*']);
    const [tier, setTier] = useState('standard');
    const [expiresAt, setExpiresAt] = useState('');
    const [saving, setSaving] = useState(false);
    const [copied, setCopied] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!name.trim()) return;
        setSaving(true);
        try {
            await onSubmit({
                name: name.trim(),
                scopes,
                tier,
                expires_at: expiresAt || null,
            });
        } finally {
            setSaving(false);
        }
    };

    const copyKey = async () => {
        if (createdKey && await copyToClipboard(createdKey)) {
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        }
    };

    // Show created key view
    if (createdKey) {
        return (
            <Modal open={true} onClose={onClose} title="API Key Created" className="api-key-modal">
                        <div className="api-key-modal__warning">
                            <AlertTriangle size={16} />
                            <span>Copy this key now. It will not be shown again.</span>
                        </div>
                        <div className="api-key-modal__key-display">
                            <code>{createdKey}</code>
                            <Button variant="outline" size="sm" onClick={copyKey}>
                                {copied ? <Check size={14} /> : <Copy size={14} />}
                                {copied ? 'Copied' : 'Copy'}
                            </Button>
                        </div>
                    <div className="modal-footer">
                        <Button variant="default" onClick={onClose}>Done</Button>
                    </div>
            </Modal>
        );
    }

    return (
        <Modal open={true} onClose={onClose} title="Create API Key" className="api-key-modal">
                <form onSubmit={handleSubmit}>
                    <div className="modal-body">
                        <div className="form-group">
                            <Label>Name</Label>
                            <Input
                                type="text"
                                value={name}
                                onChange={e => setName(e.target.value)}
                                placeholder="e.g. CI/CD Pipeline, Monitoring Script"
                                required
                            />
                        </div>

                        <div className="form-group">
                            <Label>Tier</Label>
                            <div className="api-key-modal__tiers">
                                {TIER_OPTIONS.map(t => (
                                    <button
                                        key={t.value}
                                        type="button"
                                        className={`api-key-modal__tier-btn ${tier === t.value ? 'active' : ''}`}
                                        onClick={() => setTier(t.value)}
                                    >
                                        <span className="api-key-modal__tier-label">{t.label}</span>
                                        <span className="api-key-modal__tier-desc">{t.desc}</span>
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div className="form-group">
                            <Label>Scopes</Label>
                            <ApiKeyScopesModal value={scopes} onChange={setScopes} />
                        </div>

                        <div className="form-group">
                            <Label>Expiration (optional)</Label>
                            <Input
                                type="datetime-local"
                                value={expiresAt}
                                onChange={e => setExpiresAt(e.target.value)}
                            />
                            <span className="form-help">Leave empty for no expiration</span>
                        </div>
                    </div>
                    <div className="modal-footer">
                        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
                        <Button type="submit" variant="default" disabled={saving || !name.trim()}>
                            {saving ? 'Creating...' : 'Create Key'}
                        </Button>
                    </div>
                </form>
        </Modal>
    );
};

export default ApiKeyModal;
