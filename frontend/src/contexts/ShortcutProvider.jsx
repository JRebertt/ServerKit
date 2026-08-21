import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { createShortcutRegistry } from '../services/shortcutRegistry';
import ShortcutContext from './shortcutContext';

export default function ShortcutProvider({ children }) {
    const registryRef = useRef(null);
    if (!registryRef.current) registryRef.current = createShortcutRegistry();
    const [revision, setRevision] = useState(0);

    useEffect(() => {
        const onKeyDown = (event) => registryRef.current.handle(event);
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, []);

    const register = useCallback((command) => {
        const unregister = registryRef.current.register(command);
        setRevision((current) => current + 1);
        return () => {
            unregister();
            setRevision((current) => current + 1);
        };
    }, []);
    const value = useMemo(() => ({
        register,
        commands: registryRef.current.list(),
    // Revision publishes registry changes to future shortcut-sheet consumers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }), [register, revision]);

    return <ShortcutContext.Provider value={value}>{children}</ShortcutContext.Provider>;
}
