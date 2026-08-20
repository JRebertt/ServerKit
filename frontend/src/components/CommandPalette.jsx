import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { translateLabel } from '../i18n/labels';
import {
    History, SlidersHorizontal, LayoutGrid, Zap, Server, Globe,
    Database, Boxes, Puzzle, BookOpen, KeyRound, Clock, ExternalLink, Star,
} from 'lucide-react';
import api from '../services/api';
import {
    CommandDialog,
    CommandInput,
    CommandList,
    CommandEmpty,
    CommandGroup,
    CommandItem,
} from '@/components/ui/command';
import { useContributions } from '../plugins/contributions';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';
import usePaletteAuthz from '../hooks/usePaletteAuthz';
import { PALETTE_PAGES } from '../data/palettePages';
import { SETTINGS_INDEX } from '../data/settingsIndex';
import { COMMAND_ACTIONS } from '../data/commandActions';
import { DOCS_LINKS } from '../utils/docsLinks';
import { scoreItem } from '../utils/paletteScore';
import { frecencyScore, recordUse, recentIds } from '../utils/paletteFrecency';
import { getFavorites, getRecents } from '../utils/recents';

// Group order in the list, plus a per-category icon and a scoring weight so the
// headline categories (Settings, Pages, Actions) outrank raw entity hits on ties.
const GROUP_ORDER = [
    'Favorites', 'Recently used', 'Settings', 'Pages', 'Actions', 'Services', 'Servers',
    'Domains', 'Databases', 'Sites', 'Cron Jobs', 'Vaults', 'Extensions', 'Docs',
];
const CATEGORY_ICONS = {
    Favorites: Star,
    'Recently used': History,
    Settings: SlidersHorizontal,
    Pages: LayoutGrid,
    Actions: Zap,
    Services: Boxes,
    Servers: Server,
    Domains: Globe,
    Databases: Database,
    Sites: Globe,
    'Cron Jobs': Clock,
    Vaults: KeyRound,
    Extensions: Puzzle,
    Docs: BookOpen,
};
const CATEGORY_WEIGHT = {
    Favorites: 5,
    Settings: 6, Pages: 4, Actions: 4, Services: 2, Servers: 2, Domains: 2,
    Databases: 2, Sites: 2, 'Cron Jobs': 1, Vaults: 1, Extensions: 1, Docs: 0,
};
// Backend /search row `type` -> palette category.
const ENTITY_CATEGORY = {
    service: 'Services', app: 'Services', server: 'Servers', domain: 'Domains',
    database: 'Databases', site: 'Sites', cron: 'Cron Jobs',
    extension: 'Extensions', plugin: 'Extensions', vault: 'Vaults',
};
// Visit/favorite entry `type` -> human sublabel.
const TYPE_LABEL = {
    service: 'Service', server: 'Server', monitor: 'Monitor',
    workspace: 'Workspace', project: 'Project', domain: 'Domain',
};

// Docs entries derived from the single docsLinks map (plan 40). Hidden under
// White Label since they point at the public serverkit.ai docs.
const DOCS_ENTRIES = [
    { key: 'deploySources', labelKey: 'palette.docs.deploySources', label: 'Docs: Deploy sources', keywords: 'deploy source repo git' },
    { key: 'manifest', labelKey: 'palette.docs.manifest', label: 'Docs: serverkit.yaml manifest', keywords: 'manifest yaml declarative' },
    { key: 'extensions', labelKey: 'palette.docs.extensions', label: 'Docs: Extensions', keywords: 'extension plugin' },
    { key: 'extensionsInstalling', labelKey: 'palette.docs.extensionsInstalling', label: 'Docs: Installing extensions', keywords: 'install extension' },
    { key: 'extensionsBuilding', labelKey: 'palette.docs.extensionsBuilding', label: 'Docs: Building extensions', keywords: 'build extension develop sdk' },
    { key: 'extensionsPublishing', labelKey: 'palette.docs.extensionsPublishing', label: 'Docs: Publishing extensions', keywords: 'publish extension registry' },
    { key: 'extensionsSecurity', labelKey: 'palette.docs.extensionsSecurity', label: 'Docs: Extension security', keywords: 'extension security permissions' },
];

const PER_GROUP_CAP = 6;
const OVERALL_CAP = 30;

// Cap results per category and overall, preserving the incoming (sorted) order.
function capGroups(items, perGroup = PER_GROUP_CAP, overall = OVERALL_CAP) {
    const counts = {};
    const out = [];
    for (const it of items) {
        const c = counts[it.category] || 0;
        if (c >= perGroup) continue;
        counts[it.category] = c + 1;
        out.push(it);
        if (out.length >= overall) break;
    }
    return out;
}

const CommandPalette = ({ open, onClose }) => {
    const { t } = useTranslation();
    const [query, setQuery] = useState('');
    const [entityItems, setEntityItems] = useState([]);
    const navigate = useNavigate();
    const { command_palette: pluginPaletteItems } = useContributions();
    const { logout } = useAuth();
    const { resolvedTheme, setTheme, whiteLabel } = useTheme();
    const { allowItem } = usePaletteAuthz();

    // Prefix modes: `>` = actions only, `?` = docs only, bare = everything.
    const { mode, term } = useMemo(() => {
        if (query.startsWith('>')) return { mode: 'actions', term: query.slice(1).trimStart() };
        if (query.startsWith('?')) return { mode: 'docs', term: query.slice(1).trimStart() };
        return { mode: 'all', term: query };
    }, [query]);

    // Reset transient state each time the palette opens/closes.
    useEffect(() => {
        if (open) setQuery('');
        else setEntityItems([]);
    }, [open]);

    // --- Sync providers ------------------------------------------------------
    const pageItems = useMemo(
        () => PALETTE_PAGES.filter(allowItem),
        [allowItem],
    );

    const settingsItems = useMemo(
        () => SETTINGS_INDEX
            .filter((s) => allowItem({ adminOnly: s.adminOnly }))
            .map((s) => ({
                id: `setting:${s.id}`,
                label: s.label,
                sublabel: s.description || '',
                keywords: `${s.keywords || ''} ${s.tab} settings`,
                path: `/settings/${s.tab}?focus=setting:${s.id}`,
                category: 'Settings',
            })),
        [allowItem],
    );

    const actionItems = useMemo(
        () => COMMAND_ACTIONS
            .filter((a) => allowItem({ adminOnly: a.adminOnly }))
            .map((a) => ({
                id: `action:${a.id}`,
                label: a.label,
                keywords: a.keywords || '',
                category: 'Actions',
                suggested: a.suggested,
                perform: a.perform,
            })),
        [allowItem],
    );

    const pluginItems = useMemo(
        () => (pluginPaletteItems || [])
            .filter((it) => it && it.label && it.path)
            .map((it) => ({
                id: `plugin:${it.path}:${it.label}`,
                label: translateLabel(t, it),
                keywords: it.keywords || '',
                path: it.path,
                category: it.category || 'Extensions',
            })),
        [pluginPaletteItems, t],
    );

    const docItems = useMemo(() => {
        if (whiteLabel?.enabled) return [];
        return DOCS_ENTRIES
            .filter((d) => DOCS_LINKS[d.key])
            .map((d) => ({
                id: `docs:${d.key}`,
                label: translateLabel(t, d),
                keywords: d.keywords || '',
                path: DOCS_LINKS[d.key],
                category: 'Docs',
                external: true,
            }));
    }, [whiteLabel, t]);

    // --- Favorites + visited entities (localStorage, refreshed per open) -----
    const favoriteItems = useMemo(
        () => (open ? getFavorites() : []).map((e) => ({
            id: `fav:${e.type}:${e.id}`,
            label: e.label,
            sublabel: TYPE_LABEL[e.type] || e.type,
            keywords: `${e.type} favorite starred`,
            path: e.path,
            category: 'Favorites',
        })),
        [open],
    );

    const visitItems = useMemo(
        () => (open ? getRecents(6) : []).map((e) => ({
            id: `visit:${e.type}:${e.id}`,
            label: e.label,
            sublabel: TYPE_LABEL[e.type] || e.type,
            keywords: `${e.type} recent visited`,
            path: e.path,
            category: 'Recently used',
        })),
        [open],
    );

    // --- Async entity provider (backend /search), debounced 200ms ------------
    useEffect(() => {
        if (!open) return undefined;
        const t = term.trim();
        if (mode !== 'all' || t.length < 2) {
            setEntityItems([]);
            return undefined;
        }
        let cancelled = false;
        const handle = setTimeout(async () => {
            try {
                const res = await api.search(t);
                if (cancelled) return;
                const rows = res?.results || [];
                setEntityItems(rows.map((r) => ({
                    id: `entity:${r.type}:${r.path}`,
                    label: r.label,
                    sublabel: r.sublabel || '',
                    path: r.path,
                    category: ENTITY_CATEGORY[r.type] || 'Results',
                })));
            } catch {
                if (!cancelled) setEntityItems([]);
            }
        }, 200);
        return () => { cancelled = true; clearTimeout(handle); };
    }, [open, term, mode]);

    // --- Results -------------------------------------------------------------
    const results = useMemo(() => {
        const t = term.trim();

        // Empty query: favorites + recent visits + frecency recents + suggested
        // actions (bare), or the full small set for a prefix mode.
        if (!t) {
            if (mode === 'actions') return capGroups(actionItems);
            if (mode === 'docs') return capGroups(docItems);
            const pool = [...settingsItems, ...pageItems, ...actionItems, ...pluginItems, ...docItems];
            const byId = new Map(pool.map((i) => [i.id, i]));
            const recents = recentIds(8)
                .map((id) => byId.get(id))
                .filter(Boolean)
                .map((i) => ({ ...i, category: 'Recently used' }));
            const base = recents.length
                ? recents
                : pageItems.slice(0, 6).map((i) => ({ ...i, category: 'Recently used' }));
            const suggestions = actionItems.filter((a) => a.suggested).slice(0, 4);
            return capGroups([
                ...favoriteItems.slice(0, 4),
                ...visitItems,
                ...base,
                ...suggestions,
            ], 8, OVERALL_CAP);
        }

        const syncPool = mode === 'actions'
            ? actionItems
            : mode === 'docs'
                ? docItems
                : [...settingsItems, ...pageItems, ...actionItems, ...pluginItems, ...docItems,
                    ...favoriteItems, ...visitItems];

        const scored = [];
        for (const item of syncPool) {
            const s = scoreItem(item, t);
            if (s < 0) continue;
            const weight = CATEGORY_WEIGHT[item.category] ?? 1;
            const frec = Math.min(frecencyScore(item.id), 10);
            scored.push({ ...item, _score: s + weight + frec });
        }
        if (mode === 'all') {
            for (const item of entityItems) {
                // Entities already matched server-side; score locally only for
                // ordering, and never drop them.
                const s = scoreItem(item, t);
                const weight = CATEGORY_WEIGHT[item.category] ?? 1;
                scored.push({ ...item, _score: (s < 0 ? 0 : s) + weight });
            }
        }
        scored.sort((a, b) => b._score - a._score);
        return capGroups(scored);
    }, [term, mode, settingsItems, pageItems, actionItems, pluginItems, docItems, entityItems]);

    // --- Selection -----------------------------------------------------------
    const handleSelect = useCallback((item) => {
        recordUse(item.id);
        onClose();
        if (typeof item.perform === 'function') {
            item.perform({
                navigate,
                logout,
                api,
                toggleTheme: () => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark'),
            });
            return;
        }
        if (item.external) {
            window.open(item.path, '_blank', 'noopener,noreferrer');
            return;
        }
        navigate(item.path);
    }, [navigate, onClose, logout, resolvedTheme, setTheme]);

    // Group + order for rendering.
    const grouped = useMemo(() => {
        const groups = {};
        for (const it of results) (groups[it.category] = groups[it.category] || []).push(it);
        return Object.keys(groups)
            .sort((a, b) => {
                const ia = GROUP_ORDER.indexOf(a);
                const ib = GROUP_ORDER.indexOf(b);
                return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
            })
            .map((k) => [k, groups[k]]);
    }, [results]);

    const placeholder = mode === 'actions'
        ? 'Run an action…'
        : mode === 'docs'
            ? 'Search docs…'
            : 'Search pages, settings, actions, services…';

    return (
        <CommandDialog
            open={open}
            shouldFilter={false}
            label={t('palette.label', 'Command palette')}
            onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}
        >
            <CommandInput
                placeholder={placeholder}
                value={query}
                onValueChange={setQuery}
            />
            <CommandList>
                <CommandEmpty>{t('common.state.noResults', 'No results found')}</CommandEmpty>
                {grouped.map(([category, items]) => {
                    const Icon = CATEGORY_ICONS[category] || LayoutGrid;
                    return (
                        <CommandGroup key={category} heading={category}>
                            {items.map((item) => (
                                <CommandItem
                                    key={item.id}
                                    value={item.id}
                                    onSelect={() => handleSelect(item)}
                                >
                                    <Icon className="command-palette__item-icon" aria-hidden="true" />
                                    <span className="command-palette__item-body">
                                        <span className="command-palette__item-label">{item.label}</span>
                                        {item.sublabel && (
                                            <span className="command-palette__item-sublabel">{item.sublabel}</span>
                                        )}
                                    </span>
                                    {item.external && (
                                        <ExternalLink className="command-palette__item-ext" aria-hidden="true" />
                                    )}
                                </CommandItem>
                            ))}
                        </CommandGroup>
                    );
                })}
            </CommandList>
            <div className="command-palette__footer">
                <span className="command-palette__hint"><kbd>↵</kbd> open</span>
                <span className="command-palette__hint"><kbd>&gt;</kbd> actions</span>
                <span className="command-palette__hint"><kbd>?</kbd> docs</span>
                <span className="command-palette__hint"><kbd>esc</kbd> close</span>
            </div>
        </CommandDialog>
    );
};

export default CommandPalette;
