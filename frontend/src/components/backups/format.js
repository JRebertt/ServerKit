// Shared formatting helpers for the backup "Protection" components.
import { timeAgo } from '@/utils/time';

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];

// Human-readable byte size, e.g. "2.3 GB". Matches the global Backups page style.
export function humanSize(bytes) {
    if (!bytes || bytes < 0) return '0 B';
    let size = bytes;
    let i = 0;
    while (size >= 1024 && i < UNITS.length - 1) {
        size /= 1024;
        i += 1;
    }
    return `${size.toFixed(1)} ${UNITS[i]}`;
}

// Money like "$0.04" / "$1.20"; falls back to 4 decimals for sub-cent values.
export function formatMoney(value) {
    const n = Number(value || 0);
    if (n === 0 || n >= 0.01) return `$${n.toFixed(2)}`;
    return `$${n.toFixed(4)}`;
}

// "Jan 15, 2026 · 4h ago" — absolute date plus a compact relative suffix.
export function formatWhen(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    const date = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    const rel = timeAgo(iso); // 'just now' | '4h' | '2d' | locale date
    if (rel === 'just now') return `${date} · just now`;
    if (/^\d+[mhd]$/.test(rel)) return `${date} · ${rel} ago`;
    return date;
}

// "Jan 15, 2026, 02:00 AM"
export function formatDateTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleString(undefined, {
        month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
    });
}

// Pill kind for a run/policy status, from the ONE shared vocabulary (plan 77 D3).
export { statusKind } from '../ds/status';

// Where a run is stored, from its size/remote fields.
export function storageLabel(run) {
    const hasRemote = !!run.remote_key || (run.size_remote || 0) > 0;
    const hasLocal = !!run.storage_path || (run.size_local || 0) > 0;
    if (hasLocal && hasRemote) return 'both';
    if (hasRemote) return 'remote';
    return 'local';
}
