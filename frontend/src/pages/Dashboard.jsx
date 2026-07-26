import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    Check, ChevronDown, Grid2x2, History, Maximize2, Plus,
    RefreshCw, SlidersHorizontal, X,
} from 'lucide-react';
import api from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import { useMetrics } from '../hooks/useMetrics';
import useDashboardBoards from '../hooks/useDashboardBoards';
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover';
import { SegControl } from '@/components/ds';
import EmptyState from '../components/EmptyState';
import PluginSlot from '../components/PluginSlot';
import { DashGrid } from '../components/dashboard/grid/DashGrid';
import { WidgetLibrary } from '../components/dashboard/grid/WidgetLibrary';
import { WidgetEditor } from '../components/dashboard/grid/WidgetEditor';
import { WidgetFullscreen } from '../components/dashboard/grid/WidgetFullscreen';
import {
    compact, findFreeSpot, nextWidgetId, pushDown,
} from '../components/dashboard/grid/layout';
import { useWidgetTypes, getWidgetType } from '../components/dashboard/widgets/registry';
import { RANGES } from '../components/dashboard/widgets/metrics';

// Auto-refresh choices, in seconds. 0 means "don't".
const REFRESH_OPTIONS = [
    { label: 'Off', value: 0 },
    { label: '5s', value: 5 },
    { label: '10s', value: 10 },
    { label: '30s', value: 30 },
    { label: '1m', value: 60 },
];

function formatUptime(seconds) {
    if (!seconds) return { days: 0, hours: 0, minutes: 0 };
    return {
        days: Math.floor(seconds / 86400),
        hours: Math.floor((seconds % 86400) / 3600),
        minutes: Math.floor((seconds % 3600) / 60),
    };
}

const Dashboard = () => {
    const navigate = useNavigate();
    const { isAdmin } = useAuth();
    const toast = useToast();
    const widgetTypes = useWidgetTypes();

    const {
        boards, activeBoard, activeBoardId, setActiveBoardId,
        loading: boardsLoading, error: boardsError,
        setWidgets, saveActive, createBoard, renameBoard, removeBoard, resetActiveBoard,
        takeSnapshot, restoreSnapshot,
    } = useDashboardBoards();

    // ---- board editing UI state -------------------------------------------
    const [edit, setEdit] = useState(false);
    const [selectedId, setSelectedId] = useState(null);
    const [libraryOpen, setLibraryOpen] = useState(false);
    const [fullscreen, setFullscreen] = useState(null);
    const [renamingId, setRenamingId] = useState(null);
    const [tvMode, setTvMode] = useState(false);

    // ---- board-wide variables ---------------------------------------------
    const [range, setRange] = useState('1h');
    const [tick, setTick] = useState(0);
    const [refreshInterval, setRefreshInterval] = useState(() => {
        const saved = localStorage.getItem('dashboard_refresh_interval');
        return saved ? parseInt(saved, 10) : 10;
    });

    // ---- host identity strip ----------------------------------------------
    const { metrics: localMetrics, loading: metricsLoading, connected, refresh: refreshMetrics } = useMetrics(true);
    const [systemInfo, setSystemInfo] = useState(null);
    const [servers, setServers] = useState([]);
    const [selectedServer, setSelectedServer] = useState({ id: 'local', name: 'Local (this server)' });
    const [serverMenuOpen, setServerMenuOpen] = useState(false);
    const [remoteMetrics, setRemoteMetrics] = useState(null);
    const [remoteSystemInfo, setRemoteSystemInfo] = useState(null);
    const isRemote = selectedServer.id !== 'local';
    const metrics = isRemote ? remoteMetrics : localMetrics;

    // Uptime and clock tick locally between server samples so they don't freeze
    // between polls; the refs stop a repeated sample from resetting the drift.
    const [localUptime, setLocalUptime] = useState(null);
    const [localTime, setLocalTime] = useState(null);
    const lastServerUptime = useRef(null);
    const lastServerTime = useRef(null);

    const widgets = useMemo(() => activeBoard?.widgets || [], [activeBoard]);
    const selectedWidget = widgets.find((w) => w.i === selectedId) || null;
    const selectedType = getWidgetType(widgetTypes, selectedWidget?.type);

    const resources = useMemo(() => ([
        { id: 'local', label: 'Local (this server)', kind: 'panel host' },
        ...servers
            .filter((s) => s && s.id && s.id !== 'local')
            .map((s) => ({ id: s.id, label: s.name || s.id, kind: 'server' })),
    ]), [servers]);

    const ctx = useMemo(() => ({
        range,
        tick,
        serverVar: selectedServer.id,
        isAdmin,
        navigate,
        types: widgetTypes,
    }), [range, tick, selectedServer.id, isAdmin, navigate, widgetTypes]);

    // ---- data loading ------------------------------------------------------
    useEffect(() => {
        api.getAvailableServers()
            .then((data) => setServers(Array.isArray(data) ? data : []))
            .catch(() => setServers([]));
        api.getSystemInfo()
            .then(setSystemInfo)
            .catch(() => setSystemInfo(null));
    }, []);

    const fetchRemote = useCallback(async () => {
        if (!isRemote) return;
        try {
            const [m, info] = await Promise.all([
                api.getRemoteSystemMetrics(selectedServer.id),
                api.getRemoteSystemInfo(selectedServer.id).catch(() => null),
            ]);
            setRemoteMetrics(m);
            setRemoteSystemInfo(info);
        } catch {
            // The identity strip degrades to placeholders; widgets report their
            // own failures individually.
        }
    }, [isRemote, selectedServer.id]);

    useEffect(() => {
        if (!isRemote) {
            setRemoteMetrics(null);
            setRemoteSystemInfo(null);
            return undefined;
        }
        fetchRemote();
        const id = refreshInterval > 0 ? setInterval(fetchRemote, refreshInterval * 1000) : null;
        return () => { if (id) clearInterval(id); };
    }, [fetchRemote, isRemote, refreshInterval]);

    // Board-wide refresh pulse: every widget watches ctx.tick.
    useEffect(() => {
        if (!refreshInterval) return undefined;
        const id = setInterval(() => setTick((k) => k + 1), refreshInterval * 1000);
        return () => clearInterval(id);
    }, [refreshInterval]);

    // HTTP polling fallback for live metrics when the socket is down.
    useEffect(() => {
        if (!refreshInterval || connected || isRemote) return undefined;
        const id = setInterval(() => refreshMetrics(), refreshInterval * 1000);
        return () => clearInterval(id);
    }, [refreshInterval, connected, refreshMetrics, isRemote]);

    useEffect(() => {
        const uptime = metrics?.system?.uptime_seconds;
        const stamp = metrics?.time?.current_time_formatted;
        if (uptime && uptime !== lastServerUptime.current) {
            lastServerUptime.current = uptime;
            setLocalUptime(uptime);
        }
        if (stamp && stamp !== lastServerTime.current) {
            lastServerTime.current = stamp;
            const parsed = new Date(stamp);
            if (!Number.isNaN(parsed.getTime())) setLocalTime(parsed);
        }
    }, [metrics?.system?.uptime_seconds, metrics?.time?.current_time_formatted]);

    const hasUptime = localUptime !== null;
    const hasClock = localTime !== null;
    useEffect(() => {
        if (!hasUptime && !hasClock) return undefined;
        const id = setInterval(() => {
            if (hasUptime) setLocalUptime((prev) => prev + 1);
            if (hasClock) setLocalTime((prev) => new Date(prev.getTime() + 1000));
        }, 1000);
        return () => clearInterval(id);
    }, [hasUptime, hasClock]);

    // ---- widget operations -------------------------------------------------
    const addWidget = useCallback((type) => {
        const spot = findFreeSpot(widgets, type.w, type.h);
        const widget = {
            i: nextWidgetId(widgets),
            type: type.id,
            ...spot,
            w: type.w,
            h: type.h,
            cfg: JSON.parse(JSON.stringify(type.defaultCfg || {})),
        };
        setWidgets((list) => compact([...list, widget]));
        setSelectedId(widget.i);
        setLibraryOpen(false);
        if (!edit) setEdit(true);
    }, [widgets, setWidgets, edit]);

    const duplicateWidget = useCallback((widget) => {
        const spot = findFreeSpot(widgets, widget.w, widget.h);
        const copy = { ...JSON.parse(JSON.stringify(widget)), i: nextWidgetId(widgets), ...spot };
        setWidgets((list) => compact([...list, copy]));
        setSelectedId(copy.i);
    }, [widgets, setWidgets]);

    const removeWidget = useCallback((id) => {
        setWidgets((list) => compact(list.filter((w) => w.i !== id)));
        setSelectedId(null);
    }, [setWidgets]);

    // The inspector can change w/h, which may overlap neighbours — re-settle.
    const updateWidget = useCallback((next) => {
        setWidgets((list) => pushDown(list.map((w) => (w.i === next.i ? next : w)), next));
    }, [setWidgets]);

    const onWidgetMenu = useCallback((action, widget) => {
        if (action === 'config') { setEdit(true); setSelectedId(widget.i); }
        else if (action === 'dup') duplicateWidget(widget);
        else if (action === 'del') removeWidget(widget.i);
        else if (action === 'full') setFullscreen(widget);
    }, [duplicateWidget, removeWidget]);

    // Escape backs out of TV mode, then out of a selection. Delete removes the
    // selected widget, but only while editing and never while typing into the
    // inspector — otherwise backspacing a title would delete the widget.
    useEffect(() => {
        const onKeyDown = (event) => {
            if (event.key === 'Escape') {
                if (tvMode) setTvMode(false);
                else if (selectedId) setSelectedId(null);
                return;
            }
            if (!edit || !selectedId) return;
            if (event.key !== 'Delete' && event.key !== 'Backspace') return;
            if (/input|textarea|select/i.test(document.activeElement?.tagName || '')) return;
            event.preventDefault();
            removeWidget(selectedId);
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [edit, selectedId, tvMode, removeWidget]);

    // ---- edit session ------------------------------------------------------
    const startEdit = () => { takeSnapshot(); setEdit(true); };

    const discardEdit = () => {
        restoreSnapshot();
        setEdit(false);
        setSelectedId(null);
    };

    const finishEdit = async () => {
        try {
            await saveActive();
            setEdit(false);
            setSelectedId(null);
            toast.success('Dashboard saved', {
                description: `${widgets.length} widget${widgets.length === 1 ? '' : 's'} · ${activeBoard?.name}`,
            });
        } catch {
            // useDashboardBoards keeps the edited layout on screen and surfaces
            // the reason; staying in edit mode means the work isn't lost.
            toast.error('Could not save', { description: 'Your layout is still here — try again.' });
        }
    };

    const handleReset = async () => {
        try {
            await resetActiveBoard();
            toast.info('Reset to the shipped layout', { description: activeBoard?.name });
        } catch {
            toast.error('Could not reset', { description: 'This board has no shipped default.' });
        }
    };

    const handleServerChange = (serverId) => {
        const server = servers.find((s) => s.id === serverId) || { id: 'local', name: 'Local (this server)' };
        setSelectedServer(server);
        lastServerUptime.current = null;
        lastServerTime.current = null;
        setLocalUptime(null);
        setLocalTime(null);
    };

    const handleRefreshIntervalChange = (value) => {
        setRefreshInterval(value);
        localStorage.setItem('dashboard_refresh_interval', String(value));
    };

    // ---- derived display ---------------------------------------------------
    const activeSysInfo = isRemote ? remoteSystemInfo : systemInfo;
    const hostname = metrics?.system?.hostname || activeSysInfo?.hostname || 'server';
    const kernelVersion = metrics?.system?.kernel || activeSysInfo?.kernel || '-';
    const ipAddress = metrics?.system?.ip_address || activeSysInfo?.ip_address || '-';
    const uptime = formatUptime(localUptime ?? metrics?.system?.uptime_seconds);
    const isConnected = isRemote ? !!remoteMetrics : !!localMetrics;
    const displayTime = localTime
        ? localTime.toLocaleTimeString('en-GB', { hour12: false })
        : metrics?.time?.current_time_formatted?.split(' ')[1] || '--:--:--';

    if (boardsLoading && metricsLoading) {
        return <EmptyState loading loadingVariant="chart" title="Loading dashboard..." />;
    }

    const grid = (
        <DashGrid
            widgets={widgets}
            edit={edit}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onChange={(next) => setWidgets(next)}
            ctx={ctx}
            onWidgetMenu={onWidgetMenu}
        />
    );

    // TV mode: the board, a clock and nothing else — for a wall display.
    if (tvMode) {
        return (
            <div className="skw-tv">
                <div className="skw-tv__bar">
                    <span className="skw-tv__name">{activeBoard?.name}</span>
                    <span className={`conn-status conn-status--${isConnected ? 'live' : 'down'}`} role="status">
                        <span className="conn-status__dot" aria-hidden="true"></span>
                        {isConnected ? 'Live' : 'Reconnecting'}
                    </span>
                    <span className="skw-tv__meta mono">
                        {selectedServer.name} · {range} · refresh {refreshInterval ? `${refreshInterval}s` : 'off'}
                    </span>
                    <span className="skw-tv__clock mono">{displayTime}</span>
                    <button type="button" className="btn btn-outline btn-sm" onClick={() => setTvMode(false)}>
                        <X size={14} /> Exit
                    </button>
                </div>
                <div className="skw-tv__body">{grid}</div>
            </div>
        );
    }

    // The widget editor is a drawer over the board now, not a docked panel, so
    // the page no longer reserves a right-hand gutter for it.
    return (
        <div className="page-container dashboard-page">
            {/* Host identity — which machine the board's $server variable points at */}
            <div className="top-bar">
                <div className="server-identity">
                    {/* A chevron that opens a menu of one is just noise — most
                        installs manage a single host, so show the name plainly
                        until there is actually something to switch to. */}
                    {servers.length < 2 ? (
                        <span className="srv-switch srv-switch--static">
                            <span className="srv-switch__name">{hostname}</span>
                        </span>
                    ) : (
                    <Popover open={serverMenuOpen} onOpenChange={setServerMenuOpen}>
                        <PopoverTrigger asChild>
                            <button
                                type="button"
                                className={`srv-switch${serverMenuOpen ? ' srv-switch--open' : ''}`}
                                aria-label="Switch server"
                            >
                                <span className="srv-switch__name">{hostname}</span>
                                <ChevronDown size={18} className="srv-switch__chev" aria-hidden="true" />
                            </button>
                        </PopoverTrigger>
                        <PopoverContent align="start" sideOffset={7} className="env-menu">
                            <div className="env-menu__head">Connected servers · {servers.length}</div>
                            {servers.map((server) => {
                                const online = server.status === 'online';
                                return (
                                    <button
                                        type="button"
                                        key={server.id}
                                        className="env-opt"
                                        onClick={() => { handleServerChange(server.id); setServerMenuOpen(false); }}
                                    >
                                        <span
                                            className={`env-opt__dot env-opt__dot--${online ? 'online' : 'offline'}`}
                                            aria-hidden="true"
                                        ></span>
                                        <span className="env-opt__body">
                                            <span className="env-opt__name">{server.name}</span>
                                            <span className="env-opt__meta">
                                                {server.group_name || (server.is_local ? 'local' : server.id)}
                                                {' · '}
                                                {online ? 'online' : 'offline'}
                                            </span>
                                        </span>
                                        {server.id === selectedServer.id && (
                                            <span className="env-opt__check" aria-hidden="true"><Check size={15} /></span>
                                        )}
                                    </button>
                                );
                            })}
                        </PopoverContent>
                    </Popover>
                    )}
                    <div className="server-details">
                        <span className={`conn-status conn-status--${isConnected ? 'live' : 'down'}`} role="status">
                            <span className="conn-status__dot" aria-hidden="true"></span>
                            {isConnected ? 'Live' : 'Reconnecting'}
                        </span>
                        <span className="detail-separator">·</span>
                        <span>IP: {ipAddress}</span>
                        <span className="detail-separator">·</span>
                        <span>KERNEL: {kernelVersion}</span>
                        <span className="detail-separator">·</span>
                        <span>
                            UPTIME: {uptime.days}d {String(uptime.hours).padStart(2, '0')}h{' '}
                            {String(uptime.minutes).padStart(2, '0')}m
                        </span>
                    </div>
                </div>
                <div className="top-bar-right">
                    <div className="clock-widget">
                        <span className="clock-time">{displayTime}</span>
                        <span className="clock-zone">{metrics?.time?.timezone_id || 'UTC'}</span>
                    </div>
                </div>
            </div>

            {/* Extension slot: widgets contributed to the top of the dashboard */}
            <PluginSlot name="dashboard.top" />

            {/* Board tabs + board-wide controls */}
            <div className="skw-bar">
                <div className="skw-tabs">
                    {boards.map((board) => (
                        <div
                            key={board.id}
                            className={`skw-tab${board.id === activeBoardId ? ' is-on' : ''}`}
                            onClick={() => { setActiveBoardId(board.id); setSelectedId(null); }}
                            onDoubleClick={() => edit && setRenamingId(board.id)}
                            role="button"
                            tabIndex={0}
                            onKeyDown={(e) => { if (e.key === 'Enter') { setActiveBoardId(board.id); setSelectedId(null); } }}
                        >
                            <Grid2x2 size={14} aria-hidden="true" />
                            {renamingId === board.id ? (
                                <input
                                    className="skw-rename"
                                    autoFocus
                                    defaultValue={board.name}
                                    onBlur={(e) => {
                                        renameBoard(board.id, e.target.value.trim() || board.name);
                                        setRenamingId(null);
                                    }}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter') e.target.blur();
                                        if (e.key === 'Escape') setRenamingId(null);
                                    }}
                                />
                            ) : (
                                <span>{board.name}</span>
                            )}
                            <span className="skw-tab__count mono">{(board.widgets || []).length}</span>
                            {edit && boards.length > 1 && board.id === activeBoardId && (
                                <button
                                    type="button"
                                    className="skw-iconbtn skw-iconbtn--bare"
                                    aria-label={`Delete ${board.name}`}
                                    onClick={(e) => { e.stopPropagation(); removeBoard(board.id); }}
                                >
                                    <X size={12} />
                                </button>
                            )}
                        </div>
                    ))}
                    <button
                        type="button"
                        className="skw-tab skw-tab--add"
                        onClick={() => createBoard().then((b) => setRenamingId(b.id))}
                        aria-label="New dashboard"
                        title="New dashboard"
                    >
                        <Plus size={14} />
                    </button>
                </div>

                <div className="skw-bar__ctl">
                    <SegControl
                        options={RANGES.map(([value, label]) => ({ value, label }))}
                        value={range}
                        onChange={setRange}
                        aria-label="Time range"
                    />
                    <select
                        value={refreshInterval}
                        onChange={(e) => handleRefreshIntervalChange(parseInt(e.target.value, 10))}
                        className="refresh-select"
                        title="Auto-refresh interval"
                        aria-label="Auto-refresh interval"
                    >
                        {REFRESH_OPTIONS.map((opt) => (
                            <option key={opt.value} value={opt.value}>↻ {opt.label}</option>
                        ))}
                    </select>
                    <button
                        type="button"
                        className="skw-iconbtn"
                        title="Refresh now"
                        aria-label="Refresh now"
                        onClick={() => { setTick((k) => k + 1); if (isRemote) fetchRemote(); else refreshMetrics(); }}
                    >
                        <RefreshCw size={15} />
                    </button>
                    <button
                        type="button"
                        className="skw-iconbtn"
                        title="TV mode"
                        aria-label="TV mode"
                        onClick={() => setTvMode(true)}
                    >
                        <Maximize2 size={15} />
                    </button>
                    {edit ? (
                        <>
                            <button type="button" className="btn btn-outline btn-sm" onClick={() => setLibraryOpen(true)}>
                                <Plus size={14} /> Add widget
                            </button>
                            <button
                                type="button"
                                className="btn btn-sm"
                                onClick={handleReset}
                                title="Restore the shipped layout"
                                aria-label="Restore the shipped layout"
                            >
                                <History size={14} />
                            </button>
                            <button type="button" className="btn btn-sm" onClick={discardEdit}>Discard</button>
                            <button type="button" className="btn btn-primary btn-sm" onClick={finishEdit}>
                                <Check size={14} /> Done
                            </button>
                        </>
                    ) : (
                        <button type="button" className="btn btn-outline btn-sm" onClick={startEdit}>
                            <SlidersHorizontal size={14} /> Edit
                        </button>
                    )}
                </div>
            </div>

            {boardsError && <div className="skw-hint skw-hint--error">{boardsError}</div>}

            {edit && (
                <div className="skw-hint mono">
                    <Grid2x2 size={13} aria-hidden="true" /> Drag headers to move · drag the corner to resize ·
                    click a widget to configure it{selectedId ? ' · Delete removes it' : ''}
                </div>
            )}

            {widgets.length === 0 ? (
                <div className="skw-empty-board">
                    <div className="skw-empty-board__title">Build “{activeBoard?.name || 'this dashboard'}”</div>
                    <div className="skw-empty-board__desc">
                        This board has no widgets yet. Add one to get started, or restore the layout it shipped with.
                    </div>
                    <div className="skw-empty-board__acts">
                        <button
                            type="button"
                            className="btn btn-primary btn-sm"
                            onClick={() => { setEdit(true); setLibraryOpen(true); }}
                        >
                            <Plus size={14} /> Add a widget
                        </button>
                        {activeBoard?.slug && (
                            <button type="button" className="btn btn-outline btn-sm" onClick={handleReset}>
                                <History size={14} /> Restore default layout
                            </button>
                        )}
                    </div>
                </div>
            ) : grid}

            {libraryOpen && (
                <WidgetLibrary
                    types={widgetTypes}
                    onAdd={addWidget}
                    onClose={() => setLibraryOpen(false)}
                />
            )}
            {edit && selectedWidget && (
                <WidgetEditor
                    widget={selectedWidget}
                    type={selectedType}
                    resources={resources}
                    ctx={ctx}
                    onChange={updateWidget}
                    onClose={() => setSelectedId(null)}
                    onDuplicate={() => duplicateWidget(selectedWidget)}
                    onRemove={() => removeWidget(selectedWidget.i)}
                />
            )}
            {fullscreen && (
                <WidgetFullscreen
                    widget={fullscreen}
                    type={getWidgetType(widgetTypes, fullscreen.type)}
                    ctx={ctx}
                    onClose={() => setFullscreen(null)}
                />
            )}
        </div>
    );
};

export default Dashboard;
