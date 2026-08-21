import { Check, Loader2, X, Circle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

// Per-step duration formatter (seconds -> "3s" / "1m 4s").
const fmtSeconds = (s) => {
    if (s == null) return '';
    if (s < 60) return `${s < 10 ? s.toFixed(1) : Math.round(s)}s`;
    const m = Math.floor(s / 60);
    return `${m}m ${Math.round(s % 60)}s`;
};

const STATE_ICON = {
    done: Check,
    running: Loader2,
    failed: X,
    pending: Circle,
};

// The job plan as a horizontal strip above the log: one segment per step, each
// carrying a bar sized to that step's share of total runtime, so where the time
// actually went is readable at a glance. Replaced the left-hand vertical rail,
// which cost the log pane ~250px of width for a list that never needed it.
// Clicking a segment scrolls the log pane to that step's first line.
export default function PipelineStrip({ steps, selected, onStepClick }) {
    const { t } = useTranslation();
    if (!steps || steps.length === 0) return null;

    const total = steps.reduce((sum, s) => sum + (s.seconds || 0), 0) || 1;

    return (
        <div className="deploy-console__pipeline" role="list" aria-label={t('app.pipelineStrip.deploymentSteps', 'Deployment steps')}>
            {steps.map((step) => {
                const Icon = STATE_ICON[step.state] || Circle;
                const pct = Math.round(((step.seconds || 0) / total) * 100);
                return (
                    <button
                        type="button"
                        role="listitem"
                        key={step.index}
                        className={[
                            'deploy-console__seg',
                            `deploy-console__seg--${step.state}`,
                            selected === step.index ? 'is-selected' : '',
                        ].filter(Boolean).join(' ')}
                        onClick={() => onStepClick?.(step.index)}
                        title={step.name}
                    >
                        <span className="deploy-console__seg-head">
                            <Icon
                                size={13}
                                className={step.state === 'running' ? 'deploy-console__spin' : ''}
                            />
                            <span className="deploy-console__seg-name">{step.name}</span>
                        </span>
                        <span className="deploy-console__seg-bar">
                            {/* A finished step always shows a sliver even at 0% of
                                total, so a fast step never reads as "did not run". */}
                            <i style={{ width: `${step.seconds ? Math.max(pct, 3) : 0}%` }} />
                        </span>
                        <span className="deploy-console__seg-dur">
                            {step.state === 'running'
                                ? 'running…'
                                : fmtSeconds(step.seconds) || (step.state === 'pending' ? 'pending' : '—')}
                        </span>
                    </button>
                );
            })}
        </div>
    );
}
