// Shared vocabulary for the fleet-scoped monitoring panels (heatmap, capacity,
// fleet alerts). These used to live inside the standalone Fleet Monitor page;
// they moved here when that page folded into /monitoring so the three panels
// can share one metric label map and one heat scale.

export const CHART_COLORS = [
    '#6366f1', '#ec4899', '#14b8a6', '#f59e0b',
    '#8b5cf6', '#06b6d4', '#ef4444', '#22c55e',
    '#a855f7', '#f97316',
];

export const METRIC_LABELS = {
    cpu: 'CPU %',
    memory: 'Memory %',
    disk: 'Disk %',
    network_rx: 'Network RX',
    network_tx: 'Network TX',
};

// Percentage → heat bucket. Drives the `is-*` class on heatmap cells and the
// legend dots (see styles/pages/_fleet-monitor.scss).
export const heatLevel = (value) => {
    if (value == null) return 'empty';
    if (value >= 90) return 'critical';
    if (value >= 75) return 'high';
    if (value >= 50) return 'medium';
    return 'low';
};
