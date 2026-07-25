import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import EmptyState from '../components/EmptyState';
import { Pill, PageTopbar } from '@/components/ds';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { timeAgo, formatDuration } from '../utils/time';
import {
    FlaskConical, Play, Square, ChevronDown, ChevronRight,
    Zap, Package, AlertTriangle, RefreshCw,
} from 'lucide-react';

const POLL_MS = 2500;
const HISTORY_LIMIT = 20;

const FAMILY_META = {
    debian: { label: 'Debian', kind: 'cyan' },
    rhel: { label: 'RHEL', kind: 'amber' },
    suse: { label: 'SUSE', kind: 'violet' },
};

const RESULT_PILL = {
    queued: 'gray',
    running: 'cyan',
    passed: 'green',
    failed: 'red',
};

const RUN_PILL = {
    running: 'cyan',
    done: 'green',
    cancelled: 'amber',
    error: 'red',
};

const MODES = [
    {
        value: 'quick',
        icon: Zap,
        title: 'Quick',
        desc: 'Shell unit suites in plain distro containers.',
        eta: '~1–2 min per distro',
    },
    {
        value: 'full',
        icon: Package,
        title: 'Full install',
        desc: 'Real install.sh in privileged systemd containers.',
        eta: '~5–15 min per distro',
    },
];

// Pass/fail tallies derived from a run's per-distro results.
const summarizeRun = (run) => {
    const results = Object.values(run?.results || {});
    return {
        passed: results.filter((r) => r.status === 'passed').length,
        failed: results.filter((r) => r.status === 'failed').length,
        total: (run?.distros || []).length || results.length,
    };
};

// Per-distro results list with expandable log viewers. Shared between the
// active run panel and expanded history rows.
function RunResults({ run, distroMeta, logs, openLogs, onToggleLog }) {
    const results = run.results || {};
    const keys = run.distros?.length ? run.distros : Object.keys(results);

    return (
        <div className="ts-results">
            {keys.map((key) => {
                const meta = distroMeta[key] || {};
                const result = results[key] || { status: 'queued' };
                const logKey = `${run.id}:${key}`;
                const open = openLogs.has(logKey);
                const log = logs[logKey];
                const family = FAMILY_META[meta.family];
                return (
                    <div className="ts-result" key={key}>
                        <Button
                            variant="ghost"
                            className="ts-result__head"
                            onClick={() => onToggleLog(run.id, key)}
                            aria-expanded={open}
                        >
                            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                            <span className="ts-result__name">{meta.label || key}</span>
                            {family && (
                                <Pill kind={family.kind} dot={false}>{family.label}</Pill>
                            )}
                            <span className="ts-result__spacer" />
                            {result.duration_s != null && (
                                <span className="ts-result__duration">{formatDuration(result.duration_s)}</span>
                            )}
                            {result.status === 'running' && <span className="spinner-inline" />}
                            <Pill kind={RESULT_PILL[result.status] || 'gray'}>{result.status}</Pill>
                        </Button>
                        {result.detail && (
                            <div className="ts-result__detail">{result.detail}</div>
                        )}
                        {open && (
                            <div className="ts-logwrap">
                                {log?.error ? (
                                    <pre className="ts-log ts-log--error">{log.error}</pre>
                                ) : log?.loading && !log?.text ? (
                                    <pre className="ts-log ts-log--muted">Loading log…</pre>
                                ) : (
                                    <pre className="ts-log">{log?.text || 'No log output yet.'}</pre>
                                )}
                            </div>
                        )}
                    </div>
                );
            })}
        </div>
    );
}

const TestSandbox = () => {
    const toast = useToast();

    const [distros, setDistros] = useState([]);
    const [dockerAvailable, setDockerAvailable] = useState(true);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState(null);

    const [mode, setMode] = useState('quick');
    const [selected, setSelected] = useState(() => new Set());

    const [runs, setRuns] = useState([]);
    const [runsLoading, setRunsLoading] = useState(true);

    const [activeRun, setActiveRun] = useState(null);
    const [starting, setStarting] = useState(false);
    const [cancelling, setCancelling] = useState(false);

    // Log viewer state, keyed `${runId}:${distroKey}`.
    const [logs, setLogs] = useState({});
    const [openLogs, setOpenLogs] = useState(() => new Set());
    const openLogsRef = useRef(openLogs);
    useEffect(() => { openLogsRef.current = openLogs; }, [openLogs]);

    // Expanded history rows, keyed by run id -> full Run object.
    const [expandedRuns, setExpandedRuns] = useState({});

    const distroMeta = useMemo(
        () => Object.fromEntries(distros.map((d) => [d.key, d])),
        [distros]
    );

    const loadDistros = useCallback(async () => {
        const data = await api.getTestSandboxDistros();
        setDistros(data.distros || []);
        setDockerAvailable(data.docker_available !== false);
    }, []);

    const loadRuns = useCallback(async () => {
        try {
            const data = await api.getTestSandboxRuns(HISTORY_LIMIT);
            const list = data.runs || [];
            setRuns(list);
            return list;
        } catch (err) {
            toast.error(err.message);
            return [];
        } finally {
            setRunsLoading(false);
        }
    }, [toast]);

    useEffect(() => {
        (async () => {
            try {
                await loadDistros();
            } catch (err) {
                setLoadError(err.message);
            } finally {
                setLoading(false);
            }
            // Adopt an already-running run so the page picks up polling
            // after a reload mid-run.
            const list = await loadRuns();
            const running = list.find((r) => r.status === 'running');
            if (running) setActiveRun(running);
        })();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Poll the active run until it leaves the 'running' state.
    useEffect(() => {
        if (!activeRun || activeRun.status !== 'running') return undefined;
        let stopped = false;
        const tick = async () => {
            try {
                const res = await api.getTestSandboxRun(activeRun.id);
                if (stopped) return;
                setActiveRun(res.run);
                if (res.run.status !== 'running') {
                    const { passed, failed, total } = summarizeRun(res.run);
                    if (res.run.status === 'done') {
                        toast[failed > 0 ? 'error' : 'success'](
                            `Run finished: ${passed}/${total} passed${failed ? ` (${failed} failed)` : ''}`
                        );
                    } else if (res.run.status === 'error') {
                        toast.error(res.run.error || 'Run failed');
                    }
                    loadRuns();
                }
            } catch (err) {
                if (!stopped) toast.error(err.message);
            }
        };
        const id = setInterval(tick, POLL_MS);
        return () => { stopped = true; clearInterval(id); };
    }, [activeRun?.id, activeRun?.status]); // eslint-disable-line react-hooks/exhaustive-deps

    const fetchLog = useCallback(async (runId, distroKey, { silent = false } = {}) => {
        const key = `${runId}:${distroKey}`;
        setLogs((prev) => ({
            ...prev,
            [key]: { text: prev[key]?.text || '', loading: !silent, error: null },
        }));
        try {
            const text = await api.getTestSandboxRunLog(runId, distroKey);
            setLogs((prev) => ({ ...prev, [key]: { text, loading: false, error: null } }));
        } catch (err) {
            setLogs((prev) => ({
                ...prev,
                [key]: { text: prev[key]?.text || '', loading: false, error: err.message },
            }));
        }
    }, []);

    // Auto-refresh open logs for distros still executing in the active run.
    useEffect(() => {
        if (!activeRun || activeRun.status !== 'running') return undefined;
        const id = setInterval(() => {
            for (const key of openLogsRef.current) {
                const sep = key.indexOf(':');
                const runId = key.slice(0, sep);
                const distroKey = key.slice(sep + 1);
                if (runId !== String(activeRun.id)) continue;
                const status = activeRun.results?.[distroKey]?.status;
                if (status === 'running' || status === 'queued') {
                    fetchLog(runId, distroKey, { silent: true });
                }
            }
        }, POLL_MS);
        return () => clearInterval(id);
    }, [activeRun, fetchLog]);

    const toggleLog = useCallback((runId, distroKey) => {
        const key = `${runId}:${distroKey}`;
        setOpenLogs((prev) => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
        if (!openLogsRef.current.has(key)) {
            fetchLog(runId, distroKey);
        }
    }, [fetchLog]);

    const handleModeChange = (nextMode) => {
        setMode(nextMode);
        if (nextMode === 'full') {
            // Distros without full support can't stay selected in full mode.
            setSelected((prev) => {
                const next = new Set();
                for (const key of prev) {
                    if (distroMeta[key]?.full) next.add(key);
                }
                return next;
            });
        }
    };

    const toggleDistro = (key) => {
        setSelected((prev) => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    };

    const selectableKeys = distros.filter((d) => mode === 'quick' || d.full).map((d) => d.key);

    const handleSelectAll = () => setSelected(new Set(selectableKeys));
    const handleClear = () => setSelected(new Set());

    const isRunning = activeRun?.status === 'running';

    const handleStart = async () => {
        if (selected.size === 0) return;
        setStarting(true);
        try {
            const res = await api.startTestSandboxRun([...selected], mode);
            setActiveRun(res.run);
            toast.success(`Started ${mode} run across ${res.run.distros.length} distro(s)`);
            loadRuns();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setStarting(false);
        }
    };

    const handleCancel = async () => {
        if (!activeRun) return;
        setCancelling(true);
        try {
            await api.cancelTestSandboxRun(activeRun.id);
            toast.success('Run cancelled');
            const res = await api.getTestSandboxRun(activeRun.id);
            setActiveRun(res.run);
            loadRuns();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setCancelling(false);
        }
    };

    const toggleHistoryRun = async (run) => {
        if (expandedRuns[run.id]) {
            setExpandedRuns((prev) => {
                const next = { ...prev };
                delete next[run.id];
                return next;
            });
            return;
        }
        try {
            const res = await api.getTestSandboxRun(run.id);
            setExpandedRuns((prev) => ({ ...prev, [run.id]: res.run }));
        } catch (err) {
            toast.error(err.message);
        }
    };

    if (loading) {
        return (
            <div className="page-container test-sandbox-page">
                <EmptyState loading loadingVariant="table" size="lg" title="Loading test sandbox..." />
            </div>
        );
    }

    return (
        <div className="page-container test-sandbox-page">
            <PageTopbar
                icon={<FlaskConical size={18} />}
                title="Test Sandbox"
                actions={(
                    <Button
                        variant="outline"
                        onClick={() => { loadRuns(); }}
                        disabled={runsLoading}
                    >
                        <RefreshCw size={15} />
                        Refresh
                    </Button>
                )}
            />

            <p className="ts-intro">
                Run the ServerKit test matrix against real Linux distros in Docker
                containers — pick distros, pick a mode, and watch per-distro
                pass/fail results with live logs.
            </p>

            {loadError && (
                <div className="alert alert-danger">
                    {loadError}
                    <Button variant="ghost" size="sm" onClick={() => setLoadError(null)} className="alert-close">&times;</Button>
                </div>
            )}

            {!dockerAvailable && (
                <div className="alert alert-warning">
                    <AlertTriangle size={16} />
                    Docker is not available on this host — test runs cannot start until the Docker daemon is reachable.
                </div>
            )}

            {/* ── New run ─────────────────────────────────── */}
            <Card className="ts-setup">
                <CardHeader className="ts-setup__head">
                    <CardTitle>New run</CardTitle>
                    <div className="ts-setup__picker-actions">
                        <Button variant="ghost" size="sm" onClick={handleSelectAll} disabled={selectableKeys.length === 0}>
                            Select all
                        </Button>
                        <Button variant="ghost" size="sm" onClick={handleClear} disabled={selected.size === 0}>
                            Clear
                        </Button>
                    </div>
                </CardHeader>
                <CardContent>
                    <div className="ts-modes" role="radiogroup" aria-label="Test mode">
                        {MODES.map((m) => {
                            const ModeIcon = m.icon;
                            return (
                                <Button
                                    key={m.value}
                                    variant="ghost"
                                    role="radio"
                                    aria-checked={mode === m.value}
                                    className={`ts-mode${mode === m.value ? ' is-on' : ''}`}
                                    onClick={() => handleModeChange(m.value)}
                                >
                                    <span className="ts-mode__title">
                                        <ModeIcon size={15} />
                                        {m.title}
                                    </span>
                                    <span className="ts-mode__desc">{m.desc}</span>
                                    <span className="ts-mode__eta">{m.eta}</span>
                                </Button>
                            );
                        })}
                    </div>

                    <div className="ts-grid">
                        {distros.map((d) => {
                            const disabled = mode === 'full' && !d.full;
                            const isSelected = selected.has(d.key);
                            const family = FAMILY_META[d.family];
                            return (
                                <Button
                                    key={d.key}
                                    variant="ghost"
                                    className={
                                        `ts-distro${isSelected ? ' is-selected' : ''}${disabled ? ' is-disabled' : ''}`
                                    }
                                    disabled={disabled}
                                    aria-pressed={isSelected}
                                    title={disabled ? `${d.label} only supports quick mode` : d.label}
                                    onClick={() => toggleDistro(d.key)}
                                >
                                    <span className="ts-distro__label">{d.label}</span>
                                    <span className="ts-distro__meta">
                                        {family && <Pill kind={family.kind} dot={false}>{family.label}</Pill>}
                                        <span className="ts-distro__hint">
                                            {disabled ? 'quick only' : (d.full ? 'quick + full' : 'quick')}
                                        </span>
                                    </span>
                                </Button>
                            );
                        })}
                    </div>

                    <div className="ts-launch">
                        <Button
                            onClick={handleStart}
                            disabled={selected.size === 0 || isRunning || starting || !dockerAvailable}
                        >
                            <Play size={14} />
                            {starting ? 'Starting…' : `Start ${mode} run${selected.size ? ` (${selected.size})` : ''}`}
                        </Button>
                        {isRunning && (
                            <span className="ts-launch__note">A run is already in progress.</span>
                        )}
                    </div>
                </CardContent>
            </Card>

            {/* ── Active run ──────────────────────────────── */}
            {activeRun && (
                <Card className="ts-active">
                    <CardHeader className="ts-active__head">
                        <CardTitle>Run #{activeRun.id}</CardTitle>
                        <Pill kind="gray" dot={false}>{activeRun.mode}</Pill>
                        <Pill kind={RUN_PILL[activeRun.status] || 'gray'}>{activeRun.status}</Pill>
                        {isRunning && (
                            <Button
                                variant="destructive"
                                size="sm"
                                onClick={handleCancel}
                                disabled={cancelling}
                            >
                                <Square size={13} />
                                {cancelling ? 'Cancelling…' : 'Cancel'}
                            </Button>
                        )}
                    </CardHeader>
                    <CardContent>
                        {activeRun.error && (
                            <div className="alert alert-danger">{activeRun.error}</div>
                        )}
                        <RunResults
                            run={activeRun}
                            distroMeta={distroMeta}
                            logs={logs}
                            openLogs={openLogs}
                            onToggleLog={toggleLog}
                        />
                    </CardContent>
                </Card>
            )}

            {/* ── History ─────────────────────────────────── */}
            <section className="ts-history">
                <h2 className="ts-section-title">Run history</h2>
                {runsLoading ? (
                    <EmptyState loading loadingVariant="table" title="Loading run history..." />
                ) : runs.length === 0 ? (
                    <EmptyState
                        icon={FlaskConical}
                        title="No runs yet"
                        description="Pick distros above and start your first sandbox run."
                    />
                ) : (
                    <div className="ts-history-card">
                        <table className="sk-dtable ts-table">
                            <thead>
                                <tr>
                                    <th>Run</th>
                                    <th>Mode</th>
                                    <th>Distros</th>
                                    <th>Result</th>
                                    <th>Started</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                {runs.map((run) => {
                                    const { passed, failed, total } = summarizeRun(run);
                                    const expanded = !!expandedRuns[run.id];
                                    return (
                                        <FragmentRow
                                            key={run.id}
                                            run={run}
                                            expanded={expanded}
                                            passed={passed}
                                            failed={failed}
                                            total={total}
                                            onToggle={() => toggleHistoryRun(run)}
                                            detail={expanded && (
                                                <RunResults
                                                    run={expandedRuns[run.id]}
                                                    distroMeta={distroMeta}
                                                    logs={logs}
                                                    openLogs={openLogs}
                                                    onToggleLog={toggleLog}
                                                />
                                            )}
                                        />
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </section>
        </div>
    );
};

// One history row (+ its expanded detail row) in the runs table.
function FragmentRow({ run, expanded, passed, failed, total, onToggle, detail }) {
    return (
        <>
            <tr className={`is-clickable${expanded ? ' is-expanded' : ''}`} onClick={onToggle}>
                <td>
                    <div className="sk-cell-name">
                        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        <span>#{run.id}</span>
                    </div>
                </td>
                <td><Pill kind="gray" dot={false}>{run.mode}</Pill></td>
                <td>{total}</td>
                <td>
                    <span className="ts-summary">
                        <span className="ts-summary__pass">{passed} passed</span>
                        {failed > 0 && <span className="ts-summary__fail">{failed} failed</span>}
                    </span>
                </td>
                <td>{timeAgo(run.created_at)}</td>
                <td><Pill kind={RUN_PILL[run.status] || 'gray'}>{run.status}</Pill></td>
            </tr>
            {expanded && (
                <tr className="ts-detail-row">
                    <td colSpan={6}>{detail}</td>
                </tr>
            )}
        </>
    );
}

export default TestSandbox;
