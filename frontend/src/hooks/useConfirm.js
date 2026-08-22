import { useState, useCallback } from 'react';
import { useConfirmContext } from '../contexts/ConfirmContext';

// Confirm-dialog hook.
//
// When a <ConfirmProvider> is in the tree (the dashboard), `confirm()` routes
// to the single app-level dialog and the legacy `confirmState`/`handleConfirm`/
// `handleCancel` become inert no-ops — so a page's own `<ConfirmDialog
// isOpen={confirmState.isOpen} />` simply stays closed (harmless) until it is
// removed. Outside a provider (e.g. pre-auth screens) it falls back to the
// original local-state behavior so nothing breaks.
const NOOP = () => {};

export function useConfirm() {
    const ctxConfirm = useConfirmContext();

    // Local fallback state (only used when there is no provider). Hooks run
    // unconditionally to satisfy the Rules of Hooks.
    const [confirmState, setConfirmState] = useState({
        isOpen: false,
        title: '',
        message: '',
        confirmTextKey: 'app.useConfirm.confirm', confirmText: 'Confirm',
        cancelTextKey: 'common.actions.cancel', cancelText: 'Cancel',
        variant: 'danger',
        resolve: null,
    });

    const localConfirm = useCallback(({
        title = 'Confirm Action',
        message = 'Are you sure you want to proceed?',
        confirmText = 'Confirm',
        cancelText = 'Cancel',
        variant = 'danger',
    } = {}) => {
        return new Promise((resolve) => {
            setConfirmState({
                isOpen: true,
                title,
                message,
                confirmText,
                cancelText,
                variant,
                resolve,
            });
        });
    }, []);

    const handleConfirm = useCallback(() => {
        setConfirmState((prev) => {
            prev.resolve?.(true);
            return { ...prev, isOpen: false };
        });
    }, []);

    const handleCancel = useCallback(() => {
        setConfirmState((prev) => {
            prev.resolve?.(false);
            return { ...prev, isOpen: false };
        });
    }, []);

    if (ctxConfirm) {
        return {
            confirm: ctxConfirm,
            confirmState: { isOpen: false },
            handleConfirm: NOOP,
            handleCancel: NOOP,
        };
    }

    return { confirm: localConfirm, confirmState, handleConfirm, handleCancel };
}

export default useConfirm;
