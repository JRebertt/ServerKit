import { useEffect, useRef, useState, useCallback } from 'react';
import useFocusParam from './useFocusParam';
import { scrollBehavior } from '@/utils/reducedMotion';

/**
 * Settings deep-link focus (plan 41, Phase 2). A settings tab calls this hook
 * once and spreads `register(id)` onto each card it wants to be landable from
 * the command palette. When the tab is opened via `/settings/<tab>?focus=setting:<id>`
 * the matching card is scrolled into view and flashed with `is-setting-focused`
 * for ~2s, then the highlight clears.
 *
 * Rides the plan-33 `useFocusParam` rail with a new `setting` kind — the param
 * fires once and is cleared, so a refresh doesn't re-trigger it.
 *
 * Usage — pass the card's own class as the second arg so the flash class is
 * composed onto it (no extra wrapper element, no layout shift):
 *   const register = useSettingFocus();
 *   <div {...register('security-2fa', 'settings-card')}> … </div>
 *
 * @returns {(id: string, baseClassName?: string) => { ref: Function, className: string|undefined }}
 */
export default function useSettingFocus() {
    const [focusedId, setFocusedId] = useState(null);
    const refs = useRef(new Map());

    useFocusParam('setting', useCallback((id) => {
        setFocusedId(id);
    }, []));

    useEffect(() => {
        if (!focusedId) return undefined;
        let attempts = 0;
        let clearTimer;
        let retryTimer;

        // The target card may not be mounted yet (the tab is still loading its
        // data), so poll briefly for it before giving up.
        const tryScroll = () => {
            const el = refs.current.get(focusedId);
            if (el) {
                el.scrollIntoView({ behavior: scrollBehavior(), block: 'center' });
                clearTimer = setTimeout(() => setFocusedId(null), 2000);
                return;
            }
            if (attempts++ < 20) {
                retryTimer = setTimeout(tryScroll, 100);
            } else {
                setFocusedId(null);
            }
        };
        retryTimer = setTimeout(tryScroll, 50);

        return () => {
            clearTimeout(retryTimer);
            clearTimeout(clearTimer);
        };
    }, [focusedId]);

    return useCallback((id, baseClassName) => ({
        ref: (el) => {
            if (el) refs.current.set(id, el);
            else refs.current.delete(id);
        },
        className: [baseClassName, focusedId === id ? 'is-setting-focused' : null]
            .filter(Boolean)
            .join(' ') || undefined,
    }), [focusedId]);
}
