const IDLE_STATE = Object.freeze({
    status: 'idle',
    data: undefined,
    error: null,
    updatedAt: 0,
    revision: 0,
    isFetching: false,
});

export const serializeQueryKey = (queryKey) => JSON.stringify(queryKey);

const keyStartsWith = (candidate, prefix) => (
    prefix.length <= candidate.length
    && prefix.every((part, index) => Object.is(part, candidate[index]))
);

const isAbortError = (error) => error?.name === 'AbortError';

/**
 * Small framework-neutral server-state cache.
 *
 * It deliberately owns only lifecycle concerns shared by every resource:
 * key isolation, in-flight deduplication, cancellation, freshness and
 * invalidation. Domain hooks still own response interpretation and live-event
 * semantics.
 */
export function createQueryClient() {
    const entries = new Map();

    const ensureEntry = (queryKey) => {
        const hash = serializeQueryKey(queryKey);
        let entry = entries.get(hash);
        if (!entry) {
            entry = {
                hash,
                queryKey: [...queryKey],
                state: IDLE_STATE,
                listeners: new Set(),
                controller: null,
                promise: null,
            };
            entries.set(hash, entry);
        }
        return entry;
    };

    const notify = (entry) => entry.listeners.forEach((listener) => listener());

    const updateState = (entry, patch) => {
        entry.state = { ...entry.state, ...patch };
        notify(entry);
    };

    const cancelEntry = (entry) => {
        entry.controller?.abort();
        entry.controller = null;
        entry.promise = null;
        if (entry.state.isFetching) updateState(entry, { isFetching: false });
    };

    const subscribe = (queryKey, listener) => {
        const entry = ensureEntry(queryKey);
        entry.listeners.add(listener);
        return () => {
            entry.listeners.delete(listener);
            if (entry.listeners.size === 0) cancelEntry(entry);
        };
    };

    const getSnapshot = (queryKey) => ensureEntry(queryKey).state;

    const fetchQuery = (queryKey, queryFn, { force = false, staleTime = 0 } = {}) => {
        const entry = ensureEntry(queryKey);
        if (entry.promise && !force) return entry.promise;

        const isFresh = entry.state.status === 'success'
            && Date.now() - entry.state.updatedAt < staleTime;
        if (isFresh && !force) return Promise.resolve(entry.state.data);
        if (force) cancelEntry(entry);

        const controller = new AbortController();
        entry.controller = controller;
        updateState(entry, {
            status: entry.state.data === undefined ? 'loading' : entry.state.status,
            error: null,
            isFetching: true,
        });

        const promise = Promise.resolve().then(() => queryFn({
            signal: controller.signal,
            queryKey: entry.queryKey,
        }));
        entry.promise = promise;

        return promise.then((data) => {
            if (entry.controller !== controller || controller.signal.aborted) return data;
            entry.controller = null;
            entry.promise = null;
            updateState(entry, {
                status: 'success',
                data,
                error: null,
                updatedAt: Date.now(),
                isFetching: false,
            });
            return data;
        }).catch((error) => {
            if (entry.controller !== controller || controller.signal.aborted || isAbortError(error)) {
                return undefined;
            }
            entry.controller = null;
            entry.promise = null;
            updateState(entry, {
                status: 'error',
                error,
                isFetching: false,
            });
            throw error;
        });
    };

    const invalidateQueries = (queryKeyPrefix = []) => {
        entries.forEach((entry) => {
            if (!keyStartsWith(entry.queryKey, queryKeyPrefix)) return;
            updateState(entry, {
                updatedAt: 0,
                revision: entry.state.revision + 1,
            });
        });
    };

    const cancelQueries = (queryKeyPrefix = []) => {
        entries.forEach((entry) => {
            if (keyStartsWith(entry.queryKey, queryKeyPrefix)) cancelEntry(entry);
        });
    };

    const clear = () => {
        entries.forEach(cancelEntry);
        entries.clear();
    };

    return {
        subscribe,
        getSnapshot,
        fetchQuery,
        invalidateQueries,
        cancelQueries,
        clear,
    };
}

export const queryClient = createQueryClient();
