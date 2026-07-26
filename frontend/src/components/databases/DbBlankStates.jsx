import { Link } from 'react-router-dom';
import {
    Loader2, Plus, Terminal, Table2, Activity, RefreshCw, ShieldAlert, Layers,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import EngineGlyph from './EngineGlyph';
import { engineLocation, engineMeta, engineTreeStatus, engineUnit, singular } from './engineHelpers';

// The three states the workspace can be in when there is nothing to show yet.
// Each one names what is happening and offers the single next step, rather than
// leaving an empty pane and a shrug.

// An engine template whose deploy is still running.
export function EngineInstallingPanel({ instance, onRefresh }) {
    const failed = engineTreeStatus(instance) === 'failed';
    const meta = engineMeta(instance);

    return (
        <div className="dbx-blank">
            <div className={`dbx-blank__icon${failed ? ' is-failed' : ''}`}>
                <EngineGlyph entry={instance} size={24} />
                {!failed && <Loader2 size={52} className="dbx-blank__spin dbx-spin" aria-hidden="true" />}
            </div>

            {failed ? (
                <>
                    <h2 className="dbx-blank__title">
                        <ShieldAlert size={17} aria-hidden="true" /> {instance.name} failed to install
                    </h2>
                    <p className="dbx-blank__body">
                        {instance.error_message
                            || 'The deploy did not finish. The install log has the reason.'}
                    </p>
                </>
            ) : (
                <>
                    <h2 className="dbx-blank__title">Installing {instance.name}</h2>
                    <p className="dbx-blank__body">
                        Pulling the image, provisioning the volume and waiting for the first health
                        check{meta.family ? ` on this ${meta.family.toLowerCase()} engine` : ''}.
                        This usually takes about a minute.
                    </p>
                </>
            )}

            <div className="dbx-blank__actions">
                {instance.deploy_job_id && (
                    <Button asChild size="sm">
                        <Link to={`/deployments/${instance.deploy_job_id}`}>
                            <Terminal size={14} aria-hidden="true" /> View install log
                        </Link>
                    </Button>
                )}
                <Button asChild size="sm" variant="outline">
                    <Link to="/deployments"><Activity size={14} aria-hidden="true" /> Deploy activity</Link>
                </Button>
                {onRefresh && (
                    <Button type="button" size="sm" variant="outline" onClick={onRefresh}>
                        <RefreshCw size={14} aria-hidden="true" /> Check again
                    </Button>
                )}
            </div>

            {instance.initial_database && (
                <p className="dbx-blank__note">
                    <Plus size={12} aria-hidden="true" />
                    {instance.initial_database} will be created once the engine reports healthy
                </p>
            )}
        </div>
    );
}

// An engine that is up but has nothing in it yet — either a host engine
// (MySQL / PostgreSQL) with no databases, or a freshly installed one.
export function EngineReadyPanel({ instance, label, onNewDatabase, onOpenConsole }) {
    const meta = engineMeta(instance);
    const address = engineLocation(instance);
    const unitOne = singular(engineUnit(instance));

    return (
        <div className="dbx-blank">
            <div className="dbx-blank__icon">
                <EngineGlyph entry={instance} size={24} />
            </div>
            <h2 className="dbx-blank__title">{label || instance?.name} is ready</h2>
            <p className="dbx-blank__body">
                {address ? <>Listening on <code>{address}</code>. </> : null}
                {onNewDatabase ? (
                    'Create a database to start writing to it.'
                ) : (
                    <>
                        Create a {unitOne} from {meta.client ? <code>{meta.client}</code> : 'its client'}
                        {' '}— ServerKit lists it here as soon as it exists.
                    </>
                )}
            </p>
            <div className="dbx-blank__actions">
                {onNewDatabase && (
                    <Button type="button" size="sm" onClick={onNewDatabase}>
                        <Plus size={14} aria-hidden="true" /> New database
                    </Button>
                )}
                {onOpenConsole && (
                    <Button type="button" size="sm" variant="outline" onClick={onOpenConsole}>
                        <Terminal size={14} aria-hidden="true" /> Open SQL console
                    </Button>
                )}
                {instance?.app_id != null && (
                    <Button asChild size="sm" variant="outline">
                        <Link to={`/services/${instance.app_id}`}>
                            <Layers size={14} aria-hidden="true" /> Manage service
                        </Link>
                    </Button>
                )}
            </div>
            {meta.protocol === 'none' && (
                <p className="dbx-blank__note">
                    This engine has no browsable protocol — ServerKit runs it, but table browsing
                    comes from its own client.
                </p>
            )}
        </div>
    );
}

// A database that exists but holds no tables/collections yet. The table builder
// and dump import are deliberately out of scope for this round, so the honest
// next step is the console.
export function DatabaseEmptyPanel({ node, unit = 'tables', onOpenConsole }) {
    const unitOne = singular(unit);
    return (
        <div className="dbx-blank">
            <div className="dbx-blank__icon">
                <Table2 size={24} aria-hidden="true" />
            </div>
            <h2 className="dbx-blank__title">No {unit} in {node?.label}</h2>
            <p className="dbx-blank__body">
                The database is connected and empty. Create your first {unitOne} from the console.
            </p>
            <div className="dbx-blank__actions">
                {onOpenConsole && (
                    <Button type="button" size="sm" onClick={onOpenConsole}>
                        <Terminal size={14} aria-hidden="true" /> Open SQL console
                    </Button>
                )}
            </div>
        </div>
    );
}
