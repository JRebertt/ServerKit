import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDown } from 'lucide-react';

// How many slices the severity map is divided into. Enough to resolve a single
// error in a long log without rendering a node per line.
const MAP_BUCKETS = 150;

// Worst-wins ranking: a slice holding one error among 200 info lines must show
// as an error, because finding that error is the entire point of the map.
const SEVERITY_RANK = { error: 4, warn: 3, warning: 3, info: 2, debug: 1 };

// Below this a scrollbar is already enough to see everything.
const MAP_MIN_LINES = 40;

// Monospace console surface. Auto-scrolls while "follow" is on; disengages when
// the user scrolls up and re-engages via a "Jump to live" chip. Lines carry a
// data-step attribute so the step rail can scroll a step into view.
//
// Alongside the log runs a severity map — the coloured strip that makes a
// failure findable in a few thousand lines: each slice is painted by the worst
// level it contains, the current viewport is outlined on it, and clicking or
// dragging jumps straight there.
export default function LogPane({ lines, wrap, timestamps, follow, onFollowChange, scrollToStep }) {
    const paneRef = useRef(null);
    const endRef = useRef(null);
    const [showJump, setShowJump] = useState(false);
    const [view, setView] = useState({ top: 0, height: 100 });

    const buckets = useMemo(() => {
        const out = new Array(MAP_BUCKETS).fill(null);
        if (!lines.length) return out;
        lines.forEach((ln, i) => {
            const slot = Math.min(MAP_BUCKETS - 1, Math.floor((i / lines.length) * MAP_BUCKETS));
            const level = ln.level || 'info';
            if (out[slot] == null
                || (SEVERITY_RANK[level] || 0) > (SEVERITY_RANK[out[slot]] || 0)) {
                out[slot] = level;
            }
        });
        return out;
    }, [lines]);

    const showMap = lines.length >= MAP_MIN_LINES;

    // Follow: keep pinned to the bottom as new lines arrive.
    useEffect(() => {
        if (follow && paneRef.current) {
            paneRef.current.scrollTop = paneRef.current.scrollHeight;
            setShowJump(false);
        }
    }, [lines, follow]);

    // Scroll a given step's first line into view when the rail is clicked.
    useEffect(() => {
        if (scrollToStep == null || !paneRef.current) return;
        const el = paneRef.current.querySelector(`[data-step="${scrollToStep}"]`);
        if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }, [scrollToStep]);

    const onScroll = () => {
        const pane = paneRef.current;
        if (!pane) return;
        const atBottom = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 40;
        if (!atBottom && follow) onFollowChange(false);
        setShowJump(!atBottom);
        const { scrollTop, scrollHeight, clientHeight } = pane;
        setView({
            top: scrollHeight ? (scrollTop / scrollHeight) * 100 : 0,
            // A floor, so the marker stays grabbable on a very long log.
            height: scrollHeight ? Math.max(3, (clientHeight / scrollHeight) * 100) : 100,
        });
    };

    // Keep the viewport marker honest as lines stream in and the log grows.
    useEffect(() => {
        const pane = paneRef.current;
        if (!pane || !pane.scrollHeight) return;
        setView({
            top: (pane.scrollTop / pane.scrollHeight) * 100,
            height: Math.max(3, (pane.clientHeight / pane.scrollHeight) * 100),
        });
    }, [lines]);

    // Click or drag anywhere on the map to go there.
    const mapScrub = useCallback((clientY, element) => {
        const pane = paneRef.current;
        if (!pane) return;
        const rect = element.getBoundingClientRect();
        const ratio = Math.min(1, Math.max(0, (clientY - rect.top) / rect.height));
        pane.scrollTop = ratio * pane.scrollHeight - pane.clientHeight / 2;
        onFollowChange(false);
    }, [onFollowChange]);

    const onMapDown = (event) => {
        const element = event.currentTarget;
        mapScrub(event.clientY, element);
        const move = (moveEvent) => mapScrub(moveEvent.clientY, element);
        const up = () => {
            window.removeEventListener('mousemove', move);
            window.removeEventListener('mouseup', up);
        };
        window.addEventListener('mousemove', move);
        window.addEventListener('mouseup', up);
    };

    const jumpToLive = () => {
        onFollowChange(true);
        if (paneRef.current) paneRef.current.scrollTop = paneRef.current.scrollHeight;
        setShowJump(false);
    };

    let lastStep = null;

    return (
        <div className={`deploy-console__logwrap${showMap ? ' deploy-console__logwrap--mapped' : ''}`}>
            <div
                ref={paneRef}
                className={`deploy-console__log ${wrap ? 'deploy-console__log--wrap' : ''}`}
                onScroll={onScroll}
                role="log"
                aria-live="polite"
            >
                {lines.length === 0 ? (
                    <div className="deploy-console__log-empty">Waiting for output…</div>
                ) : (
                    lines.map((ln, i) => {
                        const isNewStep = ln.step_index != null && ln.step_index !== lastStep;
                        if (ln.step_index != null) lastStep = ln.step_index;
                        const ts = timestamps && ln.ts
                            ? new Date(ln.ts).toLocaleTimeString()
                            : (timestamps && ln.created_at ? new Date(ln.created_at).toLocaleTimeString() : '');
                        return (
                            <div
                                key={ln.id ?? `i${i}`}
                                className={`deploy-console__line deploy-console__line--${ln.level || 'info'}`}
                                data-step={isNewStep ? ln.step_index : undefined}
                            >
                                {timestamps && <span className="deploy-console__line-ts">{ts}</span>}
                                <span className="deploy-console__line-msg">{ln.message}</span>
                            </div>
                        );
                    })
                )}
                <div ref={endRef} />
            </div>
            {showMap && (
                <div
                    className="deploy-console__map"
                    onMouseDown={onMapDown}
                    title="Log severity — click or drag to jump"
                >
                    {buckets.map((level, i) => (
                        <i
                            key={i}
                            aria-hidden="true"
                            className={`deploy-console__map-tick${level ? ` deploy-console__map-tick--${level}` : ''}`}
                        />
                    ))}
                    <div
                        className="deploy-console__map-view"
                        style={{ top: `${view.top}%`, height: `${view.height}%` }}
                    />
                </div>
            )}
            {showJump && (
                <button type="button" className="deploy-console__jump" onClick={jumpToLive}>
                    <ArrowDown size={14} /> Jump to live
                </button>
            )}
        </div>
    );
}
