import { useState, useEffect, useCallback } from 'react';
import { GitBranch, Box, Clock, FileDiff } from 'lucide-react';
import api from '../../services/api';
import { Pill } from '@/components/ds';
import { Button } from '@/components/ui/button';
import ConfigDiffModal from './ConfigDiffModal';
import { useTranslation } from 'react-i18next';

// Vertical timeline of an app's config snapshots. Each node shows the image /
// build method, a "config changed" badge (derived from the per-snapshot
// summary), and the capture time. Clicking a node opens the config diff vs the
// previous snapshot. Snapshots never carry secret values (masked at capture).

function formatTime(iso) {
    if (!iso) return '';
    try {
        return new Date(iso).toLocaleString();
    } catch {
        return iso;
    }
}

// A snapshot's `summary` reads like "no config changes" when nothing changed,
// or e.g. "3 env vars changed; image updated" otherwise.
function snapshotChanged(summary) {
    if (!summary) return false;
    const s = summary.toLowerCase();
    return !(s === 'no config changes' || s === 'initial config snapshot');
}

const DeploymentTimeline = ({ appId }) => {
    const { t } = useTranslation();
    const [snapshots, setSnapshots] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [activeDiff, setActiveDiff] = useState(null); // { snapId }

    const loadSnapshots = useCallback(async () => {
        try {
            setLoading(true);
            const res = await api.getAppSnapshots(appId);
            setSnapshots(res.snapshots || []);
            setError(null);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [appId]);

    useEffect(() => {
        loadSnapshots();
    }, [loadSnapshots]);

    if (loading) {
        return <div className="deploy-timeline__loading">{t('app.deploymentTimeline.loadingDeploymentTimeline', 'Loading deployment timeline…')}</div>;
    }

    if (error) {
        return <div className="alert alert-danger">{error}</div>;
    }

    if (snapshots.length === 0) {
        return (
            <div className="deploy-timeline deploy-timeline--empty">
                <Clock size={20} />
                <p>{t('app.deploymentTimeline.noConfigCheckpointsYetOneIs', 'No config checkpoints yet. One is captured before each deployment.')}</p>
            </div>
        );
    }

    return (
        <div className="deploy-timeline">
            <ol className="deploy-timeline__list">
                {snapshots.map((snap, idx) => {
                    const cfg = snap.config || {};
                    const changed = snapshotChanged(snap.summary);
                    const isLatest = idx === 0;
                    return (
                        <li key={snap.id} className="deploy-timeline__item">
                            <span
                                className={
                                    'deploy-timeline__marker' +
                                    (isLatest ? ' deploy-timeline__marker--current' : '')
                                }
                                aria-hidden="true"
                            />
                            <div className="deploy-timeline__card">
                                <div className="deploy-timeline__row">
                                    <div className="deploy-timeline__meta">
                                        {isLatest && <Pill kind="green">{t('common.labels.current', 'Current')}</Pill>}
                                        {changed && (
                                            <Pill kind="amber" dot={false}>
                                                {t('app.deploymentTimeline.configChanged', 'Config changed')}
                                            </Pill>
                                        )}
                                        <span className="deploy-timeline__time">
                                            <Clock size={13} /> {formatTime(snap.created_at)}
                                        </span>
                                    </div>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => setActiveDiff({ snapId: snap.id })}
                                    >
                                        <FileDiff size={14} /> {t('app.deploymentTimeline.viewDiff', 'View diff')}
                                    </Button>
                                </div>

                                <div className="deploy-timeline__details">
                                    {cfg.image_tag && (
                                        <span className="deploy-timeline__chip">
                                            <Box size={13} /> {cfg.image_tag}
                                        </span>
                                    )}
                                    {cfg.build_method && (
                                        <span className="deploy-timeline__chip">
                                            <GitBranch size={13} /> {cfg.build_method}
                                        </span>
                                    )}
                                    {cfg.env_keys && (
                                        <span className="deploy-timeline__chip">
                                            {cfg.env_keys.length} {t('app.deploymentTimeline.envVar', 'env var')}
                                            {cfg.env_keys.length === 1 ? '' : 's'}
                                        </span>
                                    )}
                                </div>

                                {snap.summary && (
                                    <p className="deploy-timeline__summary">{snap.summary}</p>
                                )}
                            </div>
                        </li>
                    );
                })}
            </ol>

            {activeDiff && (
                <ConfigDiffModal
                    appId={appId}
                    snapId={activeDiff.snapId}
                    onClose={() => setActiveDiff(null)}
                    onRestored={() => {
                        setActiveDiff(null);
                        loadSnapshots();
                    }}
                />
            )}
        </div>
    );
};

export default DeploymentTimeline;
