import { useCallback, useEffect, useState } from 'react';
import api from '../../services/api';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { DataTable, DataTableFooter } from '@/components/ds';

// Scoped file-integrity monitoring: baseline-and-diff over the paths
// ServerKit manages (nginx configs, serverkit-owned systemd units, and
// app docroots on explicit per-app opt-in).

const SCOPE_META = {
    nginx: {
        label: 'Nginx configuration',
        hint: 'sites-enabled + conf.d',
    },
    systemd: {
        label: 'Systemd units',
        hint: 'serverkit-* units in /etc/systemd/system',
    },
};

function formatAge(iso) {
    if (!iso) return null;
    const ms = Date.now() - new Date(iso).getTime();
    if (Number.isNaN(ms)) return null;
    const mins = Math.floor(ms / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 48) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
}

function scopeLabel(scope) {
    if (SCOPE_META[scope.scope]) return SCOPE_META[scope.scope].label;
    return scope.app_name ? `App: ${scope.app_name}` : `App #${scope.app_id}`;
}

const IntegrityTab = () => {
    const [status, setStatus] = useState(null);
    const [apps, setApps] = useState([]);
    const [busy, setBusy] = useState(null); // `${scope}:${action}` while a call runs
    const [savingOptins, setSavingOptins] = useState(false);
    const [message, setMessage] = useState(null);
    const [expanded, setExpanded] = useState(null); // scope whose changes table is open

    const load = useCallback(async () => {
        try {
            const data = await api.request('/security/fim');
            setStatus(data);
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        }
    }, []);

    useEffect(() => {
        load();
        api.getApps().then(
            (data) => setApps(data.apps || []),
            () => {} // apps list is optional chrome; FIM still works without it
        );
    }, [load]);

    async function runAction(scope, action) {
        setBusy(`${scope}:${action}`);
        setMessage(null);
        try {
            const result = await api.request(`/security/fim/${scope}/${action}`, { method: 'POST' });
            if (action === 'check') {
                setExpanded(result.total_changes > 0 ? scope : null);
                setMessage(result.total_changes === 0
                    ? { type: 'success', text: `${scope}: no changes since baseline` }
                    : { type: 'error', text: `${scope}: ${result.total_changes} change(s) detected` });
            } else {
                setExpanded(null);
                setMessage({
                    type: 'success',
                    text: `${scope}: baseline saved (${result.file_count} files)`,
                });
            }
            await load();
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setBusy(null);
        }
    }

    async function toggleApp(appId, enabled) {
        const current = status?.app_optins || [];
        const next = enabled
            ? [...new Set([...current, appId])]
            : current.filter((id) => id !== appId);
        setSavingOptins(true);
        setMessage(null);
        try {
            await api.request('/security/fim/apps', { method: 'PUT', body: { app_ids: next } });
            await load();
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setSavingOptins(false);
        }
    }

    const scopes = status?.scopes || [];
    const optins = status?.app_optins || [];

    function renderChanges(scope) {
        const check = scope.last_check;
        if (!check || check.total_changes === 0 || expanded !== scope.scope) return null;
        const rows = [
            ...(check.added || []).map((p) => ({ kind: 'added', tone: 'green', path: p, what: null })),
            ...(check.removed || []).map((p) => ({ kind: 'removed', tone: 'red', path: p, what: null })),
            ...(check.modified || []).map((m) => ({
                kind: 'modified', tone: 'amber', path: m.path, what: m.what,
            })),
        ];
        const shown = rows.slice(0, 200);
        // Cell markup/classNames identical to the hand-rolled table they
        // replace. The old "… and N more" truncation row is now the standard
        // DataTableFooter count ("Shown 200 of N changes").
        const columns = [
            {
                key: 'change',
                header: 'Change',
                sortable: true,
                sortValue: (row) => row.kind,
                render: (row) => <span className={`sec-state sec-state--${row.tone}`}>{row.kind}</span>,
            },
            {
                key: 'path',
                header: 'Path',
                sortable: true,
                sortValue: (row) => row.path,
                cellClassName: 'sk-cell-mono sec-path',
                render: (row) => row.path,
            },
            {
                key: 'what',
                header: 'What changed',
                render: (row) => (
                    row.what ? (
                        <span className="sec-what">
                            {row.what.map((w) => (
                                <span key={w} className="sec-state sec-state--gray">{w}</span>
                            ))}
                        </span>
                    ) : (
                        <span className="sec-dash">—</span>
                    )
                ),
            },
        ];
        return (
            <DataTable
                columns={columns}
                data={shown}
                keyField={(row) => `${row.kind}:${row.path}`}
                storageKey="serverkit-table-integrity-changes"
                footer={(
                    <DataTableFooter
                        shown={shown.length}
                        total={rows.length}
                        noun="change"
                    />
                )}
            />
        );
    }

    function renderScopeCard(scope) {
        const key = scope.scope;
        const baseline = scope.baseline;
        const check = scope.last_check;
        const changed = check && check.total_changes > 0;
        return (
            <div className="card sec-flush" key={key}>
                <div className="card-header">
                    <h3>
                        {scopeLabel(scope)}{' '}
                        <span className="sec-count">
                            · {SCOPE_META[key]?.hint || (scope.roots[0] || 'no docroot')}
                        </span>
                    </h3>
                    {!scope.available && <span className="sec-state sec-state--gray">not present</span>}
                    {scope.available && !baseline && <span className="sec-state sec-state--gray">no baseline</span>}
                    {baseline && !check && <span className="sec-state sec-state--cyan">baselined</span>}
                    {check && (changed
                        ? <span className="sec-state sec-state--amber">{check.total_changes} changes</span>
                        : <span className="sec-state sec-state--green">clean</span>)}
                </div>
                <div className="card-body">
                    <p className="sec-hint--lead sec-hint">
                        {baseline
                            ? `Baseline: ${baseline.file_count} files, ${formatAge(baseline.created_at) || 'unknown age'}`
                            : 'No baseline yet — create one to start tracking changes.'}
                        {check && ` · Last check ${formatAge(check.checked_at) || ''}`}
                    </p>
                    <div className="card-actions">
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => runAction(key, 'baseline')}
                            disabled={!scope.available || busy !== null}
                        >
                            {busy === `${key}:baseline` ? 'Baselining…' : 'Baseline'}
                        </Button>
                        <Button
                            variant="default"
                            size="sm"
                            onClick={() => runAction(key, 'check')}
                            disabled={!baseline || busy !== null}
                        >
                            {busy === `${key}:check` ? 'Checking…' : 'Check now'}
                        </Button>
                        {changed && (
                            <>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => runAction(key, 'accept')}
                                    disabled={busy !== null}
                                >
                                    {busy === `${key}:accept` ? 'Accepting…' : 'Accept changes'}
                                </Button>
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => setExpanded(expanded === key ? null : key)}
                                >
                                    {expanded === key ? 'Hide changes' : 'View changes'}
                                </Button>
                            </>
                        )}
                    </div>
                </div>
                {renderChanges(scope)}
            </div>
        );
    }

    const managedScopes = scopes.filter((s) => !s.scope.startsWith('app:'));
    const appScopes = scopes.filter((s) => s.scope.startsWith('app:'));

    return (
        <div className="integrity-tab">
            {message && (
                <div className={`alert alert-${message.type === 'success' ? 'success' : 'danger'}`}>
                    {message.text}
                </div>
            )}

            <p className="sec-hint sec-hint--lead">
                Baseline-and-diff monitoring over the paths ServerKit manages. Baseline a
                scope, then check it (or let the scheduled sweep do it) — any added,
                removed or modified files are flagged and admins are notified. Accepting
                changes re-baselines the scope.
            </p>

            {managedScopes.map(renderScopeCard)}
            {appScopes.map(renderScopeCard)}

            <div className="card">
                <div className="card-header">
                    <h3>Application docroots <span className="sec-count">· opt-in</span></h3>
                </div>
                <div className="card-body">
                    <p className="sec-hint sec-hint--lead">
                        Watching a docroot hashes every file outside upload/cache
                        directories, so it is opt-in per application.
                    </p>
                    {apps.length === 0 ? (
                        <p className="sec-faint">No applications found.</p>
                    ) : (
                        <div className="sec-finding-list">
                            {apps.map((appItem) => (
                                <div className="sec-finding" key={appItem.id}>
                                    <Switch
                                        checked={optins.includes(appItem.id)}
                                        disabled={savingOptins}
                                        onCheckedChange={(checked) => toggleApp(appItem.id, checked)}
                                    />
                                    <div className="sec-finding__msg">
                                        {appItem.name}{' '}
                                        <span className="sec-mono">{appItem.root_path || 'no docroot'}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default IntegrityTab;
