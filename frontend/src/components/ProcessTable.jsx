import { X, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { DataTable, DataTableFooter } from '@/components/ds';

export function UsageCell({ percent = 0, variant = 'cpu' }) {
    const clamped = Math.min(Number(percent) || 0, 100);
    return (
        <div className="usage-cell">
            <div className={`usage-bar ${variant}`} style={{ width: `${clamped}%` }} />
            <span>{clamped.toFixed(1)}%</span>
        </div>
    );
}

export function ProcessTable({
    processes = [],
    selectedPid = null,
    onSelect,
    onKill,
    onForceKill,
    formatMemory = defaultFormatMemory,
    getStatusVariant = defaultGetStatusVariant,
}) {
    // DataTable columns. Cell markup and classNames are identical to the
    // hand-rolled table they replace, so _terminal.scss keeps applying
    // (.processes-table, .mono, .process-name, .usage-cell, .action-buttons).
    // No menus: this component has no toolbar row of its own, and the SCSS
    // pins column widths by nth-child, so columns stay visible.
    const columns = [
        {
            key: 'pid',
            header: 'PID',
            sortable: true,
            sortValue: (p) => p.pid,
            cellClassName: 'mono',
            render: (p) => p.pid,
        },
        {
            key: 'name',
            header: 'Name',
            sortable: true,
            hideable: false,
            sortValue: (p) => p.name || '',
            render: (p) => <div className="process-name"><span>{p.name}</span></div>,
        },
        {
            key: 'user',
            header: 'User',
            sortable: true,
            sortValue: (p) => p.user || '',
            render: (p) => p.user,
        },
        {
            key: 'cpu',
            header: 'CPU %',
            sortable: true,
            sortValue: (p) => Number(p.cpu_percent) || 0,
            render: (p) => <UsageCell percent={p.cpu_percent} variant="cpu" />,
        },
        {
            key: 'memoryPercent',
            header: 'Memory %',
            sortable: true,
            sortValue: (p) => Number(p.memory_percent) || 0,
            render: (p) => <UsageCell percent={p.memory_percent} variant="memory" />,
        },
        {
            key: 'memory',
            header: 'Memory',
            sortable: true,
            sortValue: (p) => p.memory_info?.rss ?? null,
            render: (p) => formatMemory(p.memory_info?.rss),
        },
        {
            key: 'status',
            header: 'Status',
            sortable: true,
            sortValue: (p) => p.status || '',
            render: (p) => (
                <Badge variant={getStatusVariant(p.status)}>{p.status}</Badge>
            ),
        },
        {
            key: '__actions',
            header: 'Actions',
            sortable: false,
            hideable: false,
            render: (p) => (
                <div className="action-buttons">
                     {onKill && (
                        <Button
                            variant="outline"
                            size="icon"
                            className="process-action-button"
                            onClick={(e) => { e.stopPropagation(); onKill(p); }}
                            title="Kill"
                            aria-label={`Kill ${p.name}`}
                        >
                            <X size={12} />
                        </Button>
                    )}
                    {onForceKill && (
                        <Button
                            variant="destructive"
                            size="icon"
                            className="process-action-button"
                            onClick={(e) => { e.stopPropagation(); onForceKill(p); }}
                            title="Force Kill"
                            aria-label={`Force kill ${p.name}`}
                        >
                            <AlertTriangle size={12} />
                        </Button>
                    )}
                </div>
            ),
        },
    ];

    return (
        <DataTable
            columns={columns}
            data={processes}
            keyField="pid"
            storageKey="serverkit-table-processes"
            onRowClick={(p) => onSelect?.(p)}
            rowClassName={(p) => (selectedPid === p.pid ? 'selected' : '')}
            className="processes-table-wrapper"
            tableClassName="table processes-table"
            footer={(
                <DataTableFooter
                    shown={processes.length}
                    total={processes.length}
                    noun="process"
                />
            )}
        />
    );
}

export function ProcessDetailsPanel({ process, onClose, formatMemory = defaultFormatMemory }) {
    if (!process) return null;
    return (
        <div className="process-details-panel">
            <div className="panel-header">
                <h3>Process Details</h3>
                <Button variant="outline" size="sm" onClick={onClose}>Close</Button>
            </div>
            <div className="panel-body">
                <div className="details-grid">
                    <DetailItem label="PID" value={process.pid} mono />
                    <DetailItem label="Name" value={process.name} />
                    <DetailItem label="User" value={process.user} />
                    <DetailItem label="Status" value={process.status} />
                    <DetailItem label="CPU" value={`${(process.cpu_percent || 0).toFixed(2)}%`} />
                    <DetailItem label="Memory" value={formatMemory(process.memory_info?.rss)} />
                    <DetailItem label="Threads" value={process.num_threads} />
                    <DetailItem
                        label="Created"
                        value={process.create_time ? new Date(process.create_time * 1000).toLocaleString() : '-'}
                    />
                </div>
                {process.command && (
                    <div className="command-line">
                        <span className="detail-label">Command</span>
                        <code>{process.command}</code>
                    </div>
                )}
            </div>
        </div>
    );
}

export function DetailItem({ label, value, mono = false, children }) {
    const valueClass = ['detail-value', mono && 'mono'].filter(Boolean).join(' ');
    return (
        <div className="detail-item">
            <span className="detail-label">{label}</span>
            {children ?? <span className={valueClass}>{value}</span>}
        </div>
    );
}

function defaultFormatMemory(bytes) {
    if (!bytes) return '-';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    while (bytes >= 1024 && i < units.length - 1) {
        bytes /= 1024;
        i++;
    }
    return `${bytes.toFixed(1)} ${units[i]}`;
}

function defaultGetStatusVariant(status) {
    switch (status?.toLowerCase()) {
        case 'running':
        case 'sleeping':
            return 'success';
        case 'stopped':
        case 'zombie':
            return 'destructive';
        case 'idle':
        case 'disk-sleep':
            return 'warning';
        default:
            return 'secondary';
    }
}

export default ProcessTable;
