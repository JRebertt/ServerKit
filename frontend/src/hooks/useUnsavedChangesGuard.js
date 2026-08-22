import { useCallback, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import { useConfirm } from './useConfirm';
import { internalNavigationTarget } from '../services/navigationGuard';

export function useUnsavedChangesGuard({
    isDirty,
    confirmOptions,
    onDiscard,
} = {}) {
    const navigate = useNavigate();
    const { confirm } = useConfirm();
    const optionsRef = useRef(confirmOptions);
    const discardRef = useRef(onDiscard);
    optionsRef.current = confirmOptions;
    discardRef.current = onDiscard;

    const requestLeave = useCallback(async () => {
        if (!isDirty) return true;
        const leave = await confirm({ variant: 'warning', ...optionsRef.current });
        if (leave) discardRef.current?.();
        return leave;
    }, [confirm, isDirty]);

    const guardedNavigate = useCallback(async (to, options) => {
        if (await requestLeave()) navigate(to, options);
    }, [navigate, requestLeave]);

    useEffect(() => {
        if (!isDirty) return undefined;
        const onBeforeUnload = (event) => {
            event.preventDefault();
            event.returnValue = '';
        };
        window.addEventListener('beforeunload', onBeforeUnload);
        return () => window.removeEventListener('beforeunload', onBeforeUnload);
    }, [isDirty]);

    useEffect(() => {
        if (!isDirty) return undefined;
        const onClick = async (event) => {
            const destination = internalNavigationTarget(event, window.location);
            if (!destination) return;

            event.preventDefault();
            if (await requestLeave()) navigate(destination);
        };
        document.addEventListener('click', onClick);
        return () => document.removeEventListener('click', onClick);
    }, [isDirty, navigate, requestLeave]);

    return { requestLeave, guardedNavigate };
}
