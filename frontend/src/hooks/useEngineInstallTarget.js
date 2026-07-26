import { useEffect, useState } from 'react';
import api from '../services/api';
import { engineInitialDatabase, engineInstanceKey } from '../components/databases/engineHelpers';

// Did this deployment job install a database engine, and if so where does the
// Database Explorer keep it?
//
// Installing an engine is an ordinary template install — same pipeline, same
// job, same console — so the job itself carries no "this was a database" flag
// and shouldn't. The answer comes from the engine listing instead: an installed
// engine is an Application, so matching on `app_id` is enough, and nothing here
// knows the name of a single engine.
//
// Fail soft in every direction: a job of another kind, a backend without the
// engines endpoint, or an app that simply isn't an engine all return null, and
// the caller just doesn't offer the extra way back.
export default function useEngineInstallTarget(job) {
    const [target, setTarget] = useState(null);

    const status = job?.status;
    const kind = job?.kind;
    const appId = job?.app_id ?? null;

    useEffect(() => {
        if (status !== 'succeeded' || kind !== 'template_install' || appId == null) {
            setTarget(null);
            return undefined;
        }
        let cancelled = false;
        // Identity and install variables only — no container probe needed to
        // answer "was this app an engine, and what did it seed?".
        api.getDatabaseEngines(false)
            .then((data) => {
                if (cancelled) return;
                const match = (data?.installed || []).find(
                    (entry) => engineInstanceKey(entry) === appId,
                );
                if (!match) return;
                setTarget({
                    appId,
                    name: match.name || match.template_name || 'the engine',
                    database: engineInitialDatabase(match),
                });
            })
            .catch(() => { /* no catalog, no affordance — the console still works */ });
        return () => { cancelled = true; };
    }, [status, kind, appId]);

    return target;
}
