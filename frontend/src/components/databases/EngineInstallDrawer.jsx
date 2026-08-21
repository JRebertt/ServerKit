import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    Box, Share2, Database, Rocket, Eye, EyeOff, RefreshCw, Copy, ShieldAlert,
    CheckCircle2, HardDrive, RotateCw, Terminal,
} from 'lucide-react';
import api from '../../services/api';
import { Drawer, SegControl } from '@/components/ds';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { useToast } from '../../contexts/ToastContext';
import EngineGlyph from './EngineGlyph';
import { copyToClipboard } from '@/utils/clipboard';
import { useTranslation } from 'react-i18next';
import {
    engineMeta, engineVersions, generatePassword, partitionVariables, seedVariables,
    singular, slugifyIdent, slugifyService,
} from './engineHelpers';

// "Install <engine>" — the configure half of the install flow.
//
// The form is driven by the template's own `variables[]`, not by a fixed set of
// fields: `type: password` gets the generate/reveal/copy control, `type: port`
// gets a port field, `hidden` variables carry their defaults without a field,
// and `required` is honoured. That is what lets a brand-new engine template
// install with no change here.
//
// Two variables are promoted out of that generic list into purpose-built
// controls because the engine block names them: `admin_password_var` becomes
// the admin-credentials panel, `database_var` becomes "create a database now".
//
// Installing pulls an image, claims a port and writes a data volume, so every
// consequence is on screen before the button — and the public-exposure warning
// is not a matter of taste: it shows whenever the toggle is on.

function SecretRow({ password, onRegenerate, disabled }) {
    const { t } = useTranslation();
    const toast = useToast();
    const [revealed, setRevealed] = useState(false);

    const copy = () => {
        copyToClipboard(password).then((ok) => (ok
            ? toast.success(t('app.engineInstallDrawer.passwordCopied', 'Password copied'))
            : toast.error(t('app.engineInstallDrawer.couldNotCopyThePassword', 'Could not copy the password'))));
    };

    return (
        <div className="dbx-secret">
            <span className="dbx-secret__value">{revealed ? password : '•'.repeat(20)}</span>
            <span className="dbx-secret__actions">
                <button
                    type="button"
                    className="dbx-icon-xs"
                    onClick={() => setRevealed((r) => !r)}
                    aria-label={revealed ? t('app.engineInstallDrawer.hidePassword', 'Hide password') : t('app.engineInstallDrawer.revealPassword', 'Reveal password')}
                    title={revealed ? t('app.engineInstallDrawer.hide', 'Hide') : t('app.engineInstallDrawer.reveal', 'Reveal')}
                >
                    {revealed ? <EyeOff size={13} aria-hidden="true" /> : <Eye size={13} aria-hidden="true" />}
                </button>
                {onRegenerate && (
                    <button
                        type="button"
                        className="dbx-icon-xs"
                        onClick={() => { onRegenerate(); setRevealed(true); }}
                        disabled={disabled}
                        aria-label={t('app.engineInstallDrawer.generateANewPassword', 'Generate a new password')}
                        title={t('app.engineInstallDrawer.regenerate', 'Regenerate')}
                    >
                        <RefreshCw size={13} aria-hidden="true" />
                    </button>
                )}
                <button
                    type="button"
                    className="dbx-icon-xs"
                    onClick={copy}
                    aria-label={t('app.engineInstallDrawer.copyPasswordToClipboard', 'Copy password to clipboard')}
                    title={t('app.engineInstallDrawer.copy', 'Copy')}
                >
                    <Copy size={13} aria-hidden="true" />
                </button>
            </span>
        </div>
    );
}

// One template variable, rendered from its own declaration.
function VariableField({ variable, value, onChange }) {
    const { t } = useTranslation();
    const id = `dbx-var-${variable.name}`;
    return (
        <div className="dbx-field">
            <label className="dbx-field__label" htmlFor={id}>
                {variable.name}
                {variable.required && ' *'}
            </label>
            {variable.options ? (
                <select
                    id={id}
                    value={value ?? ''}
                    onChange={(e) => onChange(e.target.value)}
                    required={variable.required}
                >
                    <option value="">{t('app.engineInstallDrawer.select', 'Select…')}</option>
                    {variable.options.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
                </select>
            ) : (
                <Input
                    id={id}
                    type={variable.type === 'port' ? 'number' : 'text'}
                    inputMode={variable.type === 'port' ? 'numeric' : undefined}
                    value={value ?? ''}
                    onChange={(e) => onChange(e.target.value)}
                    placeholder={variable.default != null ? String(variable.default) : ''}
                    required={variable.required}
                />
            )}
            {variable.description && <p className="dbx-field-hint">{variable.description}</p>}
        </div>
    );
}

export default function EngineInstallDrawer({ entry, open, onOpenChange, onInstalled }) {
    const { t } = useTranslation();
    const toast = useToast();
    const navigate = useNavigate();

    // The list endpoint may carry a summary; the detail endpoint is the one that
    // reliably carries `variables[]`. Fail soft — a summary is still installable.
    const [template, setTemplate] = useState(entry);
    const [name, setName] = useState('');
    const [version, setVersion] = useState('');
    const [vars, setVars] = useState({});
    const [password, setPassword] = useState('');
    const [initialDb, setInitialDb] = useState('');
    const [port, setPort] = useState('');
    const [expose, setExpose] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [suggestedPort, setSuggestedPort] = useState(null);
    // Set once the install is accepted — credentials are surfaced exactly once.
    const [result, setResult] = useState(null);

    useEffect(() => {
        if (!entry) return undefined;
        let cancelled = false;

        const apply = (tpl) => {
            if (cancelled) return;
            const tplMeta = engineMeta(tpl);
            const tplParts = partitionVariables(tpl);
            const versions = engineVersions(tpl);
            setTemplate(tpl);
            setName(slugifyService(tpl.id || tpl.name));
            setVersion(versions[0] || '');
            setVars(seedVariables(tpl));
            setPassword(tplParts.passwordVar?.default || generatePassword());
            setInitialDb(tplParts.databaseVar?.default ? String(tplParts.databaseVar.default) : '');
            setPort(String(tplParts.portVar?.default ?? tplMeta.default_port ?? ''));
            setExpose(false);
            setError('');
            setSuggestedPort(null);
            setResult(null);
        };

        apply(entry);
        api.getTemplate(entry.id)
            .then((res) => {
                const full = res?.template;
                if (full) apply({ ...entry, ...full, engine: full.engine || entry.engine });
            })
            .catch(() => { /* the summary we already applied is enough to install */ });

        return () => { cancelled = true; };
    }, [entry]);

    const meta = engineMeta(template);
    const parts = useMemo(() => partitionVariables(template), [template]);
    const versionOptions = useMemo(
        () => engineVersions(template).map((v) => ({ value: v, label: v })),
        [template],
    );

    if (!entry || !template) return null;

    const unitOne = singular(meta.unit);
    const dbNoun = unitOne === 'key' ? 'namespace' : 'database';

    function setVar(varName, value) {
        setVars((prev) => ({ ...prev, [varName]: value }));
    }

    async function submit(event) {
        event.preventDefault();
        setError('');
        setSuggestedPort(null);
        setBusy(true);
        try {
            const payload = {
                template_id: template.id,
                instance_name: slugifyService(name),
                // The backend owns the bind address so that a stray `variables`
                // entry can never quietly override private-by-default.
                expose_public: expose,
                variables: { ...vars },
            };
            // Only offered when the template actually declares more than one —
            // sending a version to a template with no image-tag variable is an
            // error, not a no-op.
            if (version && versionOptions.length > 1) payload.version = version;
            if (parts.passwordVar) payload.variables[parts.passwordVar.name] = password;

            // Both of these are top-level: the backend maps them onto the
            // variables the engine block names.
            const db = slugifyIdent(initialDb);
            if (db && parts.databaseVar) payload.initial_database = db;

            const parsedPort = Number.parseInt(port, 10);
            if (Number.isFinite(parsedPort) && parsedPort > 0) payload.port = parsedPort;

            const res = await api.installDatabaseEngine(payload);
            const jobId = res.job_id || res.deploy_job_id || res.job?.id || null;
            // The pipeline may or may not hand back the app row; the caller
            // refreshes either way, so a missing one is not an error.
            const app = res.app || res.application || null;

            toast.success(t('app.engineInstallDrawer.installing', 'Installing {{name}}', { name: template.name }));
            onInstalled?.(app);

            // The admin password is shown once. Navigating straight to the deploy
            // console would take it off screen before it could be copied, so when
            // there is a secret the console is one click away instead of zero.
            if (parts.passwordVar) {
                setResult({ app, jobId, secret: password, warning: res.warning || null });
            } else {
                onOpenChange(false);
                if (jobId) navigate(`/deployments/${jobId}`);
            }
        } catch (err) {
            setError(err.message || 'Failed to start the install');
            if (err.data?.suggested_port) setSuggestedPort(err.data.suggested_port);
        } finally {
            setBusy(false);
        }
    }

    function finish() {
        const jobId = result?.jobId;
        setResult(null);
        onOpenChange(false);
        if (jobId) navigate(`/deployments/${jobId}`);
    }

    return (
        <Drawer
            flush
            open={open}
            onOpenChange={(next) => { if (!next) setResult(null); onOpenChange(next); }}
            title={result ? t('app.engineInstallDrawer.isInstalling', '{{name}} is installing', { name: template.name }) : t('app.engineInstallDrawer.install', 'Install {{name}}', { name: template.name })}
            subtitle={[meta.family, template.id, template.version ? `v${template.version}` : null]
                .filter(Boolean).join(' · ')}
            icon={<EngineGlyph entry={template} size={20} />}
            width={520}
            className="dbx-drawer"
        >
            {result ? (
                <div className="dbx-drawer__shell">
                    <div className="dbx-drawer__scroll">
                        <div className="dbx-result-lead">
                            <CheckCircle2 size={16} aria-hidden="true" />
                            <span>
                                {t('app.engineInstallDrawer.theDeployPipelineIsPullingThe', 'The deploy pipeline is pulling the image and provisioning the volume. The engine joins the tree once it reports healthy.')}
                            </span>
                        </div>

                        <dl className="dbx-kv">
                            <div className="dbx-kv__row">
                                <dt>{t('app.engineInstallDrawer.service', 'Service')}</dt>
                                <dd className="dbx-kv__mono">{result.app?.name || slugifyService(name)}</dd>
                            </div>
                            {meta.admin_user && (
                                <div className="dbx-kv__row">
                                    <dt>{t('app.engineInstallDrawer.adminUser', 'Admin user')}</dt>
                                    <dd className="dbx-kv__mono">{meta.admin_user}</dd>
                                </div>
                            )}
                            <div className="dbx-kv__row">
                                <dt>{t('app.engineInstallDrawer.password', 'Password')}</dt>
                                <dd><SecretRow password={result.secret} /></dd>
                            </div>
                        </dl>
                        <p className="dbx-field-hint">
                            {t('app.engineInstallDrawer.copyThePasswordNowItIs', 'Copy the password now — it is stored in ServerKit\'s secret store and is not shown again.')}
                        </p>
                        {result.warning && (
                            <p className="dbx-warn-line">
                                <ShieldAlert size={14} aria-hidden="true" />
                                {result.warning}
                            </p>
                        )}
                    </div>
                    <footer className="dbx-drawer__foot">
                        <Button type="button" onClick={finish}>
                            {result.jobId
                                ? <><Terminal size={15} aria-hidden="true" /> {t('app.engineInstallDrawer.openInstallLog', 'Open install log')}</>
                                : 'Done'}
                        </Button>
                    </footer>
                </div>
            ) : (
                <form className="dbx-drawer__shell" onSubmit={submit}>
                    <div className="dbx-drawer__scroll">
                        {error && (
                            <div className="error-message">
                                {error}
                                {suggestedPort && (
                                    <>
                                        {' '}
                                        <button
                                            type="button"
                                            className="dbx-inline-link"
                                            onClick={() => { setPort(String(suggestedPort)); setError(''); }}
                                        >
                                            {t('app.engineInstallDrawer.usePort', 'Use port')} {suggestedPort}
                                        </button>
                                    </>
                                )}
                            </div>
                        )}

                        {template.description && (
                            <p className="dbx-drawer__lead">{template.description}</p>
                        )}

                        {versionOptions.length > 1 && (
                            <div className="dbx-field">
                                <span className="dbx-field__label">{t('app.engineInstallDrawer.version', 'Version')}</span>
                                <SegControl options={versionOptions} value={version} onChange={setVersion} />
                            </div>
                        )}

                        <div className="dbx-field">
                            <label className="dbx-field__label" htmlFor="dbx-eng-name">{t('app.engineInstallDrawer.instanceName', 'Instance name')}</label>
                            <div className="dbx-input">
                                <Box size={15} aria-hidden="true" />
                                <input
                                    id="dbx-eng-name"
                                    type="text"
                                    value={name}
                                    onChange={(e) => setName(slugifyService(e.target.value))}
                                    minLength={2}
                                    required
                                />
                            </div>
                            <p className="dbx-field-hint">
                                {t('app.engineInstallDrawer.namesTheServiceItsContainerAnd', 'Names the service, its container and its data volume.')}
                            </p>
                        </div>

                        {(parts.portVar || meta.default_port != null) && (
                            <div className="dbx-field">
                                <label className="dbx-field__label" htmlFor="dbx-eng-port">{t('app.engineInstallDrawer.port', 'Port')}</label>
                                <div className="dbx-input">
                                    <Share2 size={15} aria-hidden="true" />
                                    <input
                                        id="dbx-eng-port"
                                        type="text"
                                        inputMode="numeric"
                                        value={port}
                                        onChange={(e) => setPort(e.target.value.replace(/\D/g, ''))}
                                    />
                                </div>
                                {parts.portVar?.description && (
                                    <p className="dbx-field-hint">{parts.portVar.description}</p>
                                )}
                            </div>
                        )}

                        {parts.visible.map((variable) => (
                            <VariableField
                                key={variable.name}
                                variable={variable}
                                value={vars[variable.name]}
                                onChange={(value) => setVar(variable.name, value)}
                            />
                        ))}

                        {(parts.passwordVar || meta.admin_user) && (
                            <div className="dbx-field">
                                <span className="dbx-field__label">{t('app.engineInstallDrawer.adminCredentials', 'Admin credentials')}</span>
                                <dl className="dbx-kv">
                                    {meta.admin_user && (
                                        <div className="dbx-kv__row">
                                            <dt>{t('app.engineInstallDrawer.user', 'User')}</dt>
                                            <dd className="dbx-kv__mono">{meta.admin_user}</dd>
                                        </div>
                                    )}
                                    {parts.passwordVar && (
                                        <div className="dbx-kv__row">
                                            <dt>{t('app.engineInstallDrawer.password2', 'Password')}</dt>
                                            <dd>
                                                <SecretRow
                                                    password={password}
                                                    disabled={busy}
                                                    onRegenerate={() => setPassword(generatePassword())}
                                                />
                                            </dd>
                                        </div>
                                    )}
                                </dl>
                                {parts.passwordVar && (
                                    <p className="dbx-field-hint">
                                        {t('app.engineInstallDrawer.shownOnceStoredInServerkitS', 'Shown once. Stored in ServerKit\'s secret store — never in a log or a second API response.')}
                                    </p>
                                )}
                            </div>
                        )}

                        {/* Only when the engine block names a variable to seed
                            it — offering the field otherwise would promise a
                            database the template has no way to create. */}
                        {parts.databaseVar && (
                            <div className="dbx-field">
                                <label className="dbx-field__label" htmlFor="dbx-eng-initdb">
                                    {t('app.engineInstallDrawer.createA', 'Create a')} {dbNoun} now
                                    <span className="dbx-field__optional"> {t('app.engineInstallDrawer.optional', '· optional')}</span>
                                </label>
                                <div className="dbx-input">
                                    <Database size={15} aria-hidden="true" />
                                    <input
                                        id="dbx-eng-initdb"
                                        type="text"
                                        placeholder="app_prod"
                                        value={initialDb}
                                        onChange={(e) => setInitialDb(e.target.value)}
                                    />
                                </div>
                                <p className="dbx-field-hint">
                                    {t('app.engineInstallDrawer.createdAsSoonAsTheEngine', 'Created as soon as the engine passes its health check.')}
                                </p>
                            </div>
                        )}

                        <div className="dbx-field">
                            <span className="dbx-field__label">{t('app.engineInstallDrawer.options', 'Options')}</span>
                            <div className="dbx-optlist">
                                <div className="dbx-opt-row">
                                    <div className="dbx-opt-row__text">
                                        <span className="dbx-opt-row__title">{t('app.engineInstallDrawer.exposeOnThePublicNetwork', 'Expose on the public network')}</span>
                                        <span className="dbx-opt-row__sub">
                                            {expose
                                                ? 'The port will be reachable from the internet'
                                                : 'Bound to 127.0.0.1 only (recommended)'}
                                        </span>
                                    </div>
                                    <Switch
                                        checked={expose}
                                        onCheckedChange={setExpose}
                                        aria-label={t('app.engineInstallDrawer.exposeOnThePublicNetwork2', 'Expose on the public network')}
                                    />
                                </div>
                                {meta.data_path && (
                                    <div className="dbx-kv__row">
                                        <dt className="dbx-kv__key">
                                            <HardDrive size={12} aria-hidden="true" /> {t('app.engineInstallDrawer.dataPath', 'Data path')}
                                        </dt>
                                        <dd className="dbx-kv__mono">{meta.data_path}</dd>
                                    </div>
                                )}
                                <div className="dbx-kv__row">
                                    <dt className="dbx-kv__key">
                                        <RotateCw size={12} aria-hidden="true" /> {t('app.engineInstallDrawer.restartPolicy', 'Restart policy')}
                                    </dt>
                                    <dd className="dbx-kv__ok">unless-stopped</dd>
                                </div>
                            </div>
                            {expose && (
                                <p className="dbx-warn-line">
                                    <ShieldAlert size={14} aria-hidden="true" />
                                    {t('app.engineInstallDrawer.publicDatabasePortsAreACommon', 'Public database ports are a common breach vector — prefer the private network or an SSH tunnel, and make sure the firewall only admits the hosts that need it.')}
                                </p>
                            )}
                        </div>
                    </div>

                    <footer className="dbx-drawer__foot">
                        <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                            {t('app.engineInstallDrawer.cancel', 'Cancel')}
                        </Button>
                        <Button type="submit" disabled={busy || !slugifyService(name)}>
                            <Rocket size={15} aria-hidden="true" />
                            {busy ? 'Starting…' : `Install ${template.name}`}
                        </Button>
                    </footer>
                </form>
            )}
        </Drawer>
    );
}
