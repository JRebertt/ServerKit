import { useState, useEffect, useRef, useMemo } from 'react';
import useTabParam from '../hooks/useTabParam';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import { useConfirm } from '../hooks/useConfirm';
import TargetPicker from '../components/TargetPicker';
import RemoteTerminal from '../components/RemoteTerminal';
import LogFileList from '../components/log-viewer/LogFileList';
import LogToolbar from '../components/log-viewer/LogToolbar';
import LogContent from '../components/log-viewer/LogContent';
import { formatBytes, logKindFromPath } from '../components/log-viewer/logHelpers';
import { formatBytes as formatMemory } from '@/utils/formatBytes';
import { Pill, Drawer } from '../components/ds';
import PageLayout from '../layouts/PageLayout';
import { Button } from '@/components/ui/button';
import {
    FileText, Clock, AlertCircle, Search, X, RefreshCw, AlertTriangle, Activity,
    Play, Square, RotateCw, Terminal as TerminalIcon, Server as ServerIcon,
    ScrollText, Cpu, Settings,
} from 'lucide-react';

// 'logs' stays first so the default landing keeps working on installs with no
// paired agents (the interactive shell needs a connected agent).
const VALID_TABS = ['logs', 'journal', 'processes', 'services', 'shell'];

// Section tabs rendered inline in the PageTopbar (Servers-style), routed via
// /terminal/<tab>. Log Files is the default landing (/terminal) — it needs no
// paired agent — so it's listed first, keeping the highlighted tab and the
// landing view in sync. The interactive Terminal sits next.
const TERMINAL_TABS = [
    { to: '/terminal', label: 'Log Files', end: true, icon: <FileText size={15} /> },
    { to: '/terminal/shell', label: 'Terminal', icon: <TerminalIcon size={15} /> },
    { to: '/terminal/journal', label: 'System Journal', icon: <ScrollText size={15} /> },
    { to: '/terminal/processes', label: 'Processes', icon: <Cpu size={15} /> },
    { to: '/terminal/services', label: 'Services', icon: <Settings size={15} /> },
];

const Terminal = () => {
    const [activeTab] = useTabParam('/terminal', VALID_TABS);

    return (
        // A full-bleed workspace, like the File Manager: the console panes fill
        // the content region edge-to-edge rather than floating as a rounded card
        // inside a padded well.
        <PageLayout
            fill
            className="terminal-page"
            contentClassName="tab-content"
            navLabel="Logs"
            tabs={TERMINAL_TABS}
        >
            {activeTab === 'shell' && <TerminalShellTab />}
            {activeTab === 'logs' && <LogFilesTab />}
            {activeTab === 'journal' && <JournalTab />}
            {activeTab === 'processes' && <ProcessesTab />}
            {activeTab === 'services' && <ServicesTab />}
        </PageLayout>
    );
};

// ─── Interactive shell tab (demo console: target rail + terminal pane) ───
// Sessions run over the ServerKit agent (terminal:create); the panel host has
// no PTY endpoint (§5 gap), so the rail lists paired agent servers only.
const TerminalShellTab = () => {
    const [servers, setServers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [selectedId, setSelectedId] = useState(null);

    useEffect(() => {
        (async () => {
            try {
                const list = await api.getAvailableServers();
                const eligible = Array.isArray(list)
                    ? list.filter(s => s.capabilities && s.capabilities.terminal)
                    : [];
                setServers(eligible);
                const firstOnline = eligible.find(s => s.status === 'online');
                if (firstOnline) setSelectedId(firstOnline.id);
            } catch (err) {
                console.error('Failed to load servers:', err);
            } finally {
                setLoading(false);
            }
        })();
    }, []);

    const selected = servers.find(s => s.id === selectedId) || null;
    const anyOnline = servers.some(s => s.status === 'online');

    return (
        <div className="term-shell">
            <aside className="term-shell__rail" aria-label="Terminal targets">
                <div className="term-shell__grp">Agent servers</div>
                {loading && <div className="term-shell__hint">Loading servers…</div>}
                {!loading && servers.length === 0 && (
                    <div className="term-shell__hint">No agent servers with shell access are paired yet.</div>
                )}
                {servers.map(s => {
                    const online = s.status === 'online';
                    return (
                        <button
                            key={s.id}
                            type="button"
                            className={`term-shell__row ${s.id === selectedId ? 'is-active' : ''}`}
                            onClick={() => setSelectedId(s.id)}
                            disabled={!online}
                            title={online ? `Open a shell on ${s.name}` : `${s.name || s.id} is ${s.status || 'offline'}`}
                        >
                            <ServerIcon size={14} className="term-shell__ico" />
                            <span className="term-shell__name">{s.name || s.hostname || s.id}</span>
                            {s.ip_address && <span className="term-shell__sub">{s.ip_address}</span>}
                            <span className={`term-shell__dot ${online ? 'is-on' : ''}`} />
                        </button>
                    );
                })}
            </aside>
            <div className="term-shell__main">
                {selected ? (
                    <RemoteTerminal key={selected.id} serverId={selected.id} onClose={() => setSelectedId(null)} />
                ) : (
                    <div className="term-shell__empty">
                        <TerminalIcon size={26} />
                        <p>
                            {anyOnline
                                ? 'Pick a server on the left to open a shell.'
                                : 'Interactive shells run over the ServerKit agent. Pair a server (Servers → Add Server) with shell access and it will show up here.'}
                        </p>
                    </div>
                )}
            </div>
        </div>
    );
};

const LOG_PREFS = {
    showLineNumbers: 'serverkit-logs-line-numbers',
    wrapLines: 'serverkit-logs-wrap',
    lineCount: 'serverkit-logs-line-count',
};

// Operations supported by the agent for remote targets. Only `read` is
// likely available today; everything else is panel-host-only until the
// matching agent verbs land. Mirrors the FileManager pattern.
const REMOTE_LOG_SUPPORTED = new Set(['list', 'read']);

const LogFilesTab = () => {
    const toast = useToast();
    const { confirm } = useConfirm();

    const [target, setTarget] = useState({ kind: 'local' });
    const isRemote = target.kind === 'agent';

    const [logFiles, setLogFiles] = useState([]);
    const [selectedLog, setSelectedLog] = useState(null);
    const [logContent, setLogContent] = useState('');
    const [loading, setLoading] = useState(true);
    const [loadingContent, setLoadingContent] = useState(false);
    const [error, setError] = useState(null);
    const [lastUpdated, setLastUpdated] = useState(null);

    const [lineCount, setLineCount] = useState(() => {
        const v = parseInt(localStorage.getItem(LOG_PREFS.lineCount), 10);
        return Number.isFinite(v) ? v : 200;
    });
    const [searchPattern, setSearchPattern] = useState('');
    const [appliedSearch, setAppliedSearch] = useState('');
    const [autoRefresh, setAutoRefresh] = useState(false);
    const [showLineNumbers, setShowLineNumbers] = useState(() => localStorage.getItem(LOG_PREFS.showLineNumbers) !== 'false');
    const [wrapLines, setWrapLines] = useState(() => localStorage.getItem(LOG_PREFS.wrapLines) !== 'false');
    const [isFullscreen, setIsFullscreen] = useState(false);

    const contentRef = useRef(null);
    const intervalRef = useRef(null);
    const selectedLogObj = useMemo(
        () => logFiles.find((l) => l.path === selectedLog) || null,
        [logFiles, selectedLog]
    );

    useEffect(() => { localStorage.setItem(LOG_PREFS.showLineNumbers, showLineNumbers); }, [showLineNumbers]);
    useEffect(() => { localStorage.setItem(LOG_PREFS.wrapLines, wrapLines); }, [wrapLines]);
    useEffect(() => { localStorage.setItem(LOG_PREFS.lineCount, lineCount); }, [lineCount]);

    // Reset when the target changes (clears previous server's selection)
    useEffect(() => {
        setSelectedLog(null);
        setLogContent('');
        setAutoRefresh(false);
        loadLogFiles();
    }, [target.kind, target.server_id]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (autoRefresh && selectedLog) {
            intervalRef.current = setInterval(() => {
                loadLogContent(selectedLog, false);
            }, 3000);
        }
        return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
    }, [autoRefresh, selectedLog, lineCount, appliedSearch]); // eslint-disable-line

    function ensureSupported(op) {
        if (isRemote && !REMOTE_LOG_SUPPORTED.has(op)) {
            toast.error(`This action isn't available on remote targets yet.`);
            return false;
        }
        return true;
    }

    async function loadLogFiles() {
        if (isRemote) {
            // No remote log-file listing yet — gracefully empty out so the
            // panel doesn't get confused with stale local entries.
            setLogFiles([]);
            setLoading(false);
            setError(`Remote log listing isn't available yet for ${target.name}.`);
            return;
        }
        setLoading(true);
        setError(null);
        try {
            const data = await api.getLogFiles();
            setLogFiles(data.logs || []);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }

    async function loadLogContent(logPath, showLoading = true) {
        if (showLoading) setLoadingContent(true);
        try {
            let data;
            if (appliedSearch.trim()) {
                data = await api.searchLog(logPath, appliedSearch, lineCount);
            } else {
                data = await api.readLog(logPath, lineCount);
            }
            setLogContent(data.content || data.lines?.join('\n') || '');
            setSelectedLog(logPath);
            setLastUpdated(new Date());

            if (autoRefresh && contentRef.current) {
                contentRef.current.scrollTop = contentRef.current.scrollHeight;
            }
        } catch (err) {
            setLogContent(`Error loading log: ${err.message}`);
        } finally {
            setLoadingContent(false);
        }
    }

    function handleSelectFile(log) {
        loadLogContent(log.path);
    }

    function handleSearchSubmit() {
        setAppliedSearch(searchPattern);
        if (selectedLog) {
            // Re-fetch with new search.
            (async () => {
                setLoadingContent(true);
                try {
                    const data = searchPattern.trim()
                        ? await api.searchLog(selectedLog, searchPattern, lineCount)
                        : await api.readLog(selectedLog, lineCount);
                    setLogContent(data.content || data.lines?.join('\n') || '');
                    setLastUpdated(new Date());
                } catch (err) {
                    setLogContent(`Error: ${err.message}`);
                } finally {
                    setLoadingContent(false);
                }
            })();
        }
    }

    function handleSearchClear() {
        setSearchPattern('');
        setAppliedSearch('');
        if (selectedLog) loadLogContent(selectedLog);
    }

    function scrollToBottom() {
        if (contentRef.current) {
            contentRef.current.scrollTop = contentRef.current.scrollHeight;
        }
    }

    async function handleClearLog() {
        if (!ensureSupported('clear')) return;
        if (!selectedLog) return;
        const confirmed = await confirm({
            title: 'Truncate log file',
            message: `This will permanently empty ${selectedLog}. Continue?`,
            variant: 'danger',
            confirmText: 'Truncate',
        });
        if (!confirmed) return;
        try {
            await api.clearLog(selectedLog);
            setLogContent('');
            toast.success('Log file truncated');
            loadLogFiles();
        } catch (err) {
            toast.error(`Failed: ${err.message}`);
        }
    }

    function handleDownload() {
        if (!logContent) return;
        const blob = new Blob([logContent], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = selectedLog ? selectedLog.split('/').pop() : 'log.txt';
        a.click();
        URL.revokeObjectURL(url);
    }

    const visibleLineCount = useMemo(() => {
        if (!logContent) return 0;
        return logContent.split('\n').filter(Boolean).length;
    }, [logContent]);

    return (
        <div className={`lv-page ${isFullscreen ? 'fullscreen' : ''}`}>
            <div className="lv-header">
                <div className="lv-header-target">
                    <span className="lv-header-label">Source</span>
                    <TargetPicker
                        feature="logs"
                        value={target}
                        onChange={setTarget}
                    />
                    {isRemote && (
                        <span className="lv-header-hint">
                            <AlertCircle size={12} />
                            Read-only. Most actions require panel-host access.
                        </span>
                    )}
                </div>
                <div className="lv-header-stats">
                    {selectedLogObj && (
                        <>
                            <span className="lv-stat">
                                <FileText size={12} />
                                {selectedLogObj.name}
                            </span>
                            <span className="lv-stat-divider" />
                            <span className="lv-stat">
                                <span className="lv-stat-label">Size</span>
                                <span className="lv-stat-value">{formatBytes(selectedLogObj.size)}</span>
                            </span>
                            <span className="lv-stat">
                                <span className="lv-stat-label">Showing</span>
                                <span className="lv-stat-value">{visibleLineCount.toLocaleString()} lines</span>
                            </span>
                            {lastUpdated && (
                                <span className="lv-stat">
                                    <Clock size={12} />
                                    {lastUpdated.toLocaleTimeString()}
                                </span>
                            )}
                        </>
                    )}
                </div>
            </div>

            {error && (
                <div className="lv-error">
                    <AlertCircle size={14} />
                    <span>{error}</span>
                    <button type="button" onClick={() => setError(null)}>&times;</button>
                </div>
            )}

            <div className="lv-layout">
                <LogFileList
                    files={logFiles}
                    selectedPath={selectedLog}
                    onSelect={handleSelectFile}
                    onRefresh={loadLogFiles}
                    loading={loading}
                />

                <div className="lv-viewer">
                    {selectedLog && (
                        <div className="lv-viewer-path">
                            <span className={`lv-viewer-path-dot kind-${logKindFromPath(selectedLog)}`} />
                            <code>{selectedLog}</code>
                        </div>
                    )}

                    <LogToolbar
                        searchPattern={searchPattern}
                        onSearchChange={setSearchPattern}
                        onSearchSubmit={handleSearchSubmit}
                        onSearchClear={handleSearchClear}
                        lineCount={lineCount}
                        onLineCountChange={(n) => { setLineCount(n); if (selectedLog) setTimeout(() => loadLogContent(selectedLog), 0); }}
                        autoRefresh={autoRefresh}
                        onAutoRefreshToggle={() => setAutoRefresh(!autoRefresh)}
                        showLineNumbers={showLineNumbers}
                        onToggleLineNumbers={() => setShowLineNumbers(!showLineNumbers)}
                        wrapLines={wrapLines}
                        onToggleWrap={() => setWrapLines(!wrapLines)}
                        isFullscreen={isFullscreen}
                        onToggleFullscreen={() => setIsFullscreen(!isFullscreen)}
                        onRefresh={() => selectedLog && loadLogContent(selectedLog)}
                        onDownload={handleDownload}
                        onClear={handleClearLog}
                        onScrollToBottom={scrollToBottom}
                        canAct={!!selectedLog && !loadingContent}
                    />

                    <LogContent
                        ref={contentRef}
                        live={autoRefresh}
                        scrollKey={selectedLog}
                        content={selectedLog ? logContent : ''}
                        loading={loadingContent}
                        emptyMessage={
                            isRemote && logFiles.length === 0
                                ? `Remote log browsing isn't supported yet for ${target.name}.`
                                : logFiles.length === 0
                                    ? 'No log files were found on this server.'
                                    : 'Select a log file from the list to view its contents.'
                        }
                        showLineNumbers={showLineNumbers}
                        wrapLines={wrapLines}
                        searchPattern={appliedSearch}
                    />
                </div>
            </div>
        </div>
    );
};

const COMMON_JOURNAL_UNITS = [
    { id: 'nginx', label: 'Nginx', kind: 'nginx' },
    { id: 'apache2', label: 'Apache', kind: 'apache' },
    { id: 'mysql', label: 'MySQL', kind: 'database' },
    { id: 'mariadb', label: 'MariaDB', kind: 'database' },
    { id: 'postgresql', label: 'PostgreSQL', kind: 'database' },
    { id: 'php-fpm', label: 'PHP-FPM', kind: 'php' },
    { id: 'docker', label: 'Docker', kind: 'default' },
    { id: 'sshd', label: 'SSH', kind: 'security' },
    { id: 'cron', label: 'Cron', kind: 'system' },
    { id: 'systemd', label: 'systemd', kind: 'system' },
    { id: 'fail2ban', label: 'fail2ban', kind: 'security' },
    { id: 'ufw', label: 'UFW', kind: 'security' },
];

const PRIORITY_OPTIONS = [
    { value: '', label: 'All' },
    { value: '0', label: 'Emergency' },
    { value: '1', label: 'Alert' },
    { value: '2', label: 'Critical' },
    { value: '3', label: 'Error' },
    { value: '4', label: 'Warning' },
    { value: '5', label: 'Notice' },
    { value: '6', label: 'Info' },
    { value: '7', label: 'Debug' },
];

const JOURNAL_PREFS = {
    showLineNumbers: 'serverkit-journal-line-numbers',
    wrapLines: 'serverkit-journal-wrap',
    lineCount: 'serverkit-journal-line-count',
};

const REMOTE_JOURNAL_SUPPORTED = new Set([]);

const JournalTab = () => {
    const toast = useToast();
    const [target, setTarget] = useState({ kind: 'local' });
    const isRemote = target.kind === 'agent';

    const [logContent, setLogContent] = useState('');
    const [loading, setLoading] = useState(false);
    const [unavailable, setUnavailable] = useState(false);
    const [unit, setUnit] = useState('');
    const [unitInput, setUnitInput] = useState('');
    const [lineCount, setLineCount] = useState(() => {
        const v = parseInt(localStorage.getItem(JOURNAL_PREFS.lineCount), 10);
        return Number.isFinite(v) ? v : 200;
    });
    const [priority, setPriority] = useState('');
    const [source, setSource] = useState('');
    const [sourceLabel, setSourceLabel] = useState('');
    const [autoRefresh, setAutoRefresh] = useState(false);
    const [searchPattern, setSearchPattern] = useState('');
    const [appliedSearch, setAppliedSearch] = useState('');
    const [showLineNumbers, setShowLineNumbers] = useState(() => localStorage.getItem(JOURNAL_PREFS.showLineNumbers) !== 'false');
    const [wrapLines, setWrapLines] = useState(() => localStorage.getItem(JOURNAL_PREFS.wrapLines) !== 'false');
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [unitFilter, setUnitFilter] = useState('');
    const [lastUpdated, setLastUpdated] = useState(null);

    const contentRef = useRef(null);
    const intervalRef = useRef(null);
    const isJournalctl = source === 'journalctl' || source === '';

    useEffect(() => { localStorage.setItem(JOURNAL_PREFS.showLineNumbers, showLineNumbers); }, [showLineNumbers]);
    useEffect(() => { localStorage.setItem(JOURNAL_PREFS.wrapLines, wrapLines); }, [wrapLines]);
    useEffect(() => { localStorage.setItem(JOURNAL_PREFS.lineCount, lineCount); }, [lineCount]);

    useEffect(() => {
        loadJournalLogs();
    }, [target.kind, target.server_id]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (autoRefresh) {
            intervalRef.current = setInterval(() => loadJournalLogs(false), 3000);
        }
        return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
    }, [autoRefresh, unit, lineCount, priority]); // eslint-disable-line

    async function loadJournalLogs(showSpinner = true) {
        if (isRemote && !REMOTE_JOURNAL_SUPPORTED.has('read')) {
            setLogContent('');
            setSource('');
            setUnavailable(false);
            setLoading(false);
            return;
        }
        if (showSpinner) setLoading(true);
        setUnavailable(false);
        try {
            const data = await api.getJournalLogs(unit || null, lineCount);
            setLogContent(data.lines?.join('\n') || '');
            setSource(data.source || '');
            setSourceLabel(data.source_label || '');
            setLastUpdated(new Date());
            if (autoRefresh && contentRef.current) {
                contentRef.current.scrollTop = contentRef.current.scrollHeight;
            }
        } catch (err) {
            const msg = err.message || '';
            if (msg.includes('No system log source available') || msg.includes('unavailable')) {
                setUnavailable(true);
            } else {
                setLogContent(`Error: ${msg}`);
            }
        } finally {
            setLoading(false);
        }
    }

    function pickUnit(u) {
        setUnit(u);
        setUnitInput(u);
        setTimeout(() => loadJournalLogs(), 0);
    }

    function clearUnit() {
        setUnit('');
        setUnitInput('');
        setTimeout(() => loadJournalLogs(), 0);
    }

    function applyUnitInput() {
        setUnit(unitInput);
        setTimeout(() => loadJournalLogs(), 0);
    }

    function handleDownload() {
        if (!logContent) return;
        const blob = new Blob([logContent], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `journal-${unit || 'all'}-${Date.now()}.log`;
        a.click();
        URL.revokeObjectURL(url);
    }

    function scrollToBottom() {
        if (contentRef.current) contentRef.current.scrollTop = contentRef.current.scrollHeight;
    }

    const filteredUnits = useMemo(() => {
        if (!unitFilter.trim()) return COMMON_JOURNAL_UNITS;
        const q = unitFilter.toLowerCase();
        return COMMON_JOURNAL_UNITS.filter(u => u.id.includes(q) || u.label.toLowerCase().includes(q));
    }, [unitFilter]);

    const visibleLineCount = useMemo(() => {
        if (!logContent) return 0;
        return logContent.split('\n').filter(Boolean).length;
    }, [logContent]);

    if (unavailable) {
        return (
            <div className="lv-page">
                <div className="lv-empty-hint is-tall">
                    <AlertCircle size={48} />
                    <h3 className="lv-empty-hint__title">System Logs Unavailable</h3>
                    <p>
                        No system log source was found. Neither <code>journalctl</code>,
                        <code> /var/log/syslog</code>, nor the Windows Event Log are available.
                    </p>
                    <p>Use the <strong>Log Files</strong> tab to browse available log files instead.</p>
                </div>
            </div>
        );
    }

    return (
        <div className={`lv-page ${isFullscreen ? 'fullscreen' : ''}`}>
            <div className="lv-header">
                <div className="lv-header-target">
                    <span className="lv-header-label">Source</span>
                    <TargetPicker feature="logs" value={target} onChange={setTarget} />
                    {isRemote && (
                        <span className="lv-header-hint">
                            <AlertCircle size={12} />
                            Remote journal isn&apos;t available yet for {target.name}.
                        </span>
                    )}
                    {!isJournalctl && source && (
                        <span className="lv-header-hint lv-header-hint--info">
                            <AlertCircle size={12} />
                            Reading from <strong>&nbsp;{sourceLabel}</strong>
                        </span>
                    )}
                </div>
                <div className="lv-header-stats">
                    {unit && (
                        <span className="lv-stat">
                            <span className="lv-stat-label">Unit</span>
                            <span className="lv-stat-value">{unit}</span>
                        </span>
                    )}
                    <span className="lv-stat">
                        <span className="lv-stat-label">Showing</span>
                        <span className="lv-stat-value">{visibleLineCount.toLocaleString()} lines</span>
                    </span>
                    {lastUpdated && (
                        <span className="lv-stat">
                            <Clock size={12} />
                            {lastUpdated.toLocaleTimeString()}
                        </span>
                    )}
                </div>
            </div>

            <div className="lv-layout">
                <div className="lv-sidebar">
                    <div className="lv-sidebar-header">
                        <div className="lv-search has-no-icon">
                            <input
                                type="text"
                                value={unitInput}
                                onChange={(e) => setUnitInput(e.target.value)}
                                onKeyDown={(e) => e.key === 'Enter' && applyUnitInput()}
                                placeholder="Type unit name…"
                            />
                        </div>
                        <button type="button" className="lv-icon-btn" onClick={applyUnitInput} title="Apply unit filter">
                            <Search size={13} />
                        </button>
                    </div>

                    <div className="lv-sidebar-body">
                        <div className="lv-group">
                            <button type="button"
                                    className={`lv-file lv-file--compact ${!unit ? 'active' : ''}`}
                                    onClick={clearUnit}
                                >
                                <span className="lv-file-dot" />
                                <span className="lv-file-name">All services</span>
                            </button>
                        </div>

                        <div className="lv-group">
                            <div className="lv-group-header is-static">
                                <span className="lv-group-header__spacer" />
                                <span>Common units</span>
                                <span className="lv-group-count">{filteredUnits.length}</span>
                            </div>
                            <div className="lv-group-files">
                                {filteredUnits.map(u => (
                                    <button type="button"
                                        key={u.id}
                                        className={`lv-file lv-file--compact ${unit === u.id ? 'active' : ''}}`}
                                        onClick={() => pickUnit(u.id)}
                                    >
                                        <span className={`lv-file-dot kind-${u.kind}`} />
                                        <span className="lv-file-name">{u.label}</span>
                                    </button>
                                ))}
                                {filteredUnits.length === 0 && (
                                    <div className="lv-empty-hint is-compact">
                                        <p>No matching units.</p>
                                    </div>
                                )}
                            </div>
                        </div>

                        {isJournalctl && (
                            <div className="lv-group">
                                <div className="lv-group-header is-static">
                                    <span className="lv-group-header__spacer" />
                                    <span>Priority</span>
                                </div>
                                <div className="lv-group-files">
                                    {PRIORITY_OPTIONS.map(opt => (
                                        <button type="button"
                                            key={opt.value}
                                            className={`lv-file lv-file--compact ${priority === opt.value ? 'active' : ''}`}
                                            onClick={() => { setPriority(opt.value); setTimeout(loadJournalLogs, 0); }}
                                        >
                                            <span className="lv-file-dot" style={{ background: priorityColor(opt.value) }} />
                                            <span className="lv-file-name">{opt.label}</span>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                <div className="lv-viewer">
                    {unit && (
                        <div className="lv-viewer-path">
                            <span className="lv-viewer-path-dot kind-system" />
                            <code>journalctl -u {unit}</code>
                        </div>
                    )}

                    <LogToolbar
                        searchPattern={searchPattern}
                        onSearchChange={setSearchPattern}
                        onSearchSubmit={() => setAppliedSearch(searchPattern)}
                        onSearchClear={() => { setSearchPattern(''); setAppliedSearch(''); }}
                        lineCount={lineCount}
                        onLineCountChange={(n) => { setLineCount(n); setTimeout(loadJournalLogs, 0); }}
                        autoRefresh={autoRefresh}
                        onAutoRefreshToggle={() => setAutoRefresh(!autoRefresh)}
                        showLineNumbers={showLineNumbers}
                        onToggleLineNumbers={() => setShowLineNumbers(!showLineNumbers)}
                        wrapLines={wrapLines}
                        onToggleWrap={() => setWrapLines(!wrapLines)}
                        isFullscreen={isFullscreen}
                        onToggleFullscreen={() => setIsFullscreen(!isFullscreen)}
                        onRefresh={() => loadJournalLogs()}
                        onDownload={handleDownload}
                        onClear={() => toast.error('Journal logs cannot be truncated from the panel.')}
                        onScrollToBottom={scrollToBottom}
                        canAct={!loading && !isRemote}
                    />

                    <LogContent
                        ref={contentRef}
                        live={autoRefresh}
                        scrollKey={unit || source}
                        content={logContent}
                        loading={loading}
                        emptyMessage={
                            isRemote
                                ? `Remote journal isn't supported yet for ${target.name}.`
                                : 'Loading journal…'
                        }
                        showLineNumbers={showLineNumbers}
                        wrapLines={wrapLines}
                        searchPattern={appliedSearch}
                    />
                </div>
            </div>
        </div>
    );
};

// Journal priority dot tints — categorical, aligned to the redesign palette.
function priorityColor(value) {
    if (value === '0' || value === '1' || value === '2') return '#fb6f6f';
    if (value === '3') return '#fc8d8d';
    if (value === '4') return '#f5b945';
    if (value === '5' || value === '6') return '#49c7f0';
    if (value === '7') return '#9aa1af';
    return '#646b7a';
}

const ProcessesTab = () => {
    const toast = useToast();
    const { confirm } = useConfirm();

    const [target, setTarget] = useState({ kind: 'local' });
    const isRemote = target.kind === 'agent';

    const [processes, setProcesses] = useState([]);
    const [loading, setLoading] = useState(true);
    const [sortBy, setSortBy] = useState('cpu');
    const [sortDir, setSortDir] = useState('desc');
    const [limit, setLimit] = useState(100);
    const [searchTerm, setSearchTerm] = useState('');
    const [statusFilter, setStatusFilter] = useState('all');
    const [userFilter, setUserFilter] = useState(null);
    const [selectedProcess, setSelectedProcess] = useState(null);
    const [autoRefresh, setAutoRefresh] = useState(false);
    const [lastUpdated, setLastUpdated] = useState(null);

    const intervalRef = useRef(null);

    useEffect(() => {
        loadProcesses();
    }, [sortBy, limit, target.kind, target.server_id]); // eslint-disable-line

    useEffect(() => {
        if (autoRefresh) {
            intervalRef.current = setInterval(() => loadProcesses(false), 4000);
        }
        return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
    }, [autoRefresh, sortBy, limit]); // eslint-disable-line

    async function loadProcesses(showSpinner = true) {
        if (isRemote) {
            setProcesses([]);
            setLoading(false);
            return;
        }
        if (showSpinner) setLoading(true);
        try {
            const data = await api.getProcesses(limit, sortBy);
            setProcesses(data.processes || []);
            setLastUpdated(new Date());
        } catch (err) {
            console.error('Failed to load processes:', err);
            toast.error(`Failed: ${err.message}`);
        } finally {
            setLoading(false);
        }
    }

    async function handleKillProcess(pid, force = false) {
        const confirmMsg = force
            ? `Force-kill PID ${pid}? Unsaved data may be lost.`
            : `Kill PID ${pid}?`;
        const confirmed = await confirm({
            title: force ? 'Force-kill process' : 'Kill process',
            message: confirmMsg,
            variant: force ? 'danger' : 'warning',
            confirmText: force ? 'Force kill' : 'Kill',
        });
        if (!confirmed) return;
        try {
            await api.killProcess(pid, force);
            toast.success(`PID ${pid} killed`);
            loadProcesses();
            setSelectedProcess(null);
        } catch (err) {
            toast.error(`Failed: ${err.message}`);
        }
    }

    function toggleSort(col) {
        if (sortBy === col) {
            setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
        } else {
            setSortBy(col);
            setSortDir(col === 'name' || col === 'user' ? 'asc' : 'desc');
        }
    }

    const userGroups = useMemo(() => {
        const map = new Map();
        for (const p of processes) {
            const u = p.user || 'unknown';
            map.set(u, (map.get(u) || 0) + 1);
        }
        return [...map.entries()].sort((a, b) => b[1] - a[1]);
    }, [processes]);

    const statusCounts = useMemo(() => {
        const counts = { all: processes.length, running: 0, sleeping: 0, stopped: 0, zombie: 0 };
        for (const p of processes) {
            const s = (p.status || '').toLowerCase();
            if (s === 'running') counts.running++;
            else if (s === 'sleeping') counts.sleeping++;
            else if (s === 'stopped') counts.stopped++;
            else if (s === 'zombie') counts.zombie++;
        }
        return counts;
    }, [processes]);

    const totalCpu = useMemo(() => processes.reduce((s, p) => s + (p.cpu_percent || 0), 0), [processes]);
    const totalMem = useMemo(() => processes.reduce((s, p) => s + (p.memory_info?.rss || 0), 0), [processes]);

    const filtered = useMemo(() => {
        let list = processes;
        if (userFilter) list = list.filter(p => (p.user || 'unknown') === userFilter);
        if (statusFilter !== 'all') list = list.filter(p => (p.status || '').toLowerCase() === statusFilter);
        const q = searchTerm.toLowerCase();
        if (q) {
            list = list.filter(p =>
                p.name?.toLowerCase().includes(q) ||
                p.command?.toLowerCase().includes(q) ||
                String(p.pid).includes(q)
            );
        }
        const dir = sortDir === 'asc' ? 1 : -1;
        const sorted = [...list];
        sorted.sort((a, b) => {
            switch (sortBy) {
                case 'pid': return ((a.pid || 0) - (b.pid || 0)) * dir;
                case 'name': return (a.name || '').localeCompare(b.name || '') * dir;
                case 'user': return (a.user || '').localeCompare(b.user || '') * dir;
                case 'memory': return ((a.memory_percent || 0) - (b.memory_percent || 0)) * dir;
                case 'cpu':
                default: return ((a.cpu_percent || 0) - (b.cpu_percent || 0)) * dir;
            }
        });
        return sorted;
    }, [processes, userFilter, statusFilter, searchTerm, sortBy, sortDir]);

    return (
        <div className="proc-page">
            <div className="lv-header">
                <div className="lv-header-target">
                    <span className="lv-header-label">Source</span>
                    <TargetPicker feature="processes" value={target} onChange={setTarget} />
                    {isRemote && (
                        <span className="lv-header-hint">
                            <AlertCircle size={12} />
                            Remote process control isn&apos;t available yet for {target.name}.
                        </span>
                    )}
                </div>
                <div className="lv-header-stats">
                    <span className="lv-stat">
                        <span className="lv-stat-label">Total</span>
                        <span className="lv-stat-value">{processes.length}</span>
                    </span>
                    <span className="lv-stat">
                        <span className="lv-stat-label">CPU</span>
                        <span className="lv-stat-value">{totalCpu.toFixed(1)}%</span>
                    </span>
                    <span className="lv-stat">
                        <span className="lv-stat-label">Memory</span>
                        <span className="lv-stat-value">{formatMemory(totalMem)}</span>
                    </span>
                    {lastUpdated && (
                        <span className="lv-stat">
                            <Clock size={12} />
                            {lastUpdated.toLocaleTimeString()}
                        </span>
                    )}
                </div>
            </div>

            <div className="proc-toolbar">
                <div className="proc-filter-chips">
                    {[
                        { id: 'all', label: 'All', count: statusCounts.all },
                        { id: 'running', label: 'Running', count: statusCounts.running },
                        { id: 'sleeping', label: 'Sleeping', count: statusCounts.sleeping },
                        { id: 'stopped', label: 'Stopped', count: statusCounts.stopped },
                        { id: 'zombie', label: 'Zombie', count: statusCounts.zombie },
                    ].map(c => (
                        <button type="button"
                            key={c.id}
                            className={`proc-chip ${statusFilter === c.id ? 'active' : ''}`}
                            onClick={() => setStatusFilter(c.id)}
                            disabled={c.id !== 'all' && c.count === 0}
                        >
                            <span>{c.label}</span>
                            <span className="proc-chip-count">{c.count}</span>
                        </button>
                    ))}
                </div>
                <div className="proc-toolbar-right">
                    <div className="lv-search-field">
                        <Search size={13} className="lv-search-field-icon" />
                        <input
                            type="text"
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                            placeholder="Filter PID, name, command…"
                        />
                        {searchTerm && (
                            <button type="button" className="lv-search-field-clear" onClick={() => setSearchTerm('')}>
                                <X size={11} />
                            </button>
                        )}
                    </div>
                    <select
                        className="lv-select"
                        value={limit}
                        onChange={(e) => setLimit(parseInt(e.target.value, 10))}
                    >
                        <option value={25}>Top 25</option>
                        <option value={50}>Top 50</option>
                        <option value={100}>Top 100</option>
                        <option value={250}>Top 250</option>
                    </select>
                    <button type="button"
                        className={`lv-chip ${autoRefresh ? 'active' : ''}`}
                        onClick={() => setAutoRefresh(!autoRefresh)}
                        disabled={isRemote}
                    >
                        <span className={`lv-pulse ${autoRefresh ? 'on' : ''}`} />
                        <span>Live</span>
                    </button>
                    <Button size="icon" variant="ghost" className="lv-icon-btn" onClick={() => loadProcesses()} title="Refresh" aria-label="Refresh processes">
                        <RefreshCw size={13} className={loading ? 'spinning' : ''} />
                    </Button>
                </div>
            </div>

            <div className="proc-layout">
                <aside className="proc-sidebar">
                    <div className="lv-sidebar-header">
                        <span className="lv-header-label is-indented">Users</span>
                    </div>
                    <div className="lv-sidebar-body">
                        <button type="button"
                            className={`lv-file ${!userFilter ? 'active' : ''}`}
                            onClick={() => setUserFilter(null)}
                        >
                            <span className="lv-file-dot is-accent" />
                            <span className="lv-file-name">All users</span>
                            <span className="lv-file-size">{processes.length}</span>
                        </button>
                        {userGroups.map(([user, count]) => (
                            <button type="button"
                                key={user}
                                className={`lv-file ${userFilter === user ? 'active' : ''}`}
                                onClick={() => setUserFilter(user)}
                            >
                                <span className="lv-file-dot" style={{ background: hashColor(user) }} />
                                <span className="lv-file-name">{user}</span>
                                <span className="lv-file-size">{count}</span>
                            </button>
                        ))}
                    </div>
                </aside>

                <div className="proc-main">
                    {loading ? (
                        <div className="lv-content-loading">Loading processes…</div>
                    ) : filtered.length === 0 ? (
                        <div className="lv-empty-hint is-medium">
                            <p>No processes match your filters.</p>
                        </div>
                    ) : (
                        <div className="proc-table-wrap">
                            <table className="proc-table">
                                <thead>
                                    <tr>
                                        <th onClick={() => toggleSort('pid')} className={sortBy === 'pid' ? 'active' : ''}>
                                            PID {sortBy === 'pid' && (sortDir === 'asc' ? '↑' : '↓')}
                                        </th>
                                        <th onClick={() => toggleSort('name')} className={sortBy === 'name' ? 'active' : ''}>
                                            Process {sortBy === 'name' && (sortDir === 'asc' ? '↑' : '↓')}
                                        </th>
                                        <th onClick={() => toggleSort('user')} className={sortBy === 'user' ? 'active' : ''}>
                                            User {sortBy === 'user' && (sortDir === 'asc' ? '↑' : '↓')}
                                        </th>
                                        <th onClick={() => toggleSort('cpu')} className={sortBy === 'cpu' ? 'active' : ''}>
                                            CPU {sortBy === 'cpu' && (sortDir === 'asc' ? '↑' : '↓')}
                                        </th>
                                        <th onClick={() => toggleSort('memory')} className={sortBy === 'memory' ? 'active' : ''}>
                                            Memory {sortBy === 'memory' && (sortDir === 'asc' ? '↑' : '↓')}
                                        </th>
                                        <th>Status</th>
                                        <th></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {filtered.map(p => {
                                        const cpu = Math.min(Number(p.cpu_percent) || 0, 100);
                                        const mem = Math.min(Number(p.memory_percent) || 0, 100);
                                        const isSelected = selectedProcess?.pid === p.pid;
                                        return (
                                            <tr
                                                key={p.pid}
                                                className={isSelected ? 'selected' : ''}
                                                onClick={() => setSelectedProcess(p)}
                                            >
                                                <td className="mono">{p.pid}</td>
                                                <td>
                                                    <div className="proc-name-cell">
                                                        <span className="proc-name">{p.name}</span>
                                                        {p.command && (
                                                            <span className="proc-cmd" title={p.command}>{p.command}</span>
                                                        )}
                                                    </div>
                                                </td>
                                                <td>
                                                    <span className="proc-user-tag">
                                                        <span className="proc-user-dot" style={{ background: hashColor(p.user) }} />
                                                        {p.user}
                                                    </span>
                                                </td>
                                                <td>
                                                    <div className="proc-bar-cell">
                                                        <span className="proc-bar-value">{cpu.toFixed(1)}%</span>
                                                        <div className="proc-bar"><div className="proc-bar-fill cpu" style={{ width: `${cpu}%` }} /></div>
                                                    </div>
                                                </td>
                                                <td>
                                                    <div className="proc-bar-cell">
                                                        <span className="proc-bar-value">{formatMemory(p.memory_info?.rss)}</span>
                                                        <div className="proc-bar"><div className="proc-bar-fill mem" style={{ width: `${mem}%` }} /></div>
                                                    </div>
                                                </td>
                                                <td>
                                                    <Pill kind={processStatusKind(p.status)}>{p.status}</Pill>
                                                </td>
                                                <td className="proc-actions" onClick={(e) => e.stopPropagation()}>
                                                    <button type="button" className="lv-icon-btn" onClick={() => handleKillProcess(p.pid)} title="Kill (SIGTERM)">
                                                        <X size={13} />
                                                    </button>
                                                    <button type="button" className="lv-icon-btn danger" onClick={() => handleKillProcess(p.pid, true)} title="Force kill (SIGKILL)">
                                                        <AlertTriangle size={13} />
                                                    </button>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>

            {/* The shared DS drawer, not a hand-rolled slide-over: focus trap,
                escape-to-close and the same chrome as every other drawer. */}
            <Drawer
                open={!!selectedProcess}
                onOpenChange={(open) => { if (!open) setSelectedProcess(null); }}
                title={selectedProcess?.name || ''}
                subtitle={selectedProcess ? `PID ${selectedProcess.pid} · ${selectedProcess.user}` : ''}
                icon={<Activity size={18} />}
                width={520}
                flush
            >
                {selectedProcess && (
                    <>
                        <div className="preview-drawer-meta">
                            <div className="meta-item">
                                <span className="meta-label">PID</span>
                                <span className="meta-value mono">{selectedProcess.pid}</span>
                            </div>
                            <div className="meta-item">
                                <span className="meta-label">User</span>
                                <span className="meta-value">{selectedProcess.user}</span>
                            </div>
                            <div className="meta-item">
                                <span className="meta-label">Status</span>
                                <span className="meta-value">{selectedProcess.status}</span>
                            </div>
                            <div className="meta-item">
                                <span className="meta-label">Threads</span>
                                <span className="meta-value">{selectedProcess.num_threads ?? '—'}</span>
                            </div>
                            <div className="meta-item">
                                <span className="meta-label">CPU</span>
                                <span className="meta-value">{(selectedProcess.cpu_percent || 0).toFixed(2)}%</span>
                            </div>
                            <div className="meta-item">
                                <span className="meta-label">Memory</span>
                                <span className="meta-value">{formatMemory(selectedProcess.memory_info?.rss)}</span>
                            </div>
                            <div className="meta-item meta-item-wide">
                                <span className="meta-label">Started</span>
                                <span className="meta-value">
                                    {selectedProcess.create_time
                                        ? new Date(selectedProcess.create_time * 1000).toLocaleString()
                                        : '—'}
                                </span>
                            </div>
                        </div>
                        <div className="preview-drawer-actions">
                            <button type="button" className="drawer-action-btn" onClick={() => handleKillProcess(selectedProcess.pid)}>
                                <X size={14} /> Kill (SIGTERM)
                            </button>
                            <button type="button" className="drawer-action-btn danger" onClick={() => handleKillProcess(selectedProcess.pid, true)}>
                                <AlertTriangle size={14} /> Force kill (SIGKILL)
                            </button>
                        </div>
                        <div className="preview-drawer-body is-padded">
                            {selectedProcess.command && (
                                <>
                                    <div className="meta-label is-spaced">Command</div>
                                    <pre className="proc-command">{selectedProcess.command}</pre>
                                </>
                            )}
                        </div>
                    </>
                )}
            </Drawer>
        </div>
    );
};

// Stable colour from a string — used to tag users by colour (categorical
// tints aligned to the redesign palette).
function hashColor(str) {
    if (!str) return '#646b7a';
    const palette = ['#6d7cff', '#3ddc97', '#f5b945', '#ec4899', '#14b8a6', '#b07bf5', '#49c7f0', '#fb7185'];
    let h = 0;
    for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0;
    return palette[Math.abs(h) % palette.length];
}

// Map a service status kind onto a ds Pill tone.
const SVC_PILL_KIND = { running: 'green', failed: 'red', stopped: 'gray', other: 'amber' };

const ServicesTab = () => {
    const toast = useToast();
    const { confirm } = useConfirm();

    const [target, setTarget] = useState({ kind: 'local' });
    const isRemote = target.kind === 'agent';

    const [services, setServices] = useState([]);
    const [loading, setLoading] = useState(true);
    const [actionLoading, setActionLoading] = useState(null);
    const [statusFilter, setStatusFilter] = useState('all');
    const [searchTerm, setSearchTerm] = useState('');
    const [selectedService, setSelectedService] = useState(null);
    const [serviceLogs, setServiceLogs] = useState('');
    const [logsLoading, setLogsLoading] = useState(false);
    const [logSearch, setLogSearch] = useState('');
    const [appliedLogSearch, setAppliedLogSearch] = useState('');
    const [logLineCount, setLogLineCount] = useState(200);
    const [logShowLineNumbers, setLogShowLineNumbers] = useState(true);
    const [logWrap, setLogWrap] = useState(true);
    const [logAutoRefresh, setLogAutoRefresh] = useState(false);
    const logContentRef = useRef(null);
    const logIntervalRef = useRef(null);

    useEffect(() => {
        loadServices();
    }, [target.kind, target.server_id]); // eslint-disable-line

    useEffect(() => {
        if (logAutoRefresh && selectedService) {
            logIntervalRef.current = setInterval(() => loadServiceLogs(selectedService, false), 3000);
        }
        return () => { if (logIntervalRef.current) clearInterval(logIntervalRef.current); };
    }, [logAutoRefresh, selectedService, logLineCount, appliedLogSearch]); // eslint-disable-line

    async function loadServices() {
        if (isRemote) {
            setServices([]);
            setLoading(false);
            return;
        }
        setLoading(true);
        try {
            const data = await api.getServicesStatus();
            setServices(data.services || []);
        } catch (err) {
            toast.error(`Failed: ${err.message}`);
        } finally {
            setLoading(false);
        }
    }

    async function handleAction(serviceName, action) {
        const isDestructive = action === 'stop' || action === 'restart';
        if (isDestructive) {
            const ok = await confirm({
                title: action === 'stop' ? 'Stop service' : 'Restart service',
                message: `${action === 'stop' ? 'Stop' : 'Restart'} ${serviceName}?`,
                variant: 'warning',
                confirmText: action === 'stop' ? 'Stop' : 'Restart',
            });
            if (!ok) return;
        }
        setActionLoading(`${serviceName}-${action}`);
        try {
            await api.controlService(serviceName, action);
            toast.success(`${serviceName} ${action}ed`);
            await loadServices();
        } catch (err) {
            toast.error(`Failed to ${action} ${serviceName}: ${err.message}`);
        } finally {
            setActionLoading(null);
        }
    }

    async function loadServiceLogs(serviceName, showSpinner = true) {
        if (showSpinner) setLogsLoading(true);
        try {
            const data = await api.getJournalLogs(serviceName, logLineCount);
            setServiceLogs(data.lines?.join('\n') || '');
            if (logAutoRefresh && logContentRef.current) {
                logContentRef.current.scrollTop = logContentRef.current.scrollHeight;
            }
        } catch (err) {
            setServiceLogs(`Error: ${err.message}`);
        } finally {
            setLogsLoading(false);
        }
    }

    function openServiceDrawer(service) {
        setSelectedService(service);
        setLogSearch('');
        setAppliedLogSearch('');
        loadServiceLogs(service.name);
    }

    function closeServiceDrawer() {
        setSelectedService(null);
        setLogAutoRefresh(false);
        setServiceLogs('');
    }

    function statusKind(status) {
        const s = (status || '').toLowerCase();
        if (s === 'running' || s === 'active') return 'running';
        if (s === 'failed') return 'failed';
        if (s === 'stopped' || s === 'inactive' || s === 'dead') return 'stopped';
        return 'other';
    }

    const counts = useMemo(() => {
        const c = { all: services.length, running: 0, stopped: 0, failed: 0 };
        for (const s of services) {
            const k = statusKind(s.status);
            if (k === 'running') c.running++;
            else if (k === 'stopped') c.stopped++;
            else if (k === 'failed') c.failed++;
        }
        return c;
    }, [services]);

    const filtered = useMemo(() => {
        let list = services;
        if (statusFilter !== 'all') list = list.filter(s => statusKind(s.status) === statusFilter);
        const q = searchTerm.toLowerCase();
        if (q) {
            list = list.filter(s =>
                s.name?.toLowerCase().includes(q) ||
                s.description?.toLowerCase().includes(q)
            );
        }
        return list.slice().sort((a, b) => {
            const ak = statusKind(a.status), bk = statusKind(b.status);
            const order = { failed: 0, running: 1, other: 2, stopped: 3 };
            if (ak !== bk) return (order[ak] ?? 4) - (order[bk] ?? 4);
            return (a.name || '').localeCompare(b.name || '');
        });
    }, [services, statusFilter, searchTerm]);

    return (
        <div className="svc-page">
            <div className="lv-header">
                <div className="lv-header-target">
                    <span className="lv-header-label">Source</span>
                    <TargetPicker feature="services" value={target} onChange={setTarget} />
                    {isRemote && (
                        <span className="lv-header-hint">
                            <AlertCircle size={12} />
                            Remote service control isn&apos;t available yet for {target.name}.
                        </span>
                    )}
                </div>
                <div className="lv-header-stats">
                    <span className="lv-stat">
                        <span className="lv-stat-label">Total</span>
                        <span className="lv-stat-value">{services.length}</span>
                    </span>
                    <button type="button"
                        className="lv-icon-btn"
                        onClick={loadServices}
                        title="Refresh"
                    >
                        <RefreshCw size={13} className={loading ? 'spinning' : ''} />
                    </button>
                </div>
            </div>

            <div className="svc-toolbar">
                <div className="proc-filter-chips">
                    {[
                        { id: 'all', label: 'All', count: counts.all },
                        { id: 'running', label: 'Running', count: counts.running },
                        { id: 'failed', label: 'Failed', count: counts.failed },
                        { id: 'stopped', label: 'Stopped', count: counts.stopped },
                    ].map(c => (
                        <button type="button"
                            key={c.id}
                            className={`proc-chip ${statusFilter === c.id ? 'active' : ''}`}
                            onClick={() => setStatusFilter(c.id)}
                            disabled={c.id !== 'all' && c.count === 0}
                        >
                            <span>{c.label}</span>
                            <span className="proc-chip-count">{c.count}</span>
                        </button>
                    ))}
                </div>
                <div className="lv-search-field is-wide">
                    <Search size={13} className="lv-search-field-icon" />
                    <input
                        type="text"
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        placeholder="Filter services…"
                    />
                    {searchTerm && (
                        <button type="button" className="lv-search-field-clear" onClick={() => setSearchTerm('')}>
                            <X size={11} />
                        </button>
                    )}
                </div>
            </div>

            {loading ? (
                <div className="lv-content-loading is-medium">Loading services…</div>
            ) : filtered.length === 0 ? (
                <div className="lv-empty-hint is-medium">
                    <p>{services.length === 0 ? 'No services found.' : 'No services match the current filters.'}</p>
                </div>
            ) : (
                <div className="svc-grid">
                    {filtered.map(service => {
                        const kind = statusKind(service.status);
                        const isRunning = kind === 'running';
                        const isFailed = kind === 'failed';
                        return (
                            <div
                                key={service.name}
                                className={`svc-card status-${kind}`}
                                onClick={() => openServiceDrawer(service)}
                            >
                                <div className="svc-card-head">
                                    <div className="svc-card-title">
                                        <span className={`svc-status-dot status-${kind}`} />
                                        <h4>{service.name}</h4>
                                    </div>
                                    <Pill kind={SVC_PILL_KIND[kind] || 'gray'}>
                                        {service.status || 'unknown'}
                                    </Pill>
                                </div>
                                {service.description && (
                                    <p className="svc-card-desc" title={service.description}>
                                        {service.description}
                                    </p>
                                )}
                                <div className="svc-card-meta">
                                    {service.pid && (
                                        <span><span className="svc-meta-label">PID</span> {service.pid}</span>
                                    )}
                                    {service.memory && (
                                        <span><span className="svc-meta-label">Mem</span> {service.memory}</span>
                                    )}
                                </div>
                                <div className="svc-card-actions" onClick={(e) => e.stopPropagation()}>
                                    {isRunning ? (
                                        <>
                                            <button type="button"
                                                className="svc-action-btn"
                                                onClick={() => handleAction(service.name, 'restart')}
                                                disabled={actionLoading === `${service.name}-restart`}
                                            >
                                                <RotateCw size={12} /> Restart
                                            </button>
                                            <button type="button"
                                                className="svc-action-btn"
                                                onClick={() => handleAction(service.name, 'stop')}
                                                disabled={actionLoading === `${service.name}-stop`}
                                            >
                                                <Square size={12} /> Stop
                                            </button>
                                        </>
                                    ) : (
                                        <button type="button"
                                            className={`svc-action-btn primary ${isFailed ? 'danger' : ''}`}
                                            onClick={() => handleAction(service.name, 'start')}
                                            disabled={actionLoading === `${service.name}-start`}
                                        >
                                            <Play size={12} /> Start
                                        </button>
                                    )}
                                    <button type="button"
                                        className="svc-action-btn ghost"
                                        onClick={() => openServiceDrawer(service)}
                                    >
                                        <FileText size={12} /> Logs
                                    </button>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            <Drawer
                open={!!selectedService}
                onOpenChange={(open) => { if (!open) closeServiceDrawer(); }}
                title={selectedService?.name || ''}
                subtitle={selectedService
                    ? (selectedService.description || `journalctl -u ${selectedService.name}`)
                    : ''}
                icon={selectedService
                    ? <span className={`svc-status-dot status-${statusKind(selectedService.status)} is-large`} />
                    : null}
                width={520}
                flush
            >
                {selectedService && (
                    <>
                        <div className="preview-drawer-meta">
                            <div className="meta-item">
                                <span className="meta-label">Status</span>
                                <span className="meta-value">{selectedService.status || 'unknown'}</span>
                            </div>
                            {selectedService.pid && (
                                <div className="meta-item">
                                    <span className="meta-label">PID</span>
                                    <span className="meta-value mono">{selectedService.pid}</span>
                                </div>
                            )}
                            {selectedService.memory && (
                                <div className="meta-item">
                                    <span className="meta-label">Memory</span>
                                    <span className="meta-value">{selectedService.memory}</span>
                                </div>
                            )}
                        </div>

                        <div className="preview-drawer-actions">
                            {statusKind(selectedService.status) === 'running' ? (
                                <>
                                    <button type="button"
                                        className="drawer-action-btn"
                                        onClick={() => handleAction(selectedService.name, 'restart')}
                                        disabled={actionLoading === `${selectedService.name}-restart`}
                                    >
                                        <RotateCw size={14} /> Restart
                                    </button>
                                    <button type="button"
                                        className="drawer-action-btn"
                                        onClick={() => handleAction(selectedService.name, 'stop')}
                                        disabled={actionLoading === `${selectedService.name}-stop`}
                                    >
                                        <Square size={14} /> Stop
                                    </button>
                                </>
                            ) : (
                                <button type="button"
                                    className="drawer-action-btn"
                                    onClick={() => handleAction(selectedService.name, 'start')}
                                    disabled={actionLoading === `${selectedService.name}-start`}
                                >
                                    <Play size={14} /> Start
                                </button>
                            )}
                        </div>

                        <LogToolbar
                            searchPattern={logSearch}
                            onSearchChange={setLogSearch}
                            onSearchSubmit={() => setAppliedLogSearch(logSearch)}
                            onSearchClear={() => { setLogSearch(''); setAppliedLogSearch(''); }}
                            lineCount={logLineCount}
                            onLineCountChange={(n) => { setLogLineCount(n); setTimeout(() => loadServiceLogs(selectedService.name), 0); }}
                            autoRefresh={logAutoRefresh}
                            onAutoRefreshToggle={() => setLogAutoRefresh(!logAutoRefresh)}
                            showLineNumbers={logShowLineNumbers}
                            onToggleLineNumbers={() => setLogShowLineNumbers(!logShowLineNumbers)}
                            wrapLines={logWrap}
                            onToggleWrap={() => setLogWrap(!logWrap)}
                            isFullscreen={false}
                            onToggleFullscreen={() => {}}
                            onRefresh={() => loadServiceLogs(selectedService.name)}
                            onDownload={() => {
                                if (!serviceLogs) return;
                                const blob = new Blob([serviceLogs], { type: 'text/plain' });
                                const url = URL.createObjectURL(blob);
                                const a = document.createElement('a');
                                a.href = url;
                                a.download = `${selectedService.name}-${Date.now()}.log`;
                                a.click();
                                URL.revokeObjectURL(url);
                            }}
                            onClear={() => toast.error('Journal logs cannot be truncated.')}
                            onScrollToBottom={() => {
                                if (logContentRef.current) logContentRef.current.scrollTop = logContentRef.current.scrollHeight;
                            }}
                            canAct={true}
                        />

                        <div className="preview-drawer-body">
                            <LogContent
                                ref={logContentRef}
                                live={logAutoRefresh}
                                scrollKey={selectedService?.name}
                                content={serviceLogs}
                                loading={logsLoading}
                                emptyMessage="No log output."
                                showLineNumbers={logShowLineNumbers}
                                wrapLines={logWrap}
                                searchPattern={appliedLogSearch}
                            />
                        </div>
                    </>
                )}
            </Drawer>
        </div>
    );
};

// Map a process status onto a ds Pill tone.
function processStatusKind(status) {
    switch (status?.toLowerCase()) {
        case 'running':
            return 'green';
        case 'sleeping':
            return 'cyan';
        case 'stopped':
        case 'zombie':
            return 'red';
        case 'idle':
        case 'disk-sleep':
            return 'amber';
        default:
            return 'gray';
    }
}

export default Terminal;
