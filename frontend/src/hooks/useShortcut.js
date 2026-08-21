import { useContext, useEffect, useRef } from 'react';

import ShortcutContext from '../contexts/shortcutContext';

export function useShortcut({ handler, ...command }) {
    const context = useContext(ShortcutContext);
    const handlerRef = useRef(handler);
    handlerRef.current = handler;
    const signature = JSON.stringify(command);

    useEffect(() => {
        if (!context) throw new Error('useShortcut must be used within ShortcutProvider');
        return context.register({
            ...command,
            handler: (event) => handlerRef.current(event),
        });
    // The serialized command is the registration contract; handlers stay fresh via ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [context?.register, signature]);
}

export function useShortcutCommands() {
    return useContext(ShortcutContext)?.commands || [];
}
