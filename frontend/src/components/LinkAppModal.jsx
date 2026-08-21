import { useState, useEffect } from 'react';
import { X, Link2, GitBranch, AlertCircle, Check } from 'lucide-react';
import api from '../services/api';
import Modal from './Modal';
import { useTranslation } from 'react-i18next';

const LinkAppModal = ({ app, onClose, onLinked }) => {
    const { t } = useTranslation();
    const [apps, setApps] = useState([]);
    const [loading, setLoading] = useState(true);
    const [linking, setLinking] = useState(false);
    const [error, setError] = useState('');

    const [selectedAppId, setSelectedAppId] = useState('');
    const [asEnvironment, setAsEnvironment] = useState('development');
    const [tablePrefix, setTablePrefix] = useState('');
    const [propagateCredentials, setPropagateCredentials] = useState(true);

    useEffect(() => {
        loadCompatibleApps();
    }, [app]);

    async function loadCompatibleApps() {
        try {
            const data = await api.getApps();
            // Filter to same type, not already linked, not self
            const compatible = (data.apps || []).filter(a =>
                a.id !== app.id &&
                a.app_type === app.app_type &&
                !a.has_linked_app &&
                a.environment_type === 'standalone'
            );
            setApps(compatible);
        } catch (err) {
            setError('Failed to load applications');
        } finally {
            setLoading(false);
        }
    }

    async function handleLink(e) {
        e.preventDefault();
        if (!selectedAppId) {
            setError('Please select an application to link');
            return;
        }

        setLinking(true);
        setError('');

        try {
            await api.linkApp(app.id, parseInt(selectedAppId), asEnvironment, {
                propagateCredentials,
                tablePrefix: tablePrefix || undefined
            });
            onLinked();
            onClose();
        } catch (err) {
            setError(err.message || 'Failed to link applications');
        } finally {
            setLinking(false);
        }
    }

    const selectedApp = apps.find(a => a.id === parseInt(selectedAppId));

    const envDescriptions = {
        development: 'This app will be the DEVELOPMENT environment',
        production: 'This app will be the PRODUCTION environment',
        staging: 'This app will be the STAGING environment'
    };

    return (
        <Modal open={true} onClose={onClose} title={t('app.linkAppModal.linkApplication', 'Link Application')} className="link-app-modal">
                {error && (
                    <div className="error-message">
                        <AlertCircle size={16} />
                        {error}
                    </div>
                )}

                {loading ? (
                    <div className="modal-loading">{t('app.linkAppModal.loadingCompatibleApps', 'Loading compatible apps...')}</div>
                ) : apps.length === 0 ? (
                    <div className="link-app-empty">
                        <GitBranch size={32} />
                        <h3>{t('app.linkAppModal.noCompatibleApps', 'No Compatible Apps')}</h3>
                        <p>
                            {t('app.linkAppModal.thereAreNoOther', 'There are no other')} {app.app_type} {t('app.linkAppModal.applicationsAvailableToLinkCreateAnother', 'applications available to link. Create another')} {app.app_type} {t('app.linkAppModal.appFirstOrEnsureExistingApps', 'app first, or ensure existing apps are not already linked.')}
                        </p>
                        <button type="button" className="btn btn-secondary" onClick={onClose}>
                            {t('app.linkAppModal.close', 'Close')}
                        </button>
                    </div>
                ) : (
                    <form onSubmit={handleLink}>
                        <div className="link-app-current">
                            <span className="link-app-label">{t('app.linkAppModal.currentApp', 'Current app:')}</span>
                            <span className="link-app-name">{app.name}</span>
                            <span className="app-type-badge">{app.app_type.toUpperCase()}</span>
                        </div>

                        <div className="form-group">
                            <label>{t('app.linkAppModal.linkToApplication', 'Link to Application')}</label>
                            <select
                                value={selectedAppId}
                                onChange={(e) => setSelectedAppId(e.target.value)}
                                required
                            >
                                <option value="">{t('app.linkAppModal.selectAnApplication', 'Select an application...')}</option>
                                {apps.map(a => (
                                    <option key={a.id} value={a.id}>
                                        {a.name} (Port: {a.port || 'N/A'})
                                    </option>
                                ))}
                            </select>
                        </div>

                        <div className="form-group">
                            <label>{t('app.linkAppModal.thisAppWillBe', 'This app will be')}</label>
                            <div className="env-radio-group">
                                {['development', 'production', 'staging'].map(env => (
                                    <label key={env} className={`env-radio-option ${asEnvironment === env ? 'selected' : ''}`}>
                                        <input
                                            type="radio"
                                            name="environment"
                                            value={env}
                                            checked={asEnvironment === env}
                                            onChange={(e) => setAsEnvironment(e.target.value)}
                                        />
                                        <span className={`env-badge env-${env}`}>
                                            {env === 'development' ? 'DEV' : env === 'production' ? 'PROD' : 'STAGING'}
                                        </span>
                                        <span className="env-radio-label">{env.charAt(0).toUpperCase() + env.slice(1)}</span>
                                    </label>
                                ))}
                            </div>
                        </div>

                        {selectedApp && (
                            <div className="link-preview">
                                <div className="link-preview-title">{t('app.linkAppModal.preview', 'Preview')}</div>
                                <div className="link-preview-diagram">
                                    <div className="link-preview-app">
                                        <span className="link-preview-name">{app.name}</span>
                                        <span className={`env-badge env-${asEnvironment}`}>
                                            {asEnvironment === 'development' ? 'DEV' : asEnvironment === 'production' ? 'PROD' : 'STAGING'}
                                        </span>
                                    </div>
                                    <div className="link-preview-connector">
                                        <GitBranch size={16} />
                                    </div>
                                    <div className="link-preview-app">
                                        <span className="link-preview-name">{selectedApp.name}</span>
                                        <span className={`env-badge env-${asEnvironment === 'development' ? 'production' : 'development'}`}>
                                            {asEnvironment === 'development' ? 'PROD' : 'DEV'}
                                        </span>
                                    </div>
                                </div>
                            </div>
                        )}

                        {app.app_type === 'docker' && (
                            <>
                                <div className="form-group">
                                    <label className="checkbox-label">
                                        <input
                                            type="checkbox"
                                            checked={propagateCredentials}
                                            onChange={(e) => setPropagateCredentials(e.target.checked)}
                                        />
                                        <span className="checkbox-custom" />
                                        <span>{t('app.linkAppModal.propagateDatabaseCredentials', 'Propagate database credentials')}</span>
                                    </label>
                                    <span className="form-hint">
                                        {t('app.linkAppModal.copyDatabaseConnectionSettingsFromProduction', 'Copy database connection settings from production to development app')}
                                    </span>
                                </div>

                                {propagateCredentials && (
                                    <div className="form-group">
                                        <label>{t('app.linkAppModal.tablePrefixOptional', 'Table Prefix (optional)')}</label>
                                        <input
                                            type="text"
                                            value={tablePrefix}
                                            onChange={(e) => setTablePrefix(e.target.value)}
                                            placeholder={t('app.linkAppModal.wpDevAutoGeneratedIfEmpty', 'wp_dev_ (auto-generated if empty)')}
                                        />
                                        <span className="form-hint">
                                            {t('app.linkAppModal.differentPrefixAllowsBothAppsTo', 'Different prefix allows both apps to share the same database')}
                                        </span>
                                    </div>
                                )}
                            </>
                        )}

                        <div className="modal-actions">
                            <button type="button" className="btn btn-secondary" onClick={onClose}>
                                {t('app.linkAppModal.cancel', 'Cancel')}
                            </button>
                            <button type="submit" className="btn btn-primary" disabled={linking || !selectedAppId}>
                                {linking ? (
                                    <>{t('app.linkAppModal.linking', 'Linking...')}</>
                                ) : (
                                    <>
                                        <Check size={16} />
                                        {t('app.linkAppModal.linkApps', 'Link Apps')}
                                    </>
                                )}
                            </button>
                        </div>
                    </form>
                )}
        </Modal>
    );
};

export default LinkAppModal;
