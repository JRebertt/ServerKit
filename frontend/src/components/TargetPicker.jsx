import { useState, useEffect, useMemo } from 'react';
import { Server } from 'lucide-react';
import { api } from '../services/api';
import { useTranslation } from 'react-i18next';

// TargetPicker — a small reusable selector for "local panel host vs.
// connected agent." Used by the Cron, Cloudflared, and File Manager
// pages to switch which server an action runs against.
//
// `feature` gates the agent list: only agents that report
// capabilities[feature] === true are shown. Agents that haven't
// reported capabilities yet (older builds) are filtered out — same
// pattern as the cron picker.
//
// onChange receives `{ kind: 'local' } | { kind: 'agent', server_id, name,
// allowedPaths, os_type, agentInstallDir, agentConfigDir }` (os_type:
// linux/windows/darwin, and the agent's self-reported footprint dirs — all
// null for agents that predate sysinfo reporting), or `{ kind: <extra.value> }`
// for any caller-supplied `extraOptions` (e.g. an "S3 bucket" target in the
// File Manager).
export default function TargetPicker({ feature, value, onChange, includeLocal = true, extraOptions = [] }) {
    const { t } = useTranslation();
    const [servers, setServers] = useState([]);

    useEffect(() => {
        let cancelled = false;
        api.getAvailableServers()
            .then(data => { if (!cancelled) setServers(Array.isArray(data) ? data : []); })
            .catch(() => { if (!cancelled) setServers([]); });
        return () => { cancelled = true; };
    }, []);

    const eligible = useMemo(() => {
        return servers.filter(s => {
            if (s.id === 'local') return false; // handled separately
            if (s.status !== 'online') return false;
            if (!feature) return true;
            return s.capabilities && s.capabilities[feature];
        });
    }, [servers, feature]);

    function handleChange(e) {
        const id = e.target.value;
        if (id === 'local') {
            onChange({ kind: 'local' });
            return;
        }
        if (extraOptions.some(o => o.value === id)) {
            onChange({ kind: id });
            return;
        }
        const s = eligible.find(x => x.id === id);
        if (!s) return;
        onChange({
            kind: 'agent',
            server_id: s.id,
            name: s.name || s.hostname || s.id,
            allowedPaths: s.allowed_paths || [],
            os_type: s.os_type || null,
            agentInstallDir: s.agent_install_dir || null,
            agentConfigDir: s.agent_config_dir || null,
        });
    }

    const selectValue = value?.kind === 'agent'
        ? value.server_id
        : (value?.kind && value.kind !== 'local' ? value.kind : 'local');

    const optionCount = (includeLocal ? 1 : 0) + eligible.length + extraOptions.length;
    const singleLabel = useMemo(() => {
        if (selectValue !== 'local') {
            const agent = eligible.find(s => s.id === selectValue);
            if (agent) return agent.name || agent.hostname || agent.id;
            const extra = extraOptions.find(o => o.value === selectValue);
            if (extra) return extra.label;
        }
        return 'Local (this server)';
    }, [selectValue, eligible, extraOptions]);

    return (
        <div className="target-picker">
            <Server size={14} className="target-picker__icon" />
            {optionCount <= 1 ? (
                <span className="target-picker__single">{singleLabel}</span>
            ) : (
                <select value={selectValue} onChange={handleChange} className="target-picker__select">
                    {includeLocal && <option value="local">{t('app.targetPicker.localThisServer', 'Local (this server)')}</option>}
                    {eligible.map(s => (
                        <option key={s.id} value={s.id}>
                            {s.name || s.hostname || s.id}
                        </option>
                    ))}
                    {extraOptions.map(o => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                </select>
            )}
        </div>
    );
}
