import { useState, useEffect, useRef } from 'react';
import api from '../../services/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { DataTable, DataTableFooter, Pill } from '@/components/ds';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { Zap, Radar, FolderSearch, Download, Box, ShieldAlert, FileCode2, Trash2, Search } from 'lucide-react';
import EmptyState from '@/components/EmptyState';

const SEVERITY_TONE = {
    critical: 'red',
    high: 'red',
    medium: 'amber',
    low: 'gray',
};

const ScannerTab = () => {
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
    const jobPollRef = useRef(null);

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
        const interval = setInterval(loadScanStatus, 5000);
        return () => {
            clearInterval(interval);
            if (jobPollRef.current) clearInterval(jobPollRef.current);
        };
    }, []);

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

    function pollJob(jobId) {
        if (jobPollRef.current) clearInterval(jobPollRef.current);
        jobPollRef.current = setInterval(async () => {
            try {
                const job = await api.getJob(jobId);
                setScanJob(job);
                if (['succeeded', 'failed', 'cancelled'].includes(job.status)) {
                    clearInterval(jobPollRef.current);
                    jobPollRef.current = null;
                    if (job.status === 'succeeded' && job.result?.findings) {
                        setFindings(job.result.findings);
                        const n = job.result.findings.length;
                        setMessage({
                            type: n > 0 ? 'error' : 'success',
                            text: n > 0
                                ? `Scan finished: ${n} finding(s) — review below`
                                : 'Scan finished: no threats found'
                        });
                    } else if (job.status === 'failed') {
                        setMessage({ type: 'error', text: job.error_message || 'Scan job failed' });
                    }
                    loadScanStatus();
                    loadHistory();
                }
            } catch (err) {
                console.error('Failed to poll scan job:', err);
            }
        }, 3000);
    }

    async function handleScanApp() {
        if (!selectedApp) return;
        setScanning(true);
        setMessage(null);
        try {
            const result = await api.scanApp(selectedApp);
            setScanJob({ id: result.job_id, status: 'pending' });
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
        if (!confirm(`Delete custom rule file ${name}?`)) return;
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
            header: 'Rule',
            sortable: true,
            hideable: false,
            sortValue: (f) => f.rule || '',
            cellClassName: 'sk-cell-mono',
            render: (f) => <span title={f.description}>{f.rule}</span>,
        },
        {
            key: 'severity',
            header: 'Severity',
            sortable: true,
            sortValue: (f) => f.severity || '',
            render: (f) => (
                <span className={`sec-state sec-state--${SEVERITY_TONE[f.severity] || 'gray'}`}>
                    {f.severity}
                </span>
            ),
        },
        {
            key: 'file',
            header: 'File',
            sortable: true,
            sortValue: (f) => f.file || '',
            cellClassName: 'sk-cell-mono sec-path sec-path--red',
            render: (f) => <span title={f.file}>{f.file}</span>,
        },
        {
            key: 'match',
            header: 'Match',
            cellClassName: 'sk-cell-mono scan-snippet',
            render: (f) => f.matched || '—',
        },
        {
            key: 'source',
            header: 'Source',
            sortable: true,
            sortValue: (f) => f.source || '',
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
            header: 'Date',
            sortable: true,
            hideable: false,
            sortValue: (scan) => {
                const t = new Date(scan.started_at).getTime();
                return Number.isNaN(t) ? null : t;
            },
            cellClassName: 'sk-cell-mono sec-faint',
            render: (scan) => new Date(scan.started_at).toLocaleString(),
        },
        {
            key: 'directory',
            header: 'Directory',
            sortable: true,
            sortValue: (scan) => scan.directory || '',
            cellClassName: 'sk-cell-mono sec-path',
            render: (scan) => scan.directory,
        },
        {
            key: 'status',
            header: 'Status',
            sortable: true,
            sortValue: (scan) => scan.status || '',
            render: (scan) => (
                <Pill kind={scan.status === 'completed' ? 'green' : scan.status === 'error' ? 'red' : 'amber'}>
                    {scan.status}
                </Pill>
            ),
        },
        {
            key: 'threats',
            header: 'Threats',
            sortable: true,
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
                    <h4>Quick Scan</h4>
                    <span className="scan-desc">Scan common web directories</span>
                    <Button
                        variant="default"
                        size="sm"
                        onClick={(e) => { e.stopPropagation(); handleStartScan('quick'); }}
                        disabled={isScanning || scanning}
                    >
                        Start Scan
                    </Button>
                </div>

                <div className="scan-card scan-card--full" onClick={() => !isScanning && !scanning && handleStartScan('full')}>
                    <div className="scan-card-icon">
                        <Radar size={20} />
                    </div>
                    <h4>Full Scan</h4>
                    <span className="scan-desc">Scan entire system (slow)</span>
                    <Button
                        variant="default"
                        size="sm"
                        onClick={(e) => { e.stopPropagation(); handleStartScan('full'); }}
                        disabled={isScanning || scanning}
                    >
                        Start Scan
                    </Button>
                </div>

                <div className="scan-card scan-card--custom">
                    <div className="scan-card-icon">
                        <FolderSearch size={20} />
                    </div>
                    <h4>Custom Path</h4>
                    <span className="scan-desc">Scan a specific directory</span>
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
                            Scan
                        </Button>
                    </div>
                </div>

                <div className="scan-card scan-card--app">
                    <div className="scan-card-icon">
                        <Box size={20} />
                    </div>
                    <h4>Scan an App</h4>
                    <span className="scan-desc">Web-shell + malware scan of a docroot</span>
                    <div className="scan-custom-input">
                        <select
                            className="scan-app-select"
                            value={selectedApp}
                            onChange={(e) => setSelectedApp(e.target.value)}
                            disabled={jobRunning}
                        >
                            <option value="">Select an app…</option>
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
                    Web-shell Rules
                </Button>
                <Button variant="outline" size="sm" onClick={handleUpdateDefinitions} disabled={updating}>
                    <Download size={14} />
                    {updating ? 'Updating...' : 'Update Definitions'}
                </Button>
            </div>

            {showRules && (
                <div className="card sec-flush yara-rules-card">
                    <div className="card-header">
                        <h3>Web-shell Detection Rules{rules && <span className="sec-count"> · {rules.builtin_count} builtin</span>}</h3>
                        <div className="card-actions">
                            <input
                                ref={ruleFileRef}
                                type="file"
                                accept=".yar"
                                className="yara-file-input"
                                onChange={handleRuleFileChosen}
                            />
                            <Button variant="outline" size="sm" onClick={() => ruleFileRef.current?.click()}>
                                Upload .yar
                            </Button>
                        </div>
                    </div>
                    <div className="card-body">
                        {!rules ? (
                            <div className="loading-sm">Loading...</div>
                        ) : (
                            <>
                                <p className="sec-hint sec-hint--lead">
                                    {rules.builtin_count} curated web-shell indicators run on every scan
                                    (engine: <span className="sec-mono">{rules.engine}</span>).
                                    {rules.engine === 'fallback' && ' Install yara to enable custom .yar rule files.'}
                                </p>
                                {rules.custom.length === 0 ? (
                                    <p className="sec-hint">No custom rule files. Upload a .yar file (max 64 KB) to extend the rule set.</p>
                                ) : (
                                    <div className="yara-custom-list">
                                        {rules.custom.map((c) => (
                                            <div key={c.name} className="yara-custom-item">
                                                <span className="sec-mono">{c.name}</span>
                                                <span className="sec-faint sec-mono">{c.size} B</span>
                                                {!rules.custom_rules_active && (
                                                    <span className="sec-state sec-state--gray">inactive — yara not installed</span>
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
                        <h3>Scan in Progress</h3>
                        {isScanning && (
                            <Button variant="destructive" size="sm" onClick={handleCancelScan}>
                                Cancel
                            </Button>
                        )}
                    </div>
                    <div className="card-body">
                        <div className="progress-info">
                            <div className="spinner"></div>
                            <div>
                                {scanStatus.directory && (
                                    <p><strong>Scanning:</strong> <span className="sec-mono">{scanStatus.directory}</span></p>
                                )}
                                {scanStatus.started_at && (
                                    <p><strong>Started:</strong> <span className="sec-mono">{new Date(scanStatus.started_at).toLocaleString()}</span></p>
                                )}
                                {jobRunning && (
                                    <p><strong>Job:</strong> <span className="sec-mono">{scanJob.id} · {scanJob.status}</span></p>
                                )}
                                {scanStatus.files_scanned > 0 && (
                                    <p><strong>Files scanned:</strong> <span className="sec-mono">{scanStatus.files_scanned}</span></p>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {findings.length > 0 && (
                <div className="card sec-flush scan-findings">
                    <div className="card-header">
                        <h3 className="sec-listtitle--red">
                            <ShieldAlert size={13} />
                            Findings <span className="sec-count">· {findings.length}</span>
                        </h3>
                        <div className="sec-tableactions">
                            <Button variant="outline" size="sm" onClick={() => setFindings([])}>Dismiss</Button>
                        </div>
                    </div>
                    <DataTable
                        columns={findingColumns}
                        data={findings}
                        keyField={(f) => `${f.file}-${f.rule}-${f.source}`}
                        sorts={findingsSorts.sorts}
                        onSortsChange={findingsSorts.setSorts}
                        hiddenKeys={findingsCols.hiddenKeys}
                        onHiddenKeysChange={findingsCols.setHiddenKeys}
                        footer={(
                            <DataTableFooter
                                shown={findings.length}
                                total={findings.length}
                                noun="finding"
                            />
                        )}
                    />
                </div>
            )}

            <div className="card sec-flush">
                <div className="card-header">
                    <h3>Scan History</h3>
                    <div className="sec-tableactions">
                        <Button variant="outline" size="sm" onClick={loadHistory}>Refresh</Button>
                    </div>
                </div>
                {history.length === 0 ? (
                    <div className="card-body">
                        <EmptyState
                            icon={Search}
                            title="No scans have been run yet."
                            description="Start a scan above to check for threats."
                        />
                    </div>
                ) : (
                    <DataTable
                        columns={historyColumns}
                        data={history}
                        keyField={(scan) => `${scan.started_at}-${scan.directory}`}
                        sorts={historySorts.sorts}
                        onSortsChange={historySorts.setSorts}
                        hiddenKeys={historyCols.hiddenKeys}
                        onHiddenKeysChange={historyCols.setHiddenKeys}
                        footer={(
                            <DataTableFooter
                                shown={history.length}
                                total={history.length}
                                noun="scan"
                            />
                        )}
                    />
                )}
            </div>
        </div>
    );
};

export default ScannerTab;
