import { useCallback } from 'react';

import api from '../services/api';
import useRunStream from './useRunStream';

/**
 * Deployment compatibility adapter for the generalized run stream.
 * Deploy Console still receives its richer job snapshot and public `job`
 * result shape while transport, reconnect catch-up, and de-duplication use the
 * shared run envelope.
 */
export default function useDeployJobStream(jobId, options = {}) {
    const {
        pollInterval = 2000,
        enabled = true,
        includePlan = false,
    } = options;

    const loadRun = useCallback(async ({ includeLogs }) => {
        const response = await api.getDeploymentJob(jobId, includeLogs, includePlan && includeLogs);
        return response?.job || null;
    }, [jobId, includePlan]);

    const stream = useRunStream('deploy', jobId, {
        pollInterval,
        enabled,
        loadRun,
    });

    return {
        ...stream,
        job: stream.run,
    };
}
