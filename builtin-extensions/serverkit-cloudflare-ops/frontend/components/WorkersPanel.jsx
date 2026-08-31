import { useState, useEffect, useCallback } from 'react';
import { Zap } from 'lucide-react';
import api from '../services/cloudflare';
import { Button, Input, Textarea, Badge, EmptyState, useToast } from 'serverkit-sdk';
import { useTranslation } from 'react-i18next';

const STARTER_SCRIPT = `export default {
  async fetch(request, env, ctx) {
    return new Response("Hello from ServerKit + Cloudflare Workers!", {
      headers: { "content-type": "text/plain" },
    });
  },
};`;

export default function WorkersPanel({ zoneId, isAdmin }) {
    const { t } = useTranslation();
    const toast = useToast();

    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [workers, setWorkers] = useState([]);
    const [routes, setRoutes] = useState([]);

    // Deploy form state
    const [name, setName] = useState('');
    const [code, setCode] = useState(STARTER_SCRIPT);
    const [routePattern, setRoutePattern] = useState('');

    // Tracks any in-flight write so buttons can disable
    const [deploying, setDeploying] = useState(false);
    const [working, setWorking] = useState(false);

    const loadData = useCallback(async () => {
        try {
            const data = await api.getCloudflareWorkers(zoneId);
            setWorkers(data.workers || []);
            setRoutes(data.routes || []);
            setError(null);
        } catch (err) {
            setError(err.message);
        }
    }, [zoneId]);

    useEffect(() => {
        let active = true;
        setLoading(true);
        (async () => {
            try {
                const data = await api.getCloudflareWorkers(zoneId);
                if (!active) return;
                setWorkers(data.workers || []);
                setRoutes(data.routes || []);
                setError(null);
            } catch (err) {
                if (active) setError(err.message);
            } finally {
                if (active) setLoading(false);
            }
        })();
        return () => {
            active = false;
        };
    }, [zoneId]);

    const handleDeploy = async () => {
        setDeploying(true);
        try {
            const res = await api.deployCloudflareWorker(zoneId, {
                name,
                code,
                route_pattern: routePattern || undefined,
            });
            toast.success(t('app.workersPanel.deployedWorker', 'Deployed worker "{{name}}"', { name: name }));
            if (res.route && !res.route.success) {
                toast.error(t('app.workersPanel.workerDeployedButTheRouteFailed', 'Worker deployed, but the route failed: ') + res.route.error);
            }
            setName('');
            setRoutePattern('');
            await loadData();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setDeploying(false);
        }
    };

    const handleDeleteWorker = async (worker) => {
        setWorking(true);
        try {
            await api.deleteCloudflareWorker(zoneId, worker.name);
            await loadData();
            toast.success(t('app.workersPanel.deletedWorker', 'Deleted worker "{{name}}"', { name: worker.name }));
        } catch (err) {
            toast.error(err.message);
        } finally {
            setWorking(false);
        }
    };

    const handleDeleteRoute = async (route) => {
        setWorking(true);
        try {
            await api.deleteCloudflareWorkerRoute(zoneId, route.id);
            await loadData();
            toast.success(t('app.workersPanel.routeRemoved', 'Route removed'));
        } catch (err) {
            toast.error(err.message);
        } finally {
            setWorking(false);
        }
    };

    if (loading) {
        return <div className="cf-workers__loading">{t('app.workersPanel.loadingWorkers', 'Loading workers…')}</div>;
    }

    if (error) {
        return (
            <EmptyState
                icon={Zap}
                title={t('app.workersPanel.workersUnavailable', 'Workers unavailable')}
                description={error}
            />
        );
    }

    const writeDisabled = !isAdmin || working;
    const deployDisabled = !isAdmin || deploying || !name.trim() || !code.trim();

    return (
        <div className="cf-workers">
            {/* Deploy a Worker */}
            <section className="cf-workers__section">
                <h3 className="cf-workers__heading">{t('app.workersPanel.deployAWorker', 'Deploy a Worker')}</h3>

                <div className="cf-workers__field">
                    <label className="cf-workers__label">{t('common.labels.name', 'Name')}</label>
                    <Input
                        value={name}
                        placeholder="my-worker"
                        onChange={(e) => setName(e.target.value)}
                        disabled={!isAdmin || deploying}
                    />
                </div>

                <div className="cf-workers__field">
                    <label className="cf-workers__label">{t('app.workersPanel.code', 'Code')}</label>
                    <Textarea
                        rows={8}
                        className="cf-workers__code"
                        value={code}
                        onChange={(e) => setCode(e.target.value)}
                        disabled={!isAdmin || deploying}
                    />
                </div>

                <div className="cf-workers__field">
                    <label className="cf-workers__label">{t('app.workersPanel.routePatternOptional', 'Route pattern (optional)')}</label>
                    <Input
                        value={routePattern}
                        placeholder="example.com/*"
                        onChange={(e) => setRoutePattern(e.target.value)}
                        disabled={!isAdmin || deploying}
                    />
                    <p className="cf-workers__hint">
                        {t('app.workersPanel.attachesTheWorkerToThisDomain', 'Attaches the worker to this domain so matching traffic runs the script.')}
                    </p>
                </div>

                <div className="cf-workers__actions">
                    <Button onClick={handleDeploy} disabled={deployDisabled}>
                        {t('app.workersPanel.deploy', 'Deploy')}
                    </Button>
                </div>
            </section>

            {/* Deployed workers */}
            <section className="cf-workers__section">
                <h3 className="cf-workers__heading">{t('app.workersPanel.workers', 'Workers (')}{workers.length})</h3>

                {workers.length === 0 ? (
                    <EmptyState
                        icon={Zap}
                        title={t('app.workersPanel.noWorkersDeployed', 'No Workers deployed')}
                        description={t('app.workersPanel.deployYourFirstEdgeScriptAbove', 'Deploy your first edge script above.')}
                    />
                ) : (
                    <ul className="cf-workers__list">
                        {workers.map((worker) => (
                            <li className="cf-workers__item" key={worker.name}>
                                <div className="cf-workers__name">
                                    <code>{worker.name}</code>
                                    {worker.managed && (
                                        <Badge variant="secondary">{t('common.labels.serverKit', 'ServerKit')}</Badge>
                                    )}
                                    {worker.modified_on && (
                                        <span className="cf-workers__meta">
                                            {new Date(worker.modified_on).toLocaleString()}
                                        </span>
                                    )}
                                </div>

                                <div className="cf-workers__item-actions">
                                    <Button
                                        variant="destructive"
                                        size="sm"
                                        onClick={() => handleDeleteWorker(worker)}
                                        disabled={writeDisabled}
                                    >
                                        {t('common.actions.delete', 'Delete')}
                                    </Button>
                                </div>
                            </li>
                        ))}
                    </ul>
                )}
            </section>

            {/* Routes */}
            <section className="cf-workers__section">
                <h3 className="cf-workers__heading">{t('app.workersPanel.routes', 'Routes (')}{routes.length})</h3>

                {routes.length === 0 ? (
                    <p className="cf-workers__hint">
                        {t('app.workersPanel.noRoutesYetAddARoute', 'No routes yet. Add a route pattern when deploying to send traffic to a worker.')}
                    </p>
                ) : (
                    <ul className="cf-workers__list">
                        {routes.map((route) => (
                            <li className="cf-workers__item" key={route.id}>
                                <div className="cf-workers__name">
                                    <code>{route.pattern}</code>
                                    <span className="cf-workers__meta">&rarr; {route.script}</span>
                                </div>

                                <div className="cf-workers__item-actions">
                                    <Button
                                        variant="destructive"
                                        size="sm"
                                        onClick={() => handleDeleteRoute(route)}
                                        disabled={writeDisabled}
                                    >
                                        {t('common.actions.remove', 'Remove')}
                                    </Button>
                                </div>
                            </li>
                        ))}
                    </ul>
                )}
            </section>
        </div>
    );
}
