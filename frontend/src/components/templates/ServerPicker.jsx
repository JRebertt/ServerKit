import { useMemo } from 'react';
import { Server } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import ResourcePicker from '../ResourcePicker';
import { formatBytes } from '../../utils/formatBytes';

const enabledCapabilities = (server) => Object.entries(server?.capabilities || {})
    .filter(([, enabled]) => enabled === true)
    .map(([name]) => name);

function capacityLabel(server) {
    const parts = [];
    if (server.cpu_cores) parts.push(`${server.cpu_cores} vCPU`);
    if (server.total_memory) parts.push(formatBytes(server.total_memory, { decimals: 0 }));
    return parts.join(' · ');
}

function serverResource(server) {
    const capacity = capacityLabel(server);
    const location = server.is_local ? 'this panel' : (server.group_name || 'remote');
    const platform = server.os_type ? `${location} · ${server.os_type}` : location;
    const capabilities = enabledCapabilities(server);
    if ((server.is_local || server.has_docker) && !capabilities.includes('docker')) {
        capabilities.push('docker');
    }
    return {
        type: server.is_local ? 'server-target' : 'server',
        id: String(server.id),
        label: server.name || String(server.id),
        sublabel: [platform, capacity].filter(Boolean).join(' · '),
        path: server.is_local ? '/servers' : `/servers/${server.id}`,
        scope: { workspaceId: server.workspace_id ?? null },
        status: server.status || null,
        capabilities,
    };
}

export default function ServerPicker({ servers, value, onChange }) {
    const { t } = useTranslation();
    const serverById = useMemo(
        () => new Map(servers.map((server) => [String(server.id), server])),
        [servers],
    );
    const staticOptions = useMemo(
        () => servers.filter((server) => server.is_local).map(serverResource),
        [servers],
    );
    const selectedServer = serverById.get(String(value));
    const selectedResource = selectedServer ? serverResource(selectedServer) : null;
    const decorateOption = (resource) => {
        const server = serverById.get(resource.id);
        if (!server) return resource;
        const metadata = serverResource(server);
        return {
            ...resource,
            sublabel: metadata.sublabel,
            capabilities: [...new Set([...resource.capabilities, ...metadata.capabilities])],
        };
    };

    return (
        <ResourcePicker
            value={selectedResource}
            onChange={(resource) => {
                const server = serverById.get(resource.id);
                onChange(server?.id ?? resource.id);
            }}
            types={['server']}
            capabilities={['docker']}
            staticOptions={staticOptions}
            filterOption={(resource) => (
                resource.type === 'server-target' || serverById.has(resource.id)
            )}
            decorateOption={decorateOption}
            icon={Server}
            showCapabilities
            label={t('app.serverPicker.deployToServer', 'Deploy to server')}
            placeholder={t('app.serverPicker.deployToServer', 'Deploy to server')}
            searchPlaceholder={t('app.serverPicker.findAServer', 'Find a server…')}
            emptyMessage={t('app.serverPicker.noServersMatch', 'No servers match.')}
            className="sk-srvpick__resource-picker"
        />
    );
}
