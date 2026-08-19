import { useEffect, useRef, useState } from 'react';
import Modal from './Modal';
import { Button } from '@/components/ui/button';
import socketService from '../services/socket';
import { rooms } from '@/constants/events';

// Subscribes to a remote agent's job:<id> stream channel and renders
// the live log output. Used by PackagesTab and ServicesTab for
// long-running install / upgrade / journal-follow operations.
//
// The agent emits {phase, lines[], message, percent, exit_code, error}
// events on the channel. The panel re-broadcasts those over Socket.IO
// as `server_stream` events into room `server_<serverId>_<channel>`.
// We join the room on mount, listen for matching server_stream events,
// and surface a "done" phase as success/error in the footer.
export default function JobProgressModal({
    open,
    serverId,
    channel,
    title = 'Working…',
    onClose,
    onComplete,
}) {
    const [lines, setLines] = useState([]);
    const [done, setDone] = useState(null); // null | { exitCode, error, extra }
    const logEndRef = useRef(null);

    useEffect(() => {
        if (!open || !channel || !serverId) return;
        const room = rooms.serverChannel(serverId, channel);
        const socket = socketService.socket;
        if (!socket) {
            // Connect lazily — happens once per panel session normally.
            socketService.connect();
        }

        const activeSocket = socketService.socket;
        if (!activeSocket) return;

        const onStream = (msg) => {
            if (msg?.channel !== channel) return;
            const ev = msg.data || {};
            if (Array.isArray(ev.lines) && ev.lines.length) {
                setLines((prev) => [...prev, ...ev.lines]);
            } else if (ev.message) {
                setLines((prev) => [...prev, ev.message]);
            }
            if (ev.phase === 'done') {
                const exitCode = typeof ev.exit_code === 'number' ? ev.exit_code : null;
                setDone({
                    exitCode,
                    error: ev.error || '',
                    extra: ev.extra || null,
                });
                if (onComplete) onComplete(ev);
            }
        };

        activeSocket.emit('join_room', { room });
        activeSocket.on('server_stream', onStream);

        return () => {
            activeSocket.emit('leave_room', { room });
            activeSocket.off('server_stream', onStream);
        };
    }, [open, channel, serverId, onComplete]);

    // Reset state on close so the next job starts fresh.
    useEffect(() => {
        if (!open) {
            setLines([]);
            setDone(null);
        }
    }, [open]);

    // Auto-scroll to the bottom as new lines arrive.
    useEffect(() => {
        logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [lines.length]);

    const success = done && done.exitCode === 0 && !done.error;
    const failure = done && !success;

    return (
        <Modal
            open={open}
            onClose={onClose}
            title={title}
            size="xl"
            footer={
                <div className="flex items-center gap-3 w-full">
                    <div className="flex-1">
                        {!done && <span className="text-muted-foreground text-sm">Streaming progress…</span>}
                        {success && <span className="text-success text-sm">Completed successfully</span>}
                        {failure && (
                            <span className="text-destructive text-sm">
                                Failed{done.exitCode !== null ? ` (exit ${done.exitCode})` : ''}
                                {done.error ? `: ${done.error}` : ''}
                            </span>
                        )}
                    </div>
                    <Button variant="outline" onClick={onClose} disabled={!done}>
                        {done ? 'Close' : 'Working…'}
                    </Button>
                </div>
            }
        >
            <div className="job-progress-modal">
                {lines.length === 0 && !done && (
                    <p className="text-muted-foreground text-sm">Waiting for the agent to begin…</p>
                )}
                {lines.length > 0 && (
                    <pre className="job-progress-modal__log">
                        {lines.join('\n')}
                        <div ref={logEndRef} />
                    </pre>
                )}
            </div>
        </Modal>
    );
}
