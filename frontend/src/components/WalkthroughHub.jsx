import {
    ArrowRight,
    BookOpenCheck,
    Boxes,
    Check,
    ChevronLeft,
    Circle,
    Clock3,
    ListChecks,
    RotateCcw,
    ShieldCheck,
    X,
} from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { useWalkthroughs } from '../contexts/walkthroughContextValue';
import { getWalkthroughProgress } from '../services/walkthroughState';
import Pill from './ds/Pill';
import IconButton from './IconButton';


const ICONS = { service: Boxes, security: ShieldCheck };

function WalkthroughCard({ walkthrough, state, onStart, t }) {
    const Icon = ICONS[walkthrough.icon] || BookOpenCheck;
    const progress = getWalkthroughProgress(state, walkthrough);
    const status = progress.entry?.status;
    const completed = status === 'completed';
    const active = status === 'active';

    return (
        <article className={`walkthrough-card walkthrough-card--${walkthrough.tone}`}>
            <div className="walkthrough-card__icon"><Icon size={18} /></div>
            <div className="walkthrough-card__body">
                <div className="walkthrough-card__meta">
                    <span><Clock3 size={12} /> {walkthrough.duration}</span>
                    {completed && <Pill kind="green">{t('app.walkthroughs.completed', 'Completed')}</Pill>}
                    {active && <Pill kind="cyan">{progress.count}/{progress.total}</Pill>}
                </div>
                <h3>{walkthrough.title}</h3>
                <p>{walkthrough.description}</p>
                <Button
                    type="button"
                    variant={active ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => onStart(walkthrough.id)}
                >
                    {completed ? <RotateCcw size={14} /> : <ArrowRight size={14} />}
                    {completed
                        ? t('app.walkthroughs.runAgain', 'Run again')
                        : active
                            ? t('app.walkthroughs.resume', 'Resume')
                            : t('app.walkthroughs.start', 'Start walkthrough')}
                </Button>
            </div>
        </article>
    );
}

function ActiveWalkthrough({ walkthrough, progress, currentStep, onBrowse, t }) {
    const {
        checkCurrent,
        dismiss,
        goToCurrent,
    } = useWalkthroughs();
    const Icon = ICONS[walkthrough.icon] || BookOpenCheck;
    const [checking, setChecking] = useState(false);

    const performAction = async () => {
        if (!currentStep?.check) {
            goToCurrent();
            return;
        }
        setChecking(true);
        try { await checkCurrent(); } finally { setChecking(false); }
    };

    return (
        <>
            <header className="walkthrough-hub__active-head">
                <Button type="button" variant="ghost" size="sm" onClick={onBrowse}>
                    <ChevronLeft size={14} /> {t('app.walkthroughs.allGuides', 'All guides')}
                </Button>
                <div className={`walkthrough-hub__active-icon is-${walkthrough.tone}`}><Icon size={19} /></div>
                <span className="walkthrough-hub__eyebrow">
                    {t('app.walkthroughs.guidedOutcome', 'Guided outcome')}
                </span>
                <h2>{walkthrough.title}</h2>
                <div className="walkthrough-hub__progress-copy">
                    <span>{t('app.walkthroughs.stepCount', 'Step {{current}} of {{total}}', {
                        current: Math.min(progress.count + 1, progress.total),
                        total: progress.total,
                    })}</span>
                    <strong>{progress.percent}%</strong>
                </div>
                <progress max="100" value={progress.percent} aria-label={t('app.walkthroughs.progress', 'Walkthrough progress')} />
            </header>

            <ol className="walkthrough-hub__steps">
                {walkthrough.steps.map((step, index) => {
                    const done = progress.completed.includes(step.id);
                    const current = currentStep?.id === step.id;
                    return (
                        <li
                            key={step.id}
                            className={`${done ? 'is-done' : ''}${current ? ' is-current' : ''}`}
                            aria-current={current ? 'step' : undefined}
                        >
                            <span className="walkthrough-hub__step-marker">
                                {done ? <Check size={13} /> : current ? <Circle size={11} /> : index + 1}
                            </span>
                            <div>
                                <strong>{step.title}</strong>
                                {(current || done) && <p>{step.description}</p>}
                            </div>
                        </li>
                    );
                })}
            </ol>

            {currentStep && (
                <div className="walkthrough-hub__next">
                    <span>{t('app.walkthroughs.now', 'Now')}</span>
                    <strong>{currentStep.title}</strong>
                    <p>{currentStep.description}</p>
                    <Button type="button" onClick={performAction} disabled={checking}>
                        {checking
                            ? t('app.walkthroughs.checking', 'Checking…')
                            : currentStep.action}
                        {!checking && <ArrowRight size={15} />}
                    </Button>
                </div>
            )}

            <footer className="walkthrough-hub__footer">
                <span>{t('app.walkthroughs.progressSaved', 'Progress is saved to your account.')}</span>
                <Button type="button" variant="ghost" size="sm" onClick={() => dismiss(walkthrough.id)}>
                    {t('app.walkthroughs.stop', 'Stop walkthrough')}
                </Button>
            </footer>
        </>
    );
}

export default function WalkthroughHub({ hideLauncher = false, statusbarMode = false }) {
    const { t } = useTranslation();
    const {
        state,
        open,
        setOpen,
        walkthroughs,
        activeWalkthrough,
        activeProgress,
        currentStep,
        start,
    } = useWalkthroughs();
    const [browse, setBrowse] = useState(false);

    const showActive = activeWalkthrough && !browse;
    const completedCount = walkthroughs.filter(
        (walkthrough) => state.progress?.[walkthrough.id]?.status === 'completed',
    ).length;

    const launch = () => {
        setBrowse(!activeWalkthrough);
        setOpen(!open);
    };

    const selectWalkthrough = (id) => {
        start(id);
        setBrowse(false);
    };

    return (
        <div className={`walkthrough-shell${statusbarMode ? ' walkthrough-shell--statusbar' : ''}${open ? ' is-open' : ''}`}>
            {!hideLauncher && <Button
                type="button"
                className="walkthrough-shell__launcher"
                variant="outline"
                onClick={launch}
                aria-expanded={open}
                aria-controls="walkthrough-hub"
            >
                <BookOpenCheck size={16} />
                <span>{activeWalkthrough
                    ? t('app.walkthroughs.activeGuide', 'Guide · {{count}}/{{total}}', {
                        count: activeProgress.count,
                        total: activeProgress.total,
                    })
                    : t('app.walkthroughs.guides', 'Guides')}</span>
            </Button>}

            {open && (
                <aside id="walkthrough-hub" className="walkthrough-hub" aria-label={t('app.walkthroughs.guides', 'Guides')}>
                    <div className="walkthrough-hub__topline">
                        <span><ListChecks size={14} /> {t('app.walkthroughs.operatorGuides', 'Operator guides')}</span>
                        <IconButton
                            icon={<X size={15} />}
                            label={t('common.actions.close', 'Close')}
                            onClick={() => setOpen(false)}
                        />
                    </div>

                    {showActive ? (
                        <ActiveWalkthrough
                            walkthrough={activeWalkthrough}
                            progress={activeProgress}
                            currentStep={currentStep}
                            onBrowse={() => setBrowse(true)}
                            t={t}
                        />
                    ) : (
                        <div className="walkthrough-hub__library">
                            <header>
                                <span className="walkthrough-hub__eyebrow">
                                    {t('app.walkthroughs.learnByDoing', 'Learn by doing')}
                                </span>
                                <h2>{t('app.walkthroughs.makeTheNextMove', 'Make the next move')}</h2>
                                <p>{t(
                                    'app.walkthroughs.libraryDescription',
                                    'Walkthroughs guide the controls. Recipes automate the server work underneath.',
                                )}</p>
                                <span className="walkthrough-hub__library-count">
                                    {t('app.walkthroughs.completedCount', '{{count}} of {{total}} completed', {
                                        count: completedCount,
                                        total: walkthroughs.length,
                                    })}
                                </span>
                            </header>
                            <div className="walkthrough-hub__cards">
                                {walkthroughs.map((walkthrough) => (
                                    <WalkthroughCard
                                        key={walkthrough.id}
                                        walkthrough={walkthrough}
                                        state={state}
                                        onStart={selectWalkthrough}
                                        t={t}
                                    />
                                ))}
                            </div>
                        </div>
                    )}
                </aside>
            )}
        </div>
    );
}
