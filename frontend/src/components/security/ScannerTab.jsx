import { useState, useEffect, useRef } from 'react';
import { statusKind } from '@/components/ds/status';
import api from '../../services/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { DataTable, DataTableFooter, Pill } from '@/components/ds';
import {
    useTableChrome, GridViewPicker, GridChips, GridFilterButton,
    GridToolsMenu, GridFilterDrawer, applyFilters,
} from '@/components/ds/grid';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { Zap, Radar, FolderSearch, Download, Box, FileCode2, Trash2, Search } from 'lucide-react';
import EmptyState from '@/components/EmptyState';
import { useConfirm } from '@/hooks/useConfirm';
import { usePolling } from '@/hooks/usePolling';
import { useTranslation } from 'react-i18next';
import { useOperations } from '@/contexts/OperationsContext';

// Scan status cadence, and the faster cadence while a scan job runs.
const SCAN_STATUS_POLL_MS = 5000;
const SCAN_JOB_POLL_MS = 3000;


// Urgency order for the Severity column. The severity strings sort
// alphabetically — critical, high, low, medium — which files "low" above
// "medium" and puts the wrong finding on top of a triage list.
const SEVERITY_RANK = { critical: 0, high: 1, medium: 2, low: 3 };

const NO_RULES = { match: 'all', rules: [] };

// Built-in views for the findings table. Every rule matches a column's `value`
// accessor, which for Severity and Source is the raw scanner word the cell
// renders — never the rank the table sorts by.
const FINDING_VIEWS = [
    {
        // The triage default: worst first. Sort only, and the empty rule set is
        // spelled out so switching here clears the previous view's filters.
        name: 'Worst first',
        state: {
            sorts: [{ key: 'severity', direction: 'asc' }],
            hiddenKeys: [],
            groupBy: null,
            columnFilters: NO_RULES,
        },
    },
    {
        // What you act on before closing the tab. 'medium' is deliberately out:
        // the curated rules emit it as their default, so it is the bucket an
        // unclassified match lands in rather than a judgement about the file.
        name: 'Critical & high',
        state: {
            sorts: [{ key: 'severity', direction: 'asc' }],
            hiddenKeys: [],
            groupBy: null,
            columnFilters: {
                match: 'all',
                rules: [{ id: 'fs1', field: 'severity', op: 'any', value: ['critical', 'high'] }],
            },
        },
    },
    {
        // The curated web-shell pass on its own — a backdoor in a docroot, not
        // a known-malware signature. Grouped by file through the sort, because
        // one shell usually trips several rules and you quarantine the FILE.
        name: 'Web-shell hits',
        state: {
            sorts: [{ key: 'file', direction: 'asc' }],
            hiddenKeys: [],
            groupBy: null,
            columnFilters: {
                match: 'all',
                rules: [{ id: 'fw1', field: 'source', op: 'any', value: ['yara'] }],
            },
        },
    },
];

// Built-in views for the scan-history table.
const HISTORY_VIEWS = [
    {
        name: 'Newest first',
        state: {
            sorts: [{ key: 'date', direction: 'desc' }],
            hiddenKeys: [],
            groupBy: null,
            columnFilters: NO_RULES,
        },
    },
    {
        // Scans that actually found something — the audit trail you re-read
        // after an incident. A scan with no infected list reads 0 threats, so
        // `over 0` can only ever be a real hit.
        name: 'Threats found',
        state: {
            sorts: [{ key: 'date', direction: 'desc' }],
            hiddenKeys: [],
            groupBy: null,
            columnFilters: {
                match: 'all',
                rules: [{ id: 'hs1', field: 'threats', op: 'gt', value: 0 }],
            },
        },
    },
    {
        // A scan that never finished proves nothing about the directory it was
        // pointed at — 'completed with 0 threats' and 'timed out' look equally
        // green from a distance, and only one of them is an answer.
        name: 'Did not finish',
        state: {
            sorts: [{ key: 'date', direction: 'desc' }],
            hiddenKeys: [],
            groupBy: null,
            columnFilters: {
                match: 'all',
                rules: [{
                    id: 'hf1',
                    field: 'status',
                    op: 'any',
                    value: ['error', 'timeout', 'cancelled'],
                }],
            },
        },
    },
];

const ScannerTab = () => {
    const { t } = useTranslation();
    const { confirm } = useConfirm();
    const { openRun } = useOperations();
    const [scanStatus, setScanStatus] = useState({ status: 'idle' });
    const [scanPath, setScanPath] = useState('/var/www');
    const [scanning, setScanning] = useState(false);
    const [updating, setUpdating] = useState(false);
    const [history, setHistory] = useState([]);
    const [message, setMessage] = useState(null);

    // App scan (job-backed)
    const [apps, setApps] = useState([]);
    const [selectedApp, setSelectedApp] = useState('');
    const [scanJob, setScanJob] = useState(null); // { id, status, result }
    const [scanJobId, setScanJobId] = useState(null);

    // Findings (YARA + ClamAV) from the last completed job/scan
    const [findings, setFindings] = useState([]);
    const [quarantining, setQuarantining] = useState(null);
    // Per-table sort + column visibility (persisted, mirrored by header menus)
    const findingsSorts = useTableSort({ storageKey: 'serverkit-table-scanner-findings-sort' });
    const findingsCols = useColumnVisibility({ storageKey: 'serverkit-table-scanner-findings-cols' });
    const historySorts = useTableSort({ storageKey: 'serverkit-table-scanner-history-sort' });
    const historyCols = useColumnVisibility({ storageKey: 'serverkit-table-scanner-history-cols' });

    // YARA rules manager
    const [rules, setRules] = useState(null);
    const [showRules, setShowRules] = useState(false);
    const ruleFileRef = useRef(null);

    useEffect(() => {
        loadScanStatus();
        loadHistory();
        loadApps();
    }, []);

    usePolling(loadScanStatus, SCAN_STATUS_POLL_MS, { immediate: false });

    async function loadScanStatus() {
        try {
            const data = await api.getScanStatus();
            setScanStatus(data);
            if (data.status === 'completed' && Array.isArray(data.findings)) {
                setFindings(data.findings);
            }
        } catch (err) {
            console.error('Failed to load scan status:', err);
        }
    }

    async function loadHistory() {
        try {
            const data = await api.getScanHistory(20);
            setHistory(data.scans || []);
        } catch (err) {
            console.error('Failed to load scan history:', err);
        }
    }

    async function loadApps() {
        try {
            const data = await api.getApps();
            setApps(data.apps || []);
        } catch (err) {
            console.error('Failed to load apps:', err);
        }
    }

    async function loadRules() {
        try {
            const data = await api.getYaraRules();
            setRules(data);
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        }
    }

    // The job id IS the "are we polling" state; the hook owns the schedule,
    // so this only has to say which job to watch.
    function pollJob(jobId) {
        setScanJobId(jobId);
    }

    usePolling(async () => {
        try {
            const response = await api.getJob(scanJobId);
            const job = response.job || response;
            setScanJob(job);
            if (!['succeeded', 'failed', 'cancelled'].includes(job.status)) return;
            setScanJobId(null);
            if (job.status === 'succeeded' && job.result?.findings) {
                setFindings(job.result.findings);
                const n = job.result.findings.length;
                setMessage({
                    type: n > 0 ? 'error' : 'success',
                    text: n > 0
                        ? `Scan finished: ${n} finding(s) — review below`
                        : 'Scan finished: no threats found',
                });
            } else if (job.status === 'failed') {
                setMessage({ type: 'error', text: job.error_message || 'Scan job failed' });
            }
            loadScanStatus();
            loadHistory();
        } catch (err) {
            console.error('Failed to poll scan job:', err);
        }
    }, SCAN_JOB_POLL_MS, { enabled: Boolean(scanJobId), immediate: false });

    async function handleScanApp() {
        if (!selectedApp) return;
        setScanning(true);
        setMessage(null);
        try {
            const result = await api.scanApp(selectedApp);
            setScanJob({ id: result.job_id, status: 'pending' });
            openRun('job', result.job_id);
            setMessage({ type: 'success', text: `Scan queued for ${result.path || 'app docroot'}` });
            pollJob(result.job_id);
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setScanning(false);
        }
    }

    async function handleStartScan(type) {
        setScanning(true);
        setMessage(null);
        try {
            let result;
            if (type === 'quick') {
                result = await api.runQuickScan();
            } else if (type === 'full') {
                result = await api.runFullScan();
            } else {
                result = await api.scanDirectory(scanPath);
            }
            setMessage({ type: 'success', text: result.message });
            loadScanStatus();
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setScanning(false);
        }
    }

    async function handleUpdateDefinitions() {
        setUpdating(true);
        setMessage(null);
        try {
            const result = await api.updateVirusDefinitions();
            setMessage({ type: result.success ? 'success' : 'error', text: result.message || result.error });
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setUpdating(false);
        }
    }

    async function handleCancelScan() {
        try {
            await api.cancelScan();
            loadScanStatus();
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        }
    }

    async function handleQuarantine(finding) {
        setQuarantining(finding.file);
        try {
            await api.quarantineFile(finding.file);
            setFindings((prev) => prev.filter((f) => f.file !== finding.file));
            setMessage({ type: 'success', text: `Quarantined ${finding.file}` });
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setQuarantining(null);
        }
    }

    async function handleToggleRules() {
        const next = !showRules;
        setShowRules(next);
        if (next && !rules) loadRules();
    }

    async function handleRuleFileChosen(e) {
        const file = e.target.files?.[0];
        e.target.value = '';
        if (!file) return;
        if (!file.name.endsWith('.yar')) {
            setMessage({ type: 'error', text: 'Only .yar rule files are accepted' });
            return;
        }
        if (file.size > 64 * 1024) {
            setMessage({ type: 'error', text: 'Rule file exceeds the 64 KB limit' });
            return;
        }
        try {
            const content = await file.text();
            await api.uploadYaraRule(file.name, content);
            setMessage({ type: 'success', text: `Rule file ${file.name} uploaded` });
            loadRules();
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        }
    }

    async function handleDeleteRule(name) {
        if (!await confirm({
            title: t('app.scannerTab.deleteScannerRule', 'Delete scanner rule'),
            message: t('app.scannerTab.deleteCustomRuleFile', 'Delete custom rule file {{name}}?', { name: name }),
            confirmText: t('app.scannerTab.deleteRule', 'Delete rule'),
        })) return;
        try {
            await api.deleteYaraRule(name);
            loadRules();
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        }
    }

    const isScanning = scanStatus.status === 'running';
    const jobRunning = scanJob && ['pending', 'running'].includes(scanJob.status);

    // Cell markup/classNames identical to the hand-rolled tables they replace.
    const findingColumns = [
        {
            key: 'rule',
            headerKey: 'app.scannerTab.rule', header: 'Rule',
            sortable: true,
            hideable: false,
            type: 'text',
            value: (f) => f.rule || '',
            sortValue: (f) => f.rule || '',
            cellClassName: 'sk-cell-mono',
            render: (f) => <span title={f.description}>{f.rule}</span>,
        },
        {
            key: 'severity',
            headerKey: 'app.scannerTab.severity', header: 'Severity',
            sortable: true,
            type: 'enum',
            // Both accessors spelled out: `value` is the word a rule matches,
            // `sortValue` is the urgency rank the table orders by. A numeric
            // sortValue on its own would type the column `num`, and every
            // severity preset would then match exactly zero rows.
            value: (f) => f.severity || 'unknown',
            sortValue: (f) => SEVERITY_RANK[f.severity] ?? 9,
            enumOrder: ['critical', 'high', 'medium', 'low'],
            render: (f) => (
                <span className={`sec-state sec-state--${statusKind(f.severity)}`}>
                    {f.severity}
                </span>
            ),
        },
        {
            key: 'file',
            headerKey: 'app.scannerTab.file', header: 'File',
            sortable: true,
            type: 'text',
            value: (f) => f.file || '',
            sortValue: (f) => f.file || '',
            cellClassName: 'sk-cell-mono sec-path sec-path--red',
            render: (f) => <span title={f.file}>{f.file}</span>,
        },
        {
            key: 'match',
            headerKey: 'app.scannerTab.match', header: 'Match',
            // The row field is `matched`, not `match`, so without an accessor
            // the column has nothing behind it: no filter, and an export column
            // of empty strings.
            type: 'text',
            value: (f) => f.matched || '',
            cellClassName: 'sk-cell-mono scan-snippet',
            render: (f) => f.matched || '—',
        },
        {
            key: 'source',
            headerKey: 'app.scannerTab.source', header: 'Source',
            sortable: true,
            type: 'enum',
            value: (f) => f.source || 'unknown',
            sortValue: (f) => f.source || '',
            enumOrder: ['yara', 'clamav'],
            render: (f) => <span className="sec-state sec-state--gray">{f.source}</span>,
        },
        {
            key: 'actions',
            header: '',
            sortable: false,
            hideable: false,
            cellClassName: 'sec-rowend',
            render: (f) => (
                <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => handleQuarantine(f)}
                    disabled={quarantining === f.file}
                >
                    {quarantining === f.file ? 'Moving…' : 'Quarantine'}
                </Button>
            ),
        },
    ];

    const historyColumns = [
        {
            key: 'date',
            headerKey: 'app.scannerTab.date', header: 'Date',
            sortable: true,
            hideable: false,
            // Declared, not inferred: the sorter wants epoch ms, and letting
            // that number type the column would offer "is under 1754…" instead
            // of a date picker — and make any date rule match nothing.
            type: 'date',
            value: (scan) => scan.started_at || null,
            sortValue: (scan) => {
                const t = new Date(scan.started_at).getTime();
                return Number.isNaN(t) ? null : t;
            },
            cellClassName: 'sk-cell-mono sec-faint',
            render: (scan) => new Date(scan.started_at).toLocaleString(),
        },
        {
            key: 'directory',
            headerKey: 'app.scannerTab.directory', header: 'Directory',
            sortable: true,
            sortValue: (scan) => scan.directory || '',
            cellClassName: 'sk-cell-mono sec-path',
            render: (scan) => scan.directory,
        },
        {
            key: 'status',
            headerKey: 'app.scannerTab.status', header: 'Status',
            sortable: true,
            type: 'enum',
            value: (scan) => scan.status || 'unknown',
            sortValue: (scan) => scan.status || '',
            enumOrder: ['completed', 'running', 'error', 'timeout', 'cancelled'],
            render: (scan) => (
                <Pill kind={scan.status === 'completed' ? 'green' : scan.status === 'error' ? 'red' : 'amber'}>
                    {scan.status}
                </Pill>
            ),
        },
        {
            key: 'threats',
            headerKey: 'app.scannerTab.threats', header: 'Threats',
            sortable: true,
            type: 'num',
            // A scan with no infected list reads 0 rather than blank, so the
            // "over 0" preset can only ever be a real hit — a scan that failed
            // before it wrote a list can never look like a clean one.
            value: (scan) => scan.infected_files?.length ?? 0,
            sortValue: (scan) => scan.infected_files?.length ?? 0,
            render: (scan) => (
                scan.infected_files?.length > 0 ? (
                    <span className="sec-state sec-state--red">{scan.infected_files.length} found</span>
                ) : (
                    <span className="sec-state sec-state--green">clean</span>
                )
            ),
        },
    ];

    // Two tables on one route, so two chrome instances — each with its own view
    // bucket AND its own `urlScope`. The link params (`view`, `sort`, `hide`,
    // `f`…) are global names: unscoped, the findings table's sort would arrive
    // as the history table's and each would overwrite the other's ?view=.
    const findingsChrome = useTableChrome({
        columns: findingColumns,
        rows: findings,
        viewPageKey: 'security-scanner-findings',
        urlScope: 'findings',
        builtinViews: FINDING_VIEWS,
        noun: 'findings',
        sorts: findingsSorts.sorts,
        setSorts: findingsSorts.setSorts,
        hiddenKeys: findingsCols.hiddenKeys,
        setHiddenKeys: findingsCols.setHiddenKeys,
    });
    const historyChrome = useTableChrome({
        columns: historyColumns,
        rows: history,
        viewPageKey: 'security-scan-history',
        urlScope: 'history',
        builtinViews: HISTORY_VIEWS,
        noun: 'scans',
        sorts: historySorts.sorts,
        setSorts: historySorts.setSorts,
        hiddenKeys: historyCols.hiddenKeys,
        setHiddenKeys: historyCols.setHiddenKeys,
    });

    // The tables filter internally, so mirror the rules here for the footers —
    // a count reading "12 findings" under 3 filtered rows is the table lying
    // about what you are looking at.
    const shownFindings = applyFilters(findings, findingsChrome.cfg.filters, findingsChrome.columns);
    const shownHistory = applyFilters(history, historyChrome.cfg.filters, historyChrome.columns);

    return (
        <div className="scanner-tab">
            {message && (
                <div className={`alert alert-${message.type === 'success' ? 'success' : 'danger'}`}>
                    {message.text}
                </div>
            )}

            <div className="scan-options">
                <div className="scan-card scan-card--quick" onClick={() => !isScanning && !scanning && handleStartScan('quick')}>
                    <div className="scan-card-icon">
                        <Zap size={20} />
                    </div>
                    <h4>{t('app.scannerTab.quickScan', 'Quick Scan')}</h4>
                    <span className="scan-desc">{t('app.scannerTab.scanCommonWebDirectories', 'Scan common web directories')}</span>
                    <Button
                        variant="default"
                        size="sm"
                        onClick={(e) => { e.stopPropagation(); handleStartScan('quick'); }}
                        disabled={isScanning || scanning}
                    >
                        {t('app.scannerTab.startScan', 'Start Scan')}
                    </Button>
                </div>

                <div className="scan-card scan-card--full" onClick={() => !isScanning && !scanning && handleStartScan('full')}>
                    <div className="scan-card-icon">
                        <Radar size={20} />
                    </div>
                    <h4>{t('app.scannerTab.fullScan', 'Full Scan')}</h4>
                    <span className="scan-desc">{t('app.scannerTab.scanEntireSystemSlow', 'Scan entire system (slow)')}</span>
                    <Button
                        variant="default"
                        size="sm"
                        onClick={(e) => { e.stopPropagation(); handleStartScan('full'); }}
                        disabled={isScanning || scanning}
                    >
                        {t('app.scannerTab.startScan2', 'Start Scan')}
                    </Button>
                </div>

                <div className="scan-card scan-card--custom">
                    <div className="scan-card-icon">
                        <FolderSearch size={20} />
                    </div>
                    <h4>{t('app.scannerTab.customPath', 'Custom Path')}</h4>
                    <span className="scan-desc">{t('app.scannerTab.scanASpecificDirectory', 'Scan a specific directory')}</span>
                    <div className="scan-custom-input">
                        <Input
                            type="text"
                            value={scanPath}
                            onChange={(e) => setScanPath(e.target.value)}
                            placeholder="/path/to/scan"
                            disabled={isScanning}
                            onClick={(e) => e.stopPropagation()}
                        />
                        <Button
                            variant="default"
                            size="sm"
                            onClick={() => handleStartScan('custom')}
                            disabled={isScanning || scanning || !scanPath}
                        >
                            {t('app.scannerTab.scan', 'Scan')}
                        </Button>
                    </div>
                </div>

                <div className="scan-card scan-card--app">
                    <div className="scan-card-icon">
                        <Box size={20} />
                    </div>
                    <h4>{t('app.scannerTab.scanAnApp', 'Scan an App')}</h4>
                    <span className="scan-desc">{t('app.scannerTab.webShellMalwareScanOfA', 'Web-shell + malware scan of a docroot')}</span>
                    <div className="scan-custom-input">
                        <select
                            className="scan-app-select"
                            value={selectedApp}
                            onChange={(e) => setSelectedApp(e.target.value)}
                            disabled={jobRunning}
                        >
                            <option value="">{t('app.scannerTab.selectAnApp', 'Select an app…')}</option>
                            {apps.map((a) => (
                                <option key={a.id} value={a.id}>{a.name}</option>
                            ))}
                        </select>
                        <Button
                            variant="default"
                            size="sm"
                            onClick={handleScanApp}
                            disabled={!selectedApp || scanning || jobRunning}
                        >
                            {jobRunning ? 'Running…' : 'Scan'}
                        </Button>
                    </div>
                </div>
            </div>

            <div className="scan-toolbar">
                <Button variant="outline" size="sm" onClick={handleToggleRules}>
                    <FileCode2 size={14} />
                    {t('app.scannerTab.webShellRules', 'Web-shell Rules')}
                </Button>
                <Button variant="outline" size="sm" onClick={handleUpdateDefinitions} disabled={updating}>
                    <Download size={14} />
                    {updating ? 'Updating...' : 'Update Definitions'}
                </Button>
            </div>

            {showRules && (
                <div className="card sec-flush yara-rules-card">
                    <div className="card-header">
                        <h3>{t('app.scannerTab.webShellDetectionRules', 'Web-shell Detection Rules')}{rules && <span className="sec-count"> · {rules.builtin_count} builtin</span>}</h3>
                        <div className="card-actions">
                            <input
                                ref={ruleFileRef}
                                type="file"
                                accept=".yar"
                                className="yara-file-input"
                                onChange={handleRuleFileChosen}
                            />
                            <Button variant="outline" size="sm" onClick={() => ruleFileRef.current?.click()}>
                                {t('app.scannerTab.uploadYar', 'Upload .yar')}
                            </Button>
                        </div>
                    </div>
                    <div className="card-body">
                        {!rules ? (
                            <div className="loading-sm">{t('app.scannerTab.loading', 'Loading...')}</div>
                        ) : (
                            <>
                                <p className="sec-hint sec-hint--lead">
                                    {rules.builtin_count} {t('app.scannerTab.curatedWebShellIndicatorsRunOn', 'curated web-shell indicators run on every scan (engine:')} <span className="sec-mono">{rules.engine}</span>).
                                    {rules.engine === 'fallback' && ' Install yara to enable custom .yar rule files.'}
                                </p>
                                {rules.custom.length === 0 ? (
                                    <p className="sec-hint">{t('app.scannerTab.noCustomRuleFilesUploadA', 'No custom rule files. Upload a .yar file (max 64 KB) to extend the rule set.')}</p>
                                ) : (
                                    <div className="yara-custom-list">
                                        {rules.custom.map((c) => (
                                            <div key={c.name} className="yara-custom-item">
                                                <span className="sec-mono">{c.name}</span>
                                                <span className="sec-faint sec-mono">{c.size} B</span>
                                                {!rules.custom_rules_active && (
                                                    <span className="sec-state sec-state--gray">{t('app.scannerTab.inactiveYaraNotInstalled', 'inactive — yara not installed')}</span>
                                                )}
                                                <Button variant="ghost" size="sm" onClick={() => handleDeleteRule(c.name)}>
                                                    <Trash2 size={14} />
                                                </Button>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                </div>
            )}

            {(isScanning || jobRunning) && (
                <div className="card scan-progress">
                    <div className="card-header">
                        <h3>{t('app.scannerTab.scanInProgress', 'Scan in Progress')}</h3>
                        {isScanning && (
                            <Button variant="destructive" size="sm" onClick={handleCancelScan}>
                                {t('app.scannerTab.cancel', 'Cancel')}
                            </Button>
                        )}
                    </div>
                    <div className="card-body">
                        <div className="progress-info">
                            <div className="spinner"></div>
                            <div>
                                {scanStatus.directory && (
                                    <p><strong>{t('app.scannerTab.scanning', 'Scanning:')}</strong> <span className="sec-mono">{scanStatus.directory}</span></p>
                                )}
                                {scanStatus.started_at && (
                                    <p><strong>{t('app.scannerTab.started', 'Started:')}</strong> <span className="sec-mono">{new Date(scanStatus.started_at).toLocaleString()}</span></p>
                                )}
                                {jobRunning && (
                                    <p><strong>{t('app.scannerTab.job', 'Job:')}</strong> <span className="sec-mono">{scanJob.id} · {scanJob.status}</span></p>
                                )}
                                {scanStatus.files_scanned > 0 && (
                                    <p><strong>{t('app.scannerTab.filesScanned', 'Files scanned:')}</strong> <span className="sec-mono">{scanStatus.files_scanned}</span></p>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {findings.length > 0 && (
                <div className="card sec-flush scan-findings">
                    <div className="card-header">
                        {/* The view name replaces the section heading — two
                            titles stacked would compete, and the view IS what
                            you are looking at. The card keeps its red border,
                            so the alarm does not depend on the words. */}
                        <GridViewPicker
                            views={findingsChrome.views}
                            label="findings"
                            onCreate={findingsChrome.createView}
                            actions={(
                                <>
                                    <GridFilterButton
                                        count={findingsChrome.filterCount}
                                        onClick={() => findingsChrome.setDrawerOpen(true)}
                                    />
                                    <GridToolsMenu {...findingsChrome.toolsProps} onRefresh={loadScanStatus} />
                                </>
                            )}
                        />
                        <div className="sec-tableactions">
                            {/* Dismiss throws the findings away rather than
                                narrowing them, so it stays out of the chrome. */}
                            <Button variant="outline" size="sm" onClick={() => setFindings([])}>{t('app.scannerTab.dismiss', 'Dismiss')}</Button>
                        </div>
                    </div>
                    <GridChips {...findingsChrome.chipProps} />
                    <DataTable
                        columns={findingsChrome.columns}
                        data={findings}
                        keyField={(f) => `${f.file}-${f.rule}-${f.source}`}
                        sorts={findingsSorts.sorts}
                        onSortsChange={findingsSorts.setSorts}
                        {...findingsChrome.tableProps}
                        footer={(
                            <DataTableFooter
                                shown={shownFindings.length}
                                total={findings.length}
                                noun="finding"
                            />
                        )}
                    />
                    <GridFilterDrawer {...findingsChrome.drawerProps} />
                </div>
            )}

            <div className="card sec-flush">
                <div className="card-header">
                    {/* Refresh is not repeated as a button next to the "⋮" that
                        already carries it. */}
                    <GridViewPicker
                        views={historyChrome.views}
                        label="scans"
                        onCreate={historyChrome.createView}
                        actions={(
                            <>
                                <GridFilterButton
                                    count={historyChrome.filterCount}
                                    onClick={() => historyChrome.setDrawerOpen(true)}
                                />
                                <GridToolsMenu {...historyChrome.toolsProps} onRefresh={loadHistory} />
                            </>
                        )}
                    />
                </div>
                <GridChips {...historyChrome.chipProps} />
                {history.length === 0 ? (
                    <div className="card-body">
                        <EmptyState
                            icon={Search}
                            title={t('app.scannerTab.noScansHaveBeenRunYet', 'No scans have been run yet.')}
                            description={t('app.scannerTab.startAScanAboveToCheck', 'Start a scan above to check for threats.')}
                        />
                    </div>
                ) : (
                    <DataTable
                        columns={historyChrome.columns}
                        data={history}
                        keyField={(scan) => `${scan.started_at}-${scan.directory}`}
                        sorts={historySorts.sorts}
                        onSortsChange={historySorts.setSorts}
                        {...historyChrome.tableProps}
                        footer={(
                            <DataTableFooter
                                shown={shownHistory.length}
                                total={history.length}
                                noun="scan"
                            />
                        )}
                    />
                )}
                <GridFilterDrawer {...historyChrome.drawerProps} />
            </div>
        </div>
    );
};

export default ScannerTab;
