import { ArrowDown, ArrowUp, Copy, Download, Maximize2, Minimize2, Search } from 'lucide-react';

const LEVELS = ['all', 'info', 'warn', 'error', 'debug'];

// Log toolbar: follow / wrap / timestamps toggles, error and warning counts that
// double as filters, a level filter, a client-side search box, match
// navigation, plus copy-all and download-.txt actions.
export default function ConsoleToolbar({
    follow, onToggleFollow,
    wrap, onToggleWrap,
    timestamps, onToggleTimestamps,
    level, onLevelChange,
    search, onSearchChange,
    onCopy, onDownload,
    errorCount = 0, warnCount = 0,
    navCount = 0, navPos = 0, navLabel = '', onNavPrev, onNavNext,
    focused = false, onToggleFocus,
}) {
    // Clicking a count filters to it, and clicking again clears — the count is
    // worth seeing on its own, so it earns the space either way.
    const toggleLevel = (target) => onLevelChange(level === target ? 'all' : target);

    return (
        <div className="deploy-console__toolbar">
            <div className="deploy-console__toolbar-group">
                <button
                    type="button"
                    className={`deploy-console__toggle ${follow ? 'is-active' : ''}`}
                    onClick={onToggleFollow}
                    aria-pressed={follow}
                >
                    Follow
                </button>
                <button
                    type="button"
                    className={`deploy-console__toggle ${wrap ? 'is-active' : ''}`}
                    onClick={onToggleWrap}
                    aria-pressed={wrap}
                >
                    Wrap
                </button>
                <button
                    type="button"
                    className={`deploy-console__toggle ${timestamps ? 'is-active' : ''}`}
                    onClick={onToggleTimestamps}
                    aria-pressed={timestamps}
                >
                    Timestamps
                </button>
                <label className="deploy-console__level">
                    <span className="sr-only">Log level</span>
                    <select value={level} onChange={(e) => onLevelChange(e.target.value)}>
                        {LEVELS.map((l) => (
                            <option key={l} value={l}>{l === 'all' ? 'All levels' : l}</option>
                        ))}
                    </select>
                </label>
                {errorCount > 0 && (
                    <button
                        type="button"
                        className={`deploy-console__chip deploy-console__chip--error ${level === 'error' ? 'is-active' : ''}`}
                        onClick={() => toggleLevel('error')}
                        aria-pressed={level === 'error'}
                    >
                        {errorCount} error{errorCount === 1 ? '' : 's'}
                    </button>
                )}
                {warnCount > 0 && (
                    <button
                        type="button"
                        className={`deploy-console__chip deploy-console__chip--warn ${level === 'warn' ? 'is-active' : ''}`}
                        onClick={() => toggleLevel('warn')}
                        aria-pressed={level === 'warn'}
                    >
                        {warnCount} warning{warnCount === 1 ? '' : 's'}
                    </button>
                )}
            </div>

            <div className="deploy-console__toolbar-group">
                <div className="deploy-console__search">
                    <Search size={14} />
                    <input
                        type="text"
                        placeholder="Search logs…"
                        value={search}
                        onChange={(e) => onSearchChange(e.target.value)}
                    />
                </div>
                {/* With no search term these step through the errors, which is
                    what someone opening a failed deploy is looking for. */}
                <div className="deploy-console__nav">
                    <span className="deploy-console__nav-count">
                        {navCount ? `${Math.min(navPos + 1, navCount)}/${navCount}` : ''} {navLabel}
                    </span>
                    <button
                        type="button"
                        className="deploy-console__toggle"
                        onClick={onNavPrev}
                        disabled={!navCount}
                        title={`Previous ${navLabel || 'match'}`}
                    >
                        <ArrowUp size={14} />
                    </button>
                    <button
                        type="button"
                        className="deploy-console__toggle"
                        onClick={onNavNext}
                        disabled={!navCount}
                        title={`Next ${navLabel || 'match'}`}
                    >
                        <ArrowDown size={14} />
                    </button>
                </div>
                <button type="button" className="deploy-console__toggle" onClick={onCopy} title="Copy all logs">
                    <Copy size={14} /> Copy
                </button>
                <button type="button" className="deploy-console__toggle" onClick={onDownload} title="Download logs as .txt">
                    <Download size={14} /> Download
                </button>
                <button
                    type="button"
                    className={`deploy-console__toggle ${focused ? 'is-active' : ''}`}
                    onClick={onToggleFocus}
                    aria-pressed={focused}
                    title={focused ? 'Show the deployment details again' : 'Give the log the whole page'}
                >
                    {focused ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
                    {focused ? 'Exit' : 'Expand'}
                </button>
            </div>
        </div>
    );
}
