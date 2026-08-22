import { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import api from '../../services/api';
import Modal from '@/components/Modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { EngineIcon } from '../icons/DatabaseBrands';
import { ENGINE_META } from './dbAdapter';
import { useTranslation } from 'react-i18next';

// Create / credentials modals for the explorer. Logic is unchanged from the
// original Databases page; the explorer wires them to its toolbar and tree.
// Each modal component is mounted only while open, so Modal `open` is constant.
// The submit button stays inside <form>, so actions live in the body (not the
// Modal footer slot).

function CredentialsResult({ title, rows, onDone }) {
    const { t } = useTranslation();
    return (
        <Modal open onClose={onDone} title={title}>
            <div className="credentials-box">
                <p>{t('app.modals.saveTheseCredentialsThePasswordWon', 'Save these credentials — the password won\'t be shown again.')}</p>
                {rows.map(([label, value]) => (
                    <div className="credential-item" key={label}>
                        <label>{label}:</label>
                        <code>{value}</code>
                    </div>
                ))}
            </div>
            <div className="modal-actions">
                <Button onClick={onDone}>{t('common.actions.done', 'Done')}</Button>
            </div>
        </Modal>
    );
}

// One "New database" modal for every engine the panel can create into, rather
// than one modal per engine. It adds two things the old pair never surfaced:
//
//  * an engine picker, with a route out to the engine catalog when the engine
//    you want isn't installed yet;
//  * "Attach to application", which sends `application_id` — the create
//    endpoints have always accepted it, the UI simply never offered it, so
//    every database created here was born unowned.
//
// Only host MySQL / PostgreSQL accept a create call today. Engines installed
// from the catalog run as their own service and are reached through their own
// client, so listing them here as pickable would be a promise we can't keep.
const CREATABLE_ENGINES = ['mysql', 'postgresql'];

function EnginePicker({ value, onChange, status, onInstallEngine }) {
    const { t } = useTranslation();
    return (
        <div className="dbx-eng-pick">
            {CREATABLE_ENGINES.map((engine) => {
                const running = Boolean(status?.[engine]?.installed && status?.[engine]?.running);
                return (
                    <button
                        key={engine}
                        type="button"
                        className={`dbx-eng-opt${value === engine ? ' is-on' : ''}`}
                        onClick={() => onChange(engine)}
                        disabled={!running}
                        title={running ? undefined : t('app.modals.isNotRunning', '{{label}} is not running', { label: ENGINE_META[engine].label })}
                    >
                        <span className={`dbx-eng-opt__ico is-${engine}`}>
                            <EngineIcon engine={engine} size={16} />
                        </span>
                        <span className="dbx-eng-opt__text">
                            <span className="dbx-eng-opt__name">{ENGINE_META[engine].label}</span>
                            <span className="dbx-eng-opt__sub">{running ? 'running' : 'not running'}</span>
                        </span>
                    </button>
                );
            })}
            {onInstallEngine && (
                <button
                    type="button"
                    className="dbx-eng-opt dbx-eng-opt--ghost"
                    onClick={onInstallEngine}
                >
                    <span className="dbx-eng-opt__ico"><Plus size={16} aria-hidden="true" /></span>
                    <span className="dbx-eng-opt__text">
                        <span className="dbx-eng-opt__name">{t('app.modals.installAnEngine', 'Install an engine')}</span>
                        <span className="dbx-eng-opt__sub">{t('app.modals.fromTheTemplateCatalog', 'from the template catalog')}</span>
                    </span>
                </button>
            )}
        </div>
    );
}

export function CreateDatabaseModal({ engine: initialEngine = 'mysql', status, onClose, onCreated, onInstallEngine }) {
    const { t } = useTranslation();
    const [engine, setEngine] = useState(initialEngine);
    const [formData, setFormData] = useState({
        name: '', charset: 'utf8mb4', collation: 'utf8mb4_unicode_ci', encoding: 'UTF8', create_user: true,
    });
    const [applicationId, setApplicationId] = useState('');
    const [apps, setApps] = useState([]);
    const [appsLoading, setAppsLoading] = useState(true);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [createdInfo, setCreatedInfo] = useState(null);

    // Attaching is optional, so a failed app lookup must not block the create —
    // the selector just stays empty.
    useEffect(() => {
        let cancelled = false;
        api.getApps()
            .then((d) => { if (!cancelled) setApps(d.apps || []); })
            .catch(() => { if (!cancelled) setApps([]); })
            .finally(() => { if (!cancelled) setAppsLoading(false); });
        return () => { cancelled = true; };
    }, []);

    const isMySQL = engine === 'mysql';

    async function handleSubmit(e) {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            const payload = isMySQL
                ? { name: formData.name, charset: formData.charset, collation: formData.collation, create_user: formData.create_user }
                : { name: formData.name, encoding: formData.encoding, create_user: formData.create_user };
            if (applicationId) payload.application_id = Number(applicationId);

            const result = isMySQL
                ? await api.createMySQLDatabase(payload)
                : await api.createPostgreSQLDatabase(payload);

            if (result.success) {
                if (result.password) setCreatedInfo({ database: formData.name, user: result.user, password: result.password });
                else { onCreated(); onClose(); }
            }
        } catch (err) {
            setError(err.message || 'Failed to create database');
        } finally {
            setLoading(false);
        }
    }

    if (createdInfo) {
        const attached = apps.find((a) => String(a.id) === String(applicationId));
        return (
            <CredentialsResult
                title={t('app.modals.databaseCreated', 'Database created')}
                rows={[
                    ['Database', createdInfo.database],
                    ['Username', createdInfo.user],
                    ['Password', createdInfo.password],
                    ...(attached ? [['Attached to', attached.name]] : []),
                ]}
                onDone={() => { onCreated(); onClose(); }}
            />
        );
    }

    return (
        <Modal open onClose={onClose} title={t('app.modals.newDatabase', 'New database')}>
            {error && <div className="error-message">{error}</div>}
            <form onSubmit={handleSubmit}>
                <div className="form-group">
                    <label>{t('app.modals.engine', 'Engine')}</label>
                    <EnginePicker
                        value={engine}
                        onChange={setEngine}
                        status={status}
                        onInstallEngine={onInstallEngine ? () => { onClose(); onInstallEngine(); } : null}
                    />
                </div>

                <div className="form-group">
                    <label>{t('app.modals.databaseName', 'Database name *')}</label>
                    <Input type="text" value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })} placeholder="my_database" required pattern="[a-zA-Z0-9_]+" autoFocus />
                </div>

                {isMySQL ? (
                    <div className="form-row">
                        <div className="form-group">
                            <label>{t('app.modals.characterSet', 'Character set')}</label>
                            <select value={formData.charset} onChange={(e) => setFormData({ ...formData, charset: e.target.value })}>
                                <option value="utf8mb4">utf8mb4</option>
                                <option value="utf8">utf8</option>
                                <option value="latin1">latin1</option>
                            </select>
                        </div>
                        <div className="form-group">
                            <label>{t('app.modals.collation', 'Collation')}</label>
                            <select value={formData.collation} onChange={(e) => setFormData({ ...formData, collation: e.target.value })}>
                                <option value="utf8mb4_unicode_ci">utf8mb4_unicode_ci</option>
                                <option value="utf8mb4_general_ci">utf8mb4_general_ci</option>
                                <option value="utf8_general_ci">utf8_general_ci</option>
                            </select>
                        </div>
                    </div>
                ) : (
                    <div className="form-group">
                        <label>{t('app.modals.encoding', 'Encoding')}</label>
                        <select value={formData.encoding} onChange={(e) => setFormData({ ...formData, encoding: e.target.value })}>
                            <option value="UTF8">UTF8</option>
                            <option value="LATIN1">LATIN1</option>
                            <option value="SQL_ASCII">SQL_ASCII</option>
                        </select>
                    </div>
                )}

                <div className="form-group">
                    <label htmlFor="dbx-attach-app">{t('app.modals.attachToApplication', 'Attach to application')}</label>
                    <select
                        id="dbx-attach-app"
                        value={applicationId}
                        onChange={(e) => setApplicationId(e.target.value)}
                        disabled={appsLoading}
                    >
                        <option value="">{t('app.modals.none', '— None —')}</option>
                        {apps.map((app) => <option key={app.id} value={app.id}>{app.name}</option>)}
                    </select>
                    <span className="form-help">
                        {appsLoading
                            ? 'Loading applications…'
                            : 'Optional. An attached database is listed on the application and is cleaned up with it.'}
                    </span>
                </div>

                <div className="form-group">
                    <label className="checkbox-label">
                        <input type="checkbox" checked={formData.create_user} onChange={(e) => setFormData({ ...formData, create_user: e.target.checked })} />
                        {t('app.modals.createUserWithSameNameAnd', 'Create user with same name and full privileges')}
                    </label>
                </div>
                <div className="modal-actions">
                    <Button type="button" variant="outline" onClick={onClose}>{t('common.actions.cancel', 'Cancel')}</Button>
                    <Button type="submit" disabled={loading}>{loading ? 'Creating…' : 'Create database'}</Button>
                </div>
            </form>
        </Modal>
    );
}

export function CreateMySQLUserModal({ databases, onClose, onCreated }) {
    const { t } = useTranslation();
    const [formData, setFormData] = useState({ username: '', password: '', host: 'localhost', database: '', privileges: 'ALL' });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [createdInfo, setCreatedInfo] = useState(null);

    async function generatePassword() {
        try {
            const result = await api.generateDatabasePassword();
            setFormData({ ...formData, password: result.password });
        } catch (err) {
            console.error('Failed to generate password:', err);
        }
    }

    async function handleSubmit(e) {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            const result = await api.createMySQLUser(formData);
            if (result.success) setCreatedInfo({ username: formData.username, password: result.password, host: formData.host });
        } catch (err) {
            setError(err.message || 'Failed to create user');
        } finally {
            setLoading(false);
        }
    }

    if (createdInfo) {
        return (
            <CredentialsResult
                title={t('app.modals.userCreated', 'User created')}
                rows={[['Username', createdInfo.username], ['Password', createdInfo.password], ['Host', createdInfo.host]]}
                onDone={() => { onCreated(); onClose(); }}
            />
        );
    }

    return (
        <Modal open onClose={onClose} title={t('app.modals.createMysqlUser', 'Create MySQL user')}>
            {error && <div className="error-message">{error}</div>}
            <form onSubmit={handleSubmit}>
                <div className="form-group">
                    <label>{t('app.modals.username', 'Username *')}</label>
                    <Input type="text" value={formData.username} onChange={(e) => setFormData({ ...formData, username: e.target.value })} placeholder="db_user" required autoFocus />
                </div>
                <div className="form-group">
                    <label>{t('common.labels.password', 'Password')}</label>
                    <div className="input-with-button">
                        <Input type="text" value={formData.password} onChange={(e) => setFormData({ ...formData, password: e.target.value })} placeholder={t('app.modals.leaveEmptyToAutoGenerate', 'Leave empty to auto-generate')} />
                        <Button type="button" variant="outline" size="sm" onClick={generatePassword}>{t('app.modals.generate', 'Generate')}</Button>
                    </div>
                </div>
                <div className="form-group">
                    <label>{t('app.modals.host', 'Host')}</label>
                    <select value={formData.host} onChange={(e) => setFormData({ ...formData, host: e.target.value })}>
                        <option value="localhost">localhost</option>
                        <option value="%">{t('app.modals.anyHost', '% (any host)')}</option>
                        <option value="127.0.0.1">127.0.0.1</option>
                    </select>
                </div>
                <div className="form-group">
                    <label>{t('app.modals.grantPrivilegesOnDatabase', 'Grant privileges on database')}</label>
                    <select value={formData.database} onChange={(e) => setFormData({ ...formData, database: e.target.value })}>
                        <option value="">{t('app.modals.none', '— None —')}</option>
                        {databases.map((db) => <option key={db.name} value={db.name}>{db.name}</option>)}
                    </select>
                </div>
                <div className="modal-actions">
                    <Button type="button" variant="outline" onClick={onClose}>{t('common.actions.cancel', 'Cancel')}</Button>
                    <Button type="submit" disabled={loading}>{loading ? 'Creating…' : 'Create user'}</Button>
                </div>
            </form>
        </Modal>
    );
}

export function CreatePostgreSQLUserModal({ databases, onClose, onCreated }) {
    const { t } = useTranslation();
    const [formData, setFormData] = useState({ username: '', password: '', database: '' });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [createdInfo, setCreatedInfo] = useState(null);

    async function generatePassword() {
        try {
            const result = await api.generateDatabasePassword();
            setFormData({ ...formData, password: result.password });
        } catch (err) {
            console.error('Failed to generate password:', err);
        }
    }

    async function handleSubmit(e) {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            const result = await api.createPostgreSQLUser(formData);
            if (result.success) setCreatedInfo({ username: formData.username, password: result.password });
        } catch (err) {
            setError(err.message || 'Failed to create user');
        } finally {
            setLoading(false);
        }
    }

    if (createdInfo) {
        return (
            <CredentialsResult
                title={t('app.modals.userCreated', 'User created')}
                rows={[['Username', createdInfo.username], ['Password', createdInfo.password]]}
                onDone={() => { onCreated(); onClose(); }}
            />
        );
    }

    return (
        <Modal open onClose={onClose} title={t('app.modals.createPostgresqlUser', 'Create PostgreSQL user')}>
            {error && <div className="error-message">{error}</div>}
            <form onSubmit={handleSubmit}>
                <div className="form-group">
                    <label>{t('app.modals.username', 'Username *')}</label>
                    <Input type="text" value={formData.username} onChange={(e) => setFormData({ ...formData, username: e.target.value })} placeholder="db_user" required autoFocus />
                </div>
                <div className="form-group">
                    <label>{t('common.labels.password', 'Password')}</label>
                    <div className="input-with-button">
                        <Input type="text" value={formData.password} onChange={(e) => setFormData({ ...formData, password: e.target.value })} placeholder={t('app.modals.leaveEmptyToAutoGenerate', 'Leave empty to auto-generate')} />
                        <Button type="button" variant="outline" size="sm" onClick={generatePassword}>{t('app.modals.generate', 'Generate')}</Button>
                    </div>
                </div>
                <div className="form-group">
                    <label>{t('app.modals.grantPrivilegesOnDatabase', 'Grant privileges on database')}</label>
                    <select value={formData.database} onChange={(e) => setFormData({ ...formData, database: e.target.value })}>
                        <option value="">{t('app.modals.none', '— None —')}</option>
                        {databases.map((db) => <option key={db.name} value={db.name}>{db.name}</option>)}
                    </select>
                </div>
                <div className="modal-actions">
                    <Button type="button" variant="outline" onClick={onClose}>{t('common.actions.cancel', 'Cancel')}</Button>
                    <Button type="submit" disabled={loading}>{loading ? 'Creating…' : 'Create user'}</Button>
                </div>
            </form>
        </Modal>
    );
}
