import { useState, useEffect } from 'react';
import api from '../../services/api';
import {
    Github, FileText, HelpCircle, MessageSquare, Bug, Check, Download, CheckCircle,
    RefreshCw, ExternalLink, Star, X
} from 'lucide-react';
import ServerKitLogo from '../ServerKitLogo';
import { Button } from '@/components/ui/button';
import useSettingFocus from '../../hooks/useSettingFocus';
import { useTranslation } from 'react-i18next';

const STAR_PROMPT_KEY = 'serverkit-star-prompt-dismissed';

const AboutTab = () => {
    const { t } = useTranslation();
    const [version, setVersion] = useState('...');
    const [updateInfo, setUpdateInfo] = useState(null);
    const [checkingUpdate, setCheckingUpdate] = useState(false);
    const [showStarPrompt, setShowStarPrompt] = useState(() => {
        return localStorage.getItem(STAR_PROMPT_KEY) !== 'true';
    });
    const register = useSettingFocus();

    useEffect(() => {
        const fetchVersion = async () => {
            try {
                const data = await api.getVersion();
                setVersion(data.version || '1.0.0');
            } catch (error) {
                setVersion('1.0.0');
            }
        };
        fetchVersion();
    }, []);

    const dismissStarPrompt = () => {
        setShowStarPrompt(false);
        localStorage.setItem(STAR_PROMPT_KEY, 'true');
    };

    const checkForUpdate = async () => {
        setCheckingUpdate(true);
        try {
            const data = await api.checkUpdate();
            setUpdateInfo(data);
        } catch (error) {
            setUpdateInfo({ error: 'Failed to check for updates' });
        }
        setCheckingUpdate(false);
    };

    return (
        <div className="settings-section">
            <div className="section-header">
                <h2>{t('app.aboutTab.aboutServerkit', 'About ServerKit')}</h2>
                <p>{t('app.aboutTab.serverManagementMadeSimple', 'Server management made simple')}</p>
            </div>

            <div {...register('about-version', 'about-card')}>
                <div className="about-logo">
                    <ServerKitLogo width={64} height={64} />
                </div>
                <h3>{t('common.labels.serverKit', 'ServerKit')}</h3>
                <p className="version">{t('common.labels.version', 'Version')} {version}</p>
                <p className="description">
                    {t('app.aboutTab.aModernLightweightServerManagementPanel', 'A modern, lightweight server management panel for managing web applications, databases, domains, and more. Built with Flask and React.')}
                </p>

                <div className="update-check">
                    {!updateInfo ? (
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={checkForUpdate}
                            disabled={checkingUpdate}
                        >
                            {checkingUpdate ? (
                                <><RefreshCw size={14} className="spinning" /> {t('common.checking', 'Checking…')}</>
                            ) : (
                                <><Download size={14} /> {t('app.aboutTab.checkForUpdates', 'Check for Updates')}</>
                            )}
                        </Button>
                    ) : updateInfo.error ? (
                        <div className="update-status error">
                            <span>{updateInfo.error}</span>
                            <button type="button" className="btn-link" onClick={checkForUpdate}>{t('common.actions.retry', 'Retry')}</button>
                        </div>
                    ) : updateInfo.update_available ? (
                        <div className="update-status available">
                            <Download size={16} />
                            <span>{t('app.aboutTab.updateAvailable', 'Update available:')} <strong>v{updateInfo.latest_version}</strong></span>
                            <a
                                href={updateInfo.release_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="btn btn-accent btn-sm"
                            >
                                {t('app.aboutTab.viewRelease', 'View Release')} <ExternalLink size={12} />
                            </a>
                        </div>
                    ) : (
                        <div className="update-status current">
                            <CheckCircle size={16} />
                            <span>{t('app.aboutTab.youReUpToDate', 'You\'re up to date!')}</span>
                        </div>
                    )}
                </div>
            </div>

            {showStarPrompt && (
                <div className="star-prompt-card">
                    <button type="button" className="dismiss-btn" onClick={dismissStarPrompt} title={t('common.actions.dismiss', 'Dismiss')}>
                        <X size={16} />
                    </button>
                    <div className="star-icon">
                        <Star size={24} />
                    </div>
                    <div className="star-content">
                        <h4>{t('app.aboutTab.enjoyingServerkit', 'Enjoying ServerKit?')}</h4>
                        <p>{t('app.aboutTab.ifYouFindServerkitUsefulConsider', 'If you find ServerKit useful, consider starring the repository on GitHub. It helps others discover the project!')}</p>
                        <a
                            href="https://github.com/jhd3197/ServerKit"
                            target="_blank"
                            rel="noopener noreferrer"
                            className="btn btn-accent"
                        >
                            <Star size={16} />
                            {t('app.aboutTab.starOnGithub', 'Star on GitHub')}
                        </a>
                    </div>
                </div>
            )}

            <div className="settings-card">
                <h3>{t('app.aboutTab.features', 'Features')}</h3>
                <ul className="feature-list">
                    <li>
                        <Check size={16} />
                        {t('app.aboutTab.applicationManagementPhpPythonNodeJs', 'Application Management (PHP, Python, Node.js, Docker)')}
                    </li>
                    <li>
                        <Check size={16} />
                        {t('app.aboutTab.domainSslCertificateManagement', 'Domain & SSL Certificate Management')}
                    </li>
                    <li>
                        <Check size={16} />
                        {t('app.aboutTab.databaseManagementMysqlPostgresql', 'Database Management (MySQL, PostgreSQL)')}
                    </li>
                    <li>
                        <Check size={16} />
                        {t('app.aboutTab.dockerContainerManagement', 'Docker Container Management')}
                    </li>
                    <li>
                        <Check size={16} />
                        {t('app.aboutTab.systemMonitoringAlerts', 'System Monitoring & Alerts')}
                    </li>
                    <li>
                        <Check size={16} />
                        {t('app.aboutTab.automatedBackups', 'Automated Backups')}
                    </li>
                    <li>
                        <Check size={16} />
                        {t('app.aboutTab.gitDeploymentWithWebhooks', 'Git Deployment with Webhooks')}
                    </li>
                </ul>
            </div>

            <div {...register('about-links', 'settings-card')}>
                <h3>{t('app.aboutTab.links', 'Links')}</h3>
                <div className="link-list">
                    <a href="https://github.com/jhd3197/ServerKit" target="_blank" rel="noopener noreferrer" className="link-item">
                        <Github size={18} />
                        {t('app.aboutTab.githubRepository', 'GitHub Repository')}
                    </a>
                    <a href="https://github.com/jhd3197/ServerKit#readme" target="_blank" rel="noopener noreferrer" className="link-item">
                        <FileText size={18} />
                        {t('app.aboutTab.documentation', 'Documentation')}
                    </a>
                    <a href="https://github.com/jhd3197/ServerKit/issues" target="_blank" rel="noopener noreferrer" className="link-item">
                        <HelpCircle size={18} />
                        {t('app.aboutTab.supportIssues', 'Support & Issues')}
                    </a>
                    <a href="https://github.com/jhd3197/ServerKit/discussions" target="_blank" rel="noopener noreferrer" className="link-item">
                        <MessageSquare size={18} />
                        {t('app.aboutTab.discussions', 'Discussions')}
                    </a>
                    <a href="https://github.com/jhd3197/ServerKit/issues/new" target="_blank" rel="noopener noreferrer" className="link-item">
                        <Bug size={18} />
                        {t('app.aboutTab.reportABug', 'Report a Bug')}
                    </a>
                </div>
            </div>

            <div className="settings-card">
                <h3>{t('app.aboutTab.license', 'License')}</h3>
                <p className="license-text">
                    {t('app.aboutTab.serverkitIsOpenSourceSoftwareLicensed', 'ServerKit is open source software licensed under the MIT License.')}
                </p>
            </div>
        </div>
    );
};

export default AboutTab;
