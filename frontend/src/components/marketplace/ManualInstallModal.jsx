import { useState } from 'react';
import {
    DownloadCloud,
    FileArchive,
    FolderOpen,
    Globe2,
    PlugZap,
    Search,
    ShieldAlert,
    ShieldCheck,
} from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import Modal from '@/components/Modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import DocsLink from '@/components/DocsLink';

const INSTALL_SOURCES = [
    { id: 'url', label: 'URL', icon: Globe2 },
    { id: 'path', label: 'Folder', icon: FolderOpen },
    { id: 'upload', label: 'Zip', icon: FileArchive },
];

const SourceInput = ({
    description,
    placeholder,
    value,
    onChange,
    onInstall,
    disabled,
    installDisabled,
    actionLabel = 'Install',
    ActionIcon = DownloadCloud,
    busyLabel = 'Installing...',
}) => (
    <div className="plugin-install-source">
        <p className="text-muted">{description}</p>
        <div className="plugin-install-row">
            <Input
                placeholder={placeholder}
                value={value}
                onChange={(event) => onChange(event.target.value)}
                onKeyDown={(event) => event.key === 'Enter' && onInstall()}
                disabled={disabled}
            />
            <Button onClick={onInstall} disabled={installDisabled}>
                <ActionIcon aria-hidden="true" />
                {disabled ? busyLabel : actionLabel}
            </Button>
        </div>
    </div>
);

// Signature verdict badge for the consent card (plan 55). 'verified' means the
// release zip's ed25519 signature checked out against a publisher key pinned
// by this panel; everything else is an honest not-verified treatment.
const SignatureBadge = ({ signature }) => {
    const status = signature?.status || 'unsigned';
    if (status === 'verified') {
        return (
            <Badge variant="success" className="plugin-install-consent__badge">
                <ShieldCheck aria-hidden="true" />
                Signed · {signature.publisher || signature.key_id}
            </Badge>
        );
    }
    if (status === 'untrusted_key') {
        return (
            <Badge variant="warning" className="plugin-install-consent__badge">
                <ShieldAlert aria-hidden="true" />
                Signed · unknown publisher
            </Badge>
        );
    }
    if (status === 'invalid') {
        return (
            <Badge variant="destructive" className="plugin-install-consent__badge">
                <ShieldAlert aria-hidden="true" />
                Signature invalid
            </Badge>
        );
    }
    return (
        <Badge variant="warning" className="plugin-install-consent__badge">
            <ShieldAlert aria-hidden="true" />
            Unsigned
        </Badge>
    );
};

// The consent card shown after a GitHub/zip URL is resolved but before install.
// Presents what will be installed and what it wants — the same permissions
// presentation as the registry detail modal — so the install is never blind.
const PreviewConsent = ({ preview, installing, onInstall, onCancel }) => {
    const permissions = Array.isArray(preview.permissions) ? preview.permissions : [];
    const warnings = Array.isArray(preview.warnings) ? preview.warnings : [];
    const sigStatus = preview.signature?.status || 'unsigned';
    const compat = preview.min_panel_version || preview.max_panel_version
        ? `Panel ${preview.min_panel_version || '*'}–${preview.max_panel_version || '*'}`
        : null;

    return (
        <div className="plugin-install-consent">
            <div className="plugin-install-consent__head">
                <div>
                    <h4>{preview.display_name}</h4>
                    <div className="plugin-install-consent__meta">
                        <span>v{preview.version}</span>
                        <code>{preview.slug}</code>
                        {preview.author && <span>by {preview.author}</span>}
                        {compat && <span>{compat}</span>}
                    </div>
                </div>
                <SignatureBadge signature={preview.signature} />
            </div>

            {preview.description && (
                <p className="plugin-install-consent__desc">{preview.description}</p>
            )}

            {sigStatus === 'invalid' && (
                <p className="plugin-install-consent__sig-note plugin-install-consent__sig-note--danger">
                    {preview.signature?.error || 'The signature does not match this archive.'}
                    {' '}The download may have been tampered with — do not install it.
                </p>
            )}
            {sigStatus === 'untrusted_key' && (
                <p className="plugin-install-consent__sig-note">
                    This release is signed, but the publisher key is not pinned by this
                    panel, so the signature cannot be verified. Treat it as unsigned.
                </p>
            )}
            {sigStatus === 'unsigned' && (
                <p className="plugin-install-consent__sig-note">
                    This release carries no publisher signature. It will run with full
                    panel privileges — install only if you trust the source.
                </p>
            )}

            <div className="plugin-install-consent__section">
                <p className="plugin-install-consent__label">This extension requests:</p>
                {permissions.length > 0 ? (
                    <div className="plugin-install-consent__chips">
                        {permissions.map((permission) => (
                            <Badge key={permission} variant="outline">{permission}</Badge>
                        ))}
                    </div>
                ) : (
                    <p className="text-muted">No host permissions declared.</p>
                )}
            </div>

            {warnings.length > 0 && (
                <ul className="plugin-install-consent__warnings">
                    {warnings.map((warning) => (
                        <li key={warning}>
                            <ShieldAlert aria-hidden="true" />
                            {warning}
                        </li>
                    ))}
                </ul>
            )}

            <div className="plugin-install-consent__actions">
                <Button variant="secondary" onClick={onCancel} disabled={installing}>
                    Back
                </Button>
                <Button
                    onClick={onInstall}
                    disabled={installing || sigStatus === 'invalid'}
                    variant={sigStatus === 'verified' ? 'default' : 'destructive'}
                >
                    <DownloadCloud aria-hidden="true" />
                    {installing ? 'Installing...'
                        : sigStatus === 'verified' ? 'Install' : 'Install anyway'}
                </Button>
            </div>
        </div>
    );
};

// Manual extension install (URL / host folder / zip upload). An occasional
// operator action, so it lives in a modal off the topbar rather than a tab.
// The URL path is two-step: resolve → consent card → install, so what lands is
// previewed (and checksum-pinned) before it touches the panel.
const ManualInstallModal = ({ defaultSource = 'url', onClose, onInstalled }) => {
    const toast = useToast();
    const [installSource, setInstallSource] = useState(defaultSource);
    const [pluginUrl, setPluginUrl] = useState('');
    const [pluginPath, setPluginPath] = useState('');
    const [pluginFile, setPluginFile] = useState(null);
    const [installing, setInstalling] = useState(false);
    const [previewing, setPreviewing] = useState(false);
    const [preview, setPreview] = useState(null);

    const switchSource = (id) => {
        setInstallSource(id);
        setPreview(null);
    };

    const handleUrlChange = (value) => {
        setPluginUrl(value);
        if (preview) setPreview(null);
    };

    const handlePreview = async () => {
        if (!pluginUrl.trim()) return;
        setPreviewing(true);
        try {
            const result = await api.previewPlugin(pluginUrl.trim());
            setPreview(result);
        } catch (err) {
            toast.error(err.message || 'Could not resolve that extension');
        } finally {
            setPreviewing(false);
        }
    };

    const handleInstallFromPreview = async () => {
        setInstalling(true);
        try {
            // Pin the install to the exact previewed bytes (resolved URL +
            // sha256) and re-verify the previewed signature against them.
            const result = await api.installPlugin(
                preview.resolved_url, preview.sha256, preview.signature);
            toast.success(`Extension "${result.display_name}" installed. Restart backend to activate routes.`);
            onInstalled();
        } catch (err) {
            toast.error(err.message || 'Extension installation failed');
        } finally {
            setInstalling(false);
        }
    };

    const handleInstall = async () => {
        let action;
        if (installSource === 'path') {
            if (!pluginPath.trim()) return;
            action = () => api.installPluginFromPath(pluginPath.trim());
        } else if (installSource === 'upload') {
            if (!pluginFile) return;
            action = () => api.installPluginFromZip(pluginFile);
        } else {
            return;
        }

        setInstalling(true);
        try {
            const result = await action();
            toast.success(`Extension "${result.display_name}" installed. Restart backend to activate routes.`);
            onInstalled();
        } catch (err) {
            toast.error(err.message || 'Extension installation failed');
        } finally {
            setInstalling(false);
        }
    };

    return (
        <Modal open onClose={onClose} title="Install extension manually" size="md">
            <div className="plugin-install-form">
                <div className="plugin-install-form__heading">
                    <div className="plugin-install-form__icon">
                        <PlugZap aria-hidden="true" />
                    </div>
                    <div>
                        <h3>Extension source</h3>
                        <p className="text-muted">Load extension packages from a repository, host folder, or zip archive.</p>
                    </div>
                    <DocsLink to="extensionsInstalling" className="plugin-install-form__docs" />
                </div>

                <div className="plugin-install-tabs" role="tablist" aria-label="Extension install source">
                    {INSTALL_SOURCES.map((source) => {
                        const SourceIcon = source.icon;
                        return (
                            <button
                                key={source.id}
                                role="tab"
                                type="button"
                                aria-selected={installSource === source.id}
                                className={`plugin-install-tab ${installSource === source.id ? 'plugin-install-tab--active' : ''}`}
                                onClick={() => switchSource(source.id)}
                            >
                                <SourceIcon aria-hidden="true" />
                                {source.label}
                            </button>
                        );
                    })}
                </div>

                {installSource === 'url' && !preview && (
                    <SourceInput
                        description="Paste a GitHub repo (owner/repo or owner/repo@tag), a release URL, or a direct zip link. You'll preview what installs before it lands."
                        placeholder="owner/serverkit-plugin"
                        value={pluginUrl}
                        onChange={handleUrlChange}
                        onInstall={handlePreview}
                        disabled={previewing}
                        installDisabled={previewing || !pluginUrl.trim()}
                        actionLabel="Preview"
                        ActionIcon={Search}
                        busyLabel="Resolving..."
                    />
                )}

                {installSource === 'url' && preview && (
                    <PreviewConsent
                        preview={preview}
                        installing={installing}
                        onInstall={handleInstallFromPreview}
                        onCancel={() => setPreview(null)}
                    />
                )}

                {installSource === 'path' && (
                    <SourceInput
                        description="Use an absolute path that exists on the backend host or inside the backend container."
                        placeholder="/opt/serverkit/plugins/my-plugin"
                        value={pluginPath}
                        onChange={setPluginPath}
                        onInstall={handleInstall}
                        disabled={installing}
                        installDisabled={installing || !pluginPath.trim()}
                    />
                )}

                {installSource === 'upload' && (
                    <div className="plugin-install-source">
                        <p className="text-muted">
                            Upload an extension zip with <code>plugin.json</code> at the top level or one folder deep.
                        </p>
                        <div className="plugin-install-row">
                            <Input
                                type="file"
                                className="marketplace-file-input"
                                accept=".zip,application/zip,application/x-zip-compressed"
                                disabled={installing}
                                onChange={(event) => setPluginFile(event.target.files?.[0] || null)}
                            />
                            <Button
                                onClick={handleInstall}
                                disabled={installing || !pluginFile}
                            >
                                <DownloadCloud aria-hidden="true" />
                                {installing ? 'Installing...' : 'Install'}
                            </Button>
                        </div>
                        {pluginFile && (
                            <div className="plugin-file-note">
                                {pluginFile.name} | {(pluginFile.size / 1024).toFixed(1)} KB
                            </div>
                        )}
                    </div>
                )}
            </div>
        </Modal>
    );
};

export default ManualInstallModal;
