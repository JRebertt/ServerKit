// useServerStream — the ONE join/listen/cleanup dance for socket rooms
// (plan 77 E4). Components used to hand-roll connect + join_room + on(event)
// + off/leave in slightly different ways (some forgot to re-join after a
// reconnect, which silently kills the stream server-side). Both shapes live
// here:
//
//   useServerStream(room, event, handler, { enabled })   // effect-shaped
//   const stop = joinServerStream(room, event, handler); // imperative
//
// `handler` must be referentially stable across renders for the hook form
// (wrap it in useCallback) or the room will be left/re-joined every render.
import { useEffect } from 'react';

import socketService from '@/services/socket';

export function joinServerStream(room, event, handler) {
    if (!socketService.socket) socketService.connect();
    const sock = socketService.socket;
    if (!sock || !room) return () => {};

    const join = () => sock.emit('join_room', { room });
    join(); // socket.io buffers this until connected
    sock.on('connect', join); // rooms are lost server-side on reconnect
    sock.on(event, handler);

    return () => {
        sock.off(event, handler);
        sock.off('connect', join);
        if (sock.connected) sock.emit('leave_room', { room });
    };
}

export function useServerStream(room, event, handler, { enabled = true } = {}) {
    useEffect(() => {
        if (!enabled || !room) return undefined;
        return joinServerStream(room, event, handler);
    }, [room, event, handler, enabled]);
}
