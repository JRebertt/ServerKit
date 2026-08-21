import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';
import EmptyState from '../EmptyState';
import { useToast } from '../../contexts/ToastContext';
import { useConfirm } from '../../hooks/useConfirm';
import { InfoList, InfoItem } from '../InfoList';
import BuildpackPreview from '../buildpack/BuildpackPreview';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Pill, statusKind } from '@/components/ds';
import Modal from '@/components/Modal';
import { useTranslation } from 'react-i18next';

const BuildTab = ({ appId, appPath, app }) => {
    const { t } = useTranslation();
    const toast = useToast();
    const { confirm: confirmBuild } = useConfirm();
    const [buildConfig, setBuildConfig] = useState(null);
    const [detection, setDetection] = useState(null);
    const [deployments, setDeployments] = useState([]);
    const [currentDeployment, setCurrentDeployment] = useState(null);
    const [loading, setLoading] = useState(true);
    const [building, setBuilding] = useState(false);
    const [deploying, setDeploying] = useState(false);
    const navigate = useNavigate();
    const [showConfigModal, setShowConfigModal] = useState(false);
    const [showLogsModal, setShowLogsModal] = useState(false);
    const [selectedLog, setSelectedLog] = useState(null);
    const [buildLogs, setBuildLogs] = useState([]);
    const [error, setError] = useState(null);
    const [bpDockerfile, setBpDockerfile] = useState(null);

    // When the app was created from a detected build pack, fetch a read-only
    // preview of the generated Dockerfile for transparency.
    useEffect(() => {
        let active = true;
        if (app?.buildpack_plan) {
            api.generateBuildpack(app.buildpack_plan, app.buildpack_overrides || {}, app.name)
                .then((res) => { if (active) setBpDockerfile(res?.dockerfile || null); })
                .catch(() => {});
        }
        return () => { active = false; };
    }, [app?.buildpack_plan, app?.buildpack_overrides, app?.name]);

    const [configForm, setConfigForm] = useState({
        buildMethod: 'auto',
        dockerfilePath: 'Dockerfile',
        customBuildCmd: '',
        customStartCmd: '',
        cacheEnabled: true,
        timeout: 600,
        keepDeployments: 5
    });

    useEffect(() => {
        loadData();
    }, [appId]);

    async function loadData() {
        try {
            setLoading(true);
            const [configRes, detectRes, deploymentsRes] = await Promise.all([
                api.getBuildConfig(appId),
                api.detectBuildMethod(appId),
                api.getDeployments(appId, 10)
            ]);

            setDetection(detectRes);

            if (configRes.configured) {
                setBuildConfig(configRes.config);
                setConfigForm({
                    buildMethod: configRes.config.build_method || 'auto',
                    dockerfilePath: configRes.config.dockerfile_path || 'Dockerfile',
                    customBuildCmd: configRes.config.custom_build_cmd || '',
                    customStartCmd: configRes.config.custom_start_cmd || '',
                    cacheEnabled: configRes.config.cache_enabled !== false,
                    timeout: configRes.config.timeout || 600,
                    keepDeployments: configRes.config.keep_deployments || 5
                });
            }

            setDeployments(deploymentsRes.deployments || []);
            setCurrentDeployment(deploymentsRes.current);

        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }

    async function handleConfigureBuild(e) {
        e.preventDefault();
        try {
            await api.configureBuild(appId, {
                build_method: configForm.buildMethod,
                dockerfile_path: configForm.dockerfilePath,
                custom_build_cmd: configForm.customBuildCmd || null,
                custom_start_cmd: configForm.customStartCmd || null,
                cache_enabled: configForm.cacheEnabled,
                timeout: configForm.timeout,
                keep_deployments: configForm.keepDeployments
            });
            setShowConfigModal(false);
            toast.success(t('app.buildTab.buildConfigurationSaved', 'Build configuration saved'));
            loadData();
        } catch (err) {
            setError(err.message);
        }
    }

    async function handleBuild(noCache = false) {
        setBuilding(true);
        setError(null);
        try {
            const result = await api.triggerBuild(appId, noCache);
            if (result.success) {
                toast.success(t('app.buildTab.buildCompletedSuccessfully', 'Build completed successfully'));
            } else {
                setError(result.error || 'Build failed');
            }
            loadData();
        } catch (err) {
            setError(err.message);
        } finally {
            setBuilding(false);
        }
    }

    async function handleDeploy(noCache = false) {
        setDeploying(true);
        setError(null);
        try {
            const result = await api.deployApp(appId, { no_cache: noCache });
            if (result?.deploy_job_id) {
                // Async deploy → watch it live on the Deploy Console.
                navigate(`/deployments/${result.deploy_job_id}`);
                return;
            }
            if (result.success) {
                toast.success(t('app.buildTab.deploymentStarted', 'Deployment started'));
            } else {
                setError(result.error || 'Deployment failed');
            }
            loadData();
        } catch (err) {
            setError(err.message);
        } finally {
            setDeploying(false);
        }
    }

    async function handleRollback(version = null) {
        const rollbackMsg = version
            ? `Rollback to version ${version}? This will replace the current deployment.`
            : 'Rollback to previous deployment?';
        const confirmed = await confirmBuild({ titleKey: 'app.buildTab.rollback', title: 'Rollback', message: rollbackMsg, variant: 'warning' });
        if (!confirmed) return;

        setDeploying(true);
        setError(null);
        try {
            const result = await api.rollback(appId, version);
            if (result.success) {
                toast.success(t('app.buildTab.rollbackSuccessful', 'Rollback successful'));
            } else {
                setError(result.error || 'Rollback failed');
            }
            loadData();
        } catch (err) {
            setError(err.message);
        } finally {
            setDeploying(false);
        }
    }

    function formatDuration(seconds) {
        if (!seconds) return '-';
        if (seconds < 60) return `${Math.round(seconds)}s`;
        return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
    }

    if (loading) {
        return <EmptyState loading loadingVariant="form" title={t('app.buildTab.loadingBuildConfiguration', 'Loading build configuration...')} />;
    }

    return (
        <div className="build-tab">
            {error && (
                <div className="alert alert-danger">
                    {error}
                    <button type="button" onClick={() => setError(null)} className="alert-close">&times;</button>
                </div>
            )}

            {detection && (
                <div className="card">
                    <h3>{t('app.buildTab.autoDetectionResults', 'Auto-Detection Results')}</h3>
                    <div className="detection-results">
                        <div className="detection-item">
                            <span className="detection-label">{t('app.buildTab.detectedMethod', 'Detected Method:')}</span>
                            <span className="detection-value">{detection.detected_method || 'None'}</span>
                        </div>
                        {detection.dockerfile_exists && (
                            <div className="detection-item">
                                <span className="detection-label">{t('app.buildTab.dockerfile', 'Dockerfile:')}</span>
                                <span className="detection-value">{t('app.buildTab.found', 'Found')}</span>
                            </div>
                        )}
                        {detection.docker_compose_exists && (
                            <div className="detection-item">
                                <span className="detection-label">{t('app.buildTab.dockerCompose', 'Docker Compose:')}</span>
                                <span className="detection-value">{t('app.buildTab.found2', 'Found')}</span>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {app?.buildpack_plan && (
                <div className="card">
                    <h3>{t('app.buildTab.buildPack', 'Build Pack')}</h3>
                    <BuildpackPreview
                        plan={app.buildpack_plan}
                        dockerfile={bpDockerfile}
                        overrides={app.buildpack_overrides || {}}
                    />
                </div>
            )}

            <div className="card">
                <div className="card-header-row">
                    <h3>{t('app.buildTab.buildConfiguration', 'Build Configuration')}</h3>
                    <Button variant="outline" size="sm" onClick={() => setShowConfigModal(true)}>
                        {t('app.buildTab.configure', 'Configure')}
                    </Button>
                </div>
                {buildConfig ? (
                    <InfoList>
                        <InfoItem label={t('app.buildTab.method', 'Method')} value={buildConfig.build_method} />
                        <InfoItem label={t('app.buildTab.timeout', 'Timeout')} value={`${buildConfig.timeout}s`} />
                    </InfoList>
                ) : (
                    <p className="hint">{t('app.buildTab.noBuildConfigurationClickConfigureTo', 'No build configuration. Click Configure to set up.')}</p>
                )}
                <div className="card-actions">
                    <Button
                        onClick={() => handleDeploy(false)}
                        disabled={deploying || building}
                    >
                        {deploying ? 'Deploying...' : 'Build & Deploy'}
                    </Button>
                    <Button
                        variant="outline"
                        onClick={() => handleBuild(false)}
                        disabled={building || deploying}
                    >
                        {building ? 'Building...' : 'Build Only'}
                    </Button>
                </div>
            </div>

            {deployments.length > 0 && (
                <div className="card">
                    <h3>{t('app.buildTab.deploymentHistory', 'Deployment History')}</h3>
                    <div className="deployments-list">
                        {deployments.map(dep => (
                            <div key={dep.version} className={`deployment-item ${dep.status === 'live' ? 'current' : ''}`}>
                                <div className="deployment-info">
                                    <span className="deployment-version">v{dep.version}</span>
                                    <Pill kind={statusKind(dep.status)}>{dep.status}</Pill>
                                </div>
                                <div className="deployment-meta">
                                    <span>{new Date(dep.created_at).toLocaleString()}</span>
                                    <span>{formatDuration(dep.build_duration)}</span>
                                </div>
                                {dep.status !== 'live' && (
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => handleRollback(dep.version)}
                                        disabled={deploying}
                                    >
                                        {t('app.buildTab.rollback2', 'Rollback')}
                                    </Button>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            <Modal open={showConfigModal} onClose={() => setShowConfigModal(false)} title={t('app.buildTab.buildConfiguration2', 'Build Configuration')}>
                        <form onSubmit={handleConfigureBuild}>
                            <div className="form-group">
                                <label>{t('app.buildTab.buildMethod', 'Build Method')}</label>
                                <select
                                    value={configForm.buildMethod}
                                    onChange={e => setConfigForm({...configForm, buildMethod: e.target.value})}
                                >
                                    <option value="auto">{t('app.buildTab.autoDetect', 'Auto-detect')}</option>
                                    <option value="dockerfile">{t('app.buildTab.dockerfile2', 'Dockerfile')}</option>
                                    <option value="docker-compose">{t('app.buildTab.dockerCompose2', 'Docker Compose')}</option>
                                    <option value="custom">{t('app.buildTab.custom', 'Custom')}</option>
                                </select>
                            </div>
                            {configForm.buildMethod === 'dockerfile' && (
                                <div className="form-group">
                                    <label>{t('app.buildTab.dockerfilePath', 'Dockerfile Path')}</label>
                                    <Input
                                        type="text"
                                        value={configForm.dockerfilePath}
                                        onChange={e => setConfigForm({...configForm, dockerfilePath: e.target.value})}
                                    />
                                </div>
                            )}
                            {configForm.buildMethod === 'custom' && (
                                <>
                                    <div className="form-group">
                                        <label>{t('app.buildTab.buildCommand', 'Build Command')}</label>
                                        <Input
                                            type="text"
                                            value={configForm.customBuildCmd}
                                            onChange={e => setConfigForm({...configForm, customBuildCmd: e.target.value})}
                                            placeholder={t('app.buildTab.npmRunBuild', 'npm run build')}
                                        />
                                    </div>
                                    <div className="form-group">
                                        <label>{t('app.buildTab.startCommand', 'Start Command')}</label>
                                        <Input
                                            type="text"
                                            value={configForm.customStartCmd}
                                            onChange={e => setConfigForm({...configForm, customStartCmd: e.target.value})}
                                            placeholder={t('app.buildTab.npmStart', 'npm start')}
                                        />
                                    </div>
                                </>
                            )}
                            <div className="form-group">
                                <label>{t('app.buildTab.timeoutSeconds', 'Timeout (seconds)')}</label>
                                <Input
                                    type="number"
                                    value={configForm.timeout}
                                    onChange={e => setConfigForm({...configForm, timeout: parseInt(e.target.value)})}
                                />
                            </div>
                            <div className="modal-actions">
                                <Button type="button" variant="outline" onClick={() => setShowConfigModal(false)}>
                                    {t('app.buildTab.cancel', 'Cancel')}
                                </Button>
                                <Button type="submit">
                                    {t('app.buildTab.saveConfiguration', 'Save Configuration')}
                                </Button>
                            </div>
                        </form>
            </Modal>
        </div>
    );
};

export default BuildTab;
