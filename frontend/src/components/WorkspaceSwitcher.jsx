import { useEffect, useState } from 'react';
import { Building2 } from 'lucide-react';
import { api } from '../services/api';
import { useWorkspace } from '../contexts/WorkspaceContext';
import { useTranslation } from 'react-i18next';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from './ui/select';

// Active-workspace selector (#33). Self-contained: it reads/writes the active
// workspace through WorkspaceContext and reloads so existing pages re-fetch all
// lists under the new scope. Always rendered when at least one workspace exists
// so the scoping concept stays visible even on single-workspace installs.
const WorkspaceSwitcher = () => {
    const { t } = useTranslation();
    const [workspaces, setWorkspaces] = useState([]);
    const {
        activeWorkspaceId,
        clearActiveWorkspace,
        refreshActiveWorkspace,
        setActiveWorkspace,
    } = useWorkspace();

    useEffect(() => {
        let alive = true;
        api.getWorkspaces()
            .then((res) => {
                if (!alive) return;
                const list = res?.workspaces || [];
                setWorkspaces(list);
                if (activeWorkspaceId !== 'all') {
                    const ws = list.find((w) => String(w.id) === activeWorkspaceId);
                    if (!ws) {
                        // Stale selection (workspace deleted / access lost): clear it so
                        // a dead X-Workspace-Id header / brand color isn't applied.
                        clearActiveWorkspace();
                    } else {
                        // Keep workspace settings (brand color, nav permissions) fresh.
                        refreshActiveWorkspace(ws);
                    }
                }
            })
            .catch(() => { /* best-effort; the selector just won't render */ });
        return () => { alive = false; };
    }, [activeWorkspaceId, clearActiveWorkspace, refreshActiveWorkspace]);

    if (workspaces.length === 0) return null;

    const handleChange = (value) => {
        if (value === 'all') {
            clearActiveWorkspace();
        } else {
            const ws = workspaces.find((w) => String(w.id) === value);
            setActiveWorkspace(ws);
        }
        // Reload so every page re-fetches its lists (and re-applies the brand color)
        // under the new workspace scope.
        window.location.reload();
    };

    return (
        <Select value={activeWorkspaceId} onValueChange={handleChange}>
            <SelectTrigger className="workspace-switcher__trigger" aria-label={t('app.workspaceSwitcher.activeWorkspace', 'Active workspace')}>
                <Building2 size={14} className="workspace-switcher__icon" aria-hidden="true" />
                <SelectValue placeholder={t('app.workspaceSwitcher.allWorkspaces', 'All workspaces')} />
            </SelectTrigger>
            <SelectContent>
                <SelectItem value="all">{t('app.workspaceSwitcher.allWorkspaces', 'All workspaces')}</SelectItem>
                {workspaces.map((w) => (
                    <SelectItem key={w.id} value={String(w.id)}>{w.name}</SelectItem>
                ))}
            </SelectContent>
        </Select>
    );
};

export default WorkspaceSwitcher;
