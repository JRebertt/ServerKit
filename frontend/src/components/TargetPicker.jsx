import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import ResourcePicker from './ResourcePicker';
import { api } from '../services/api';

const enabledCapabilities = (server) => Object.entries(server?.capabilities || {})
    .filter(([, enabled]) => enabled === true)
    .map(([name]) => name);

const onlineServersOnly = (resource) => (
    resource.type !== 'server' || resource.status === 'online'
);

// Compatibility adapter around ResourcePicker. Callers keep receiving the
// operational target shape while selection itself now uses scoped ResourceRef
// search, capability filters, keyboard navigation, and recent resources.
export default function TargetPicker({
    feature,
    value,
    onChange,
    includeLocal = true,
    extraOptions = [],
}) {
    const { t } = useTranslation();
    const [servers, setServers] = useState([]);

    useEffect(() => {
        let cancelled = false;
        api.getAvailableServers()
            .then((data) => {
                if (!cancelled) setServers(Array.isArray(data) ? data : []);
            })
            .catch(() => {
                if (!cancelled) setServers([]);
            });
        return () => { cancelled = true; };
    }, []);

    const localOption = useMemo(() => ({
        type: 'target',
        id: 'local',
        label: t('app.targetPicker.localThisServer', 'Local (this server)'),
        sublabel: '',
        path: '/servers',
        scope: {},
        status: 'online',
        capabilities: [],
    }), [t]);

    const staticOptions = useMemo(() => [
        ...(includeLocal ? [localOption] : []),
        ...extraOptions.map((option) => ({
            type: 'target',
            id: String(option.value),
            label: option.label,
            sublabel: '',
            path: '/files',
            scope: {},
            status: null,
            capabilities: [],
        })),
    ], [extraOptions, includeLocal, localOption]);

    const selectedResource = useMemo(() => {
        if (value?.kind === 'agent') {
            const server = servers.find((candidate) => String(candidate.id) === String(value.server_id));
            return {
                type: 'server',
                id: String(value.server_id),
                label: value.name || server?.name || server?.hostname || String(value.server_id),
                sublabel: server?.ip_address || server?.hostname || '',
                path: `/servers/${value.server_id}`,
                scope: {},
                status: server?.status || null,
                capabilities: enabledCapabilities(server),
            };
        }
        if (value?.kind && value.kind !== 'local') {
            return staticOptions.find((option) => option.id === String(value.kind)) || null;
        }
        return localOption;
    }, [localOption, servers, staticOptions, value]);

    const handleChange = (resource) => {
        if (resource.type === 'target') {
            onChange(resource.id === 'local' ? { kind: 'local' } : { kind: resource.id });
            return;
        }
        const server = servers.find((candidate) => String(candidate.id) === resource.id);
        onChange({
            kind: 'agent',
            server_id: resource.id,
            name: resource.label,
            allowedPaths: server?.allowed_paths || [],
            os_type: server?.os_type || null,
            agentInstallDir: server?.agent_install_dir || null,
            agentConfigDir: server?.agent_config_dir || null,
        });
    };

    return (
        <div className="target-picker">
            <ResourcePicker
                value={selectedResource}
                onChange={handleChange}
                types={['server']}
                capabilities={feature ? [feature] : []}
                staticOptions={staticOptions}
                filterOption={onlineServersOnly}
                label={t('app.serverPicker.filterServers', 'Filter servers')}
                placeholder={t('app.targetPicker.localThisServer', 'Local (this server)')}
                searchPlaceholder={t('app.serverPicker.findAServer', 'Find a server…')}
                className="target-picker__resource"
            />
        </div>
    );
}
