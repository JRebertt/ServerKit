import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { useWorkspace } from '../contexts/WorkspaceContext';
import { queryClient, serializeQueryKey } from '../services/queryClient';

const workspaceKey = (workspaceId, queryKey) => ['workspace', workspaceId, ...queryKey];

export function useServerQuery(queryKey, queryFn, options = {}) {
    const {
        enabled = true,
        staleTime = 0,
        onError,
    } = options;
    const { activeWorkspaceId } = useWorkspace();
    const localKeyHash = serializeQueryKey(queryKey);
    const scopedKey = useMemo(
        () => workspaceKey(activeWorkspaceId, queryKey),
        // queryKey is commonly declared inline; its serialized value is the
        // semantic dependency and avoids refetching on every render.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [activeWorkspaceId, localKeyHash],
    );
    const scopedKeyHash = serializeQueryKey(scopedKey);
    const queryFnRef = useRef(queryFn);
    const onErrorRef = useRef(onError);
    queryFnRef.current = queryFn;
    onErrorRef.current = onError;

    const subscribe = useCallback(
        (listener) => queryClient.subscribe(scopedKey, listener),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [scopedKeyHash],
    );
    const getSnapshot = useCallback(
        () => queryClient.getSnapshot(scopedKey),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [scopedKeyHash],
    );
    const state = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

    useEffect(() => {
        if (!enabled) return undefined;
        let active = true;
        queryClient.fetchQuery(
            scopedKey,
            (context) => queryFnRef.current(context),
            { staleTime },
        ).catch((error) => {
            if (active) onErrorRef.current?.(error);
        });
        return () => { active = false; };
    }, [enabled, scopedKeyHash, staleTime, state.revision, scopedKey]);

    const refetch = useCallback(
        () => queryClient.fetchQuery(
            scopedKey,
            (context) => queryFnRef.current(context),
            { force: true, staleTime },
        ),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [scopedKeyHash, staleTime],
    );

    return {
        ...state,
        isLoading: state.status === 'idle' || state.status === 'loading',
        isError: state.status === 'error',
        refetch,
    };
}

export function useServerMutation(mutationFn, options = {}) {
    const { invalidate = [], onSuccess, onError } = options;
    const { activeWorkspaceId } = useWorkspace();
    const mutationFnRef = useRef(mutationFn);
    const optionsRef = useRef({ invalidate, onSuccess, onError });
    mutationFnRef.current = mutationFn;
    optionsRef.current = { invalidate, onSuccess, onError };
    const [state, setState] = useState({ status: 'idle', data: undefined, error: null });

    const mutate = useCallback(async (variables) => {
        setState((previous) => ({ ...previous, status: 'loading', error: null }));
        try {
            const data = await mutationFnRef.current(variables);
            setState({ status: 'success', data, error: null });
            optionsRef.current.invalidate.forEach((prefix) => {
                queryClient.invalidateQueries(workspaceKey(activeWorkspaceId, prefix));
            });
            await optionsRef.current.onSuccess?.(data, variables);
            return data;
        } catch (error) {
            setState({ status: 'error', data: undefined, error });
            optionsRef.current.onError?.(error, variables);
            throw error;
        }
    }, [activeWorkspaceId]);

    const reset = useCallback(() => {
        setState({ status: 'idle', data: undefined, error: null });
    }, []);

    return {
        ...state,
        isPending: state.status === 'loading',
        mutate,
        reset,
    };
}
