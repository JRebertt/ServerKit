import { useNavigate } from 'react-router-dom';
import { Globe, Plus } from 'lucide-react';
import { ServiceTile, Pill, DataTable, DataTableFooter, serviceStatusKind } from '@/components/ds';
import {
    useTableChrome, GridViewPicker, GridChips, GridFilterButton,
    GridToolsMenu, GridFilterDrawer,
} from '@/components/ds/grid';
import { useTableSort } from '@/hooks/useTableSort';
import { useColumnVisibility } from '@/hooks/useColumnVisibility';
import { Button } from '@/components/ui/button';
import EmptyState from '../EmptyState';

// What the Status cell shows when the row carries none. A real word, not '':
// `ruleIsArmed` drops any rule whose value is empty.
const UNKNOWN = 'unknown';

const NO_RULES = { match: 'all', rules: [] };
const BY_NAME = [{ key: 'name', direction: 'asc' }];

// Built-in saved views. Every row here is already a WordPress app, so the axis
// left is whether the site is actually serving.
const WORKSPACE_SITE_VIEWS = [
    {
        name: 'All sites',
        state: { sorts: BY_NAME, hiddenKeys: [], columnFilters: NO_RULES },
    },
    {
        // Stated as "not running" rather than as a list of bad statuses, so
        // 'error', 'deploying' and anything new all land here.
        name: 'Not running',
        state: {
            sorts: BY_NAME,
            hiddenKeys: [],
            columnFilters: {
                match: 'all',
                rules: [{ id: 'wsi1', field: 'status', op: 'none', value: ['running'] }],
            },
        },
    },
];

const WorkspaceSitesTab = ({ wsId, sites, appsOut, onMoveApp, onShare }) => {
    const navigate = useNavigate();
    const { sorts, setSorts } = useTableSort({ storageKey: 'serverkit-table-ws-sites-sort' });
    const {
        hiddenKeys, setHiddenKeys,
    } = useColumnVisibility({ storageKey: 'serverkit-table-ws-sites-cols' });

    // DataTable columns. Cell markup and classNames are unchanged, so the
    // shared .sk-cell-name / .sk-cell-sub rules keep applying.
    const columns = [
        {
            key: 'name',
            header: 'Site',
            sortable: true,
            hideable: false,
            type: 'text',
            value: (a) => a.name || '',
            sortValue: (a) => a.name || '',
            render: (a) => (
                <div className="sk-cell-name">
                    <ServiceTile name={a.name} size={30} />
                    <div>
                        <div>{a.name}</div>
                        <div className="sk-cell-sub">{a.app_type}{a.domain ? ` · ${a.domain}` : ''}</div>
                    </div>
                </div>
            ),
        },
        {
            key: 'status',
            header: 'Status',
            sortable: true,
            // Declared, not inferred: a workspace holding two sites of two
            // statuses fails the enum cardinality test and would fall back to
            // text, turning the pick-list into a typed fragment and the view
            // above into a no-op. No `enumOrder` — the options come from the
            // data, which is the only source that agrees with itself here.
            type: 'enum',
            value: (a) => a.status || UNKNOWN,
            sortValue: (a) => a.status || UNKNOWN,
            render: (a) => <Pill kind={serviceStatusKind(a.status)}>{a.status || UNKNOWN}</Pill>,
        },
        {
            key: 'actions',
            header: '',
            width: 220,
            sortable: false,
            hideable: false,
            render: (a) => (
                <div className="ws-detail__rowactions" onClick={e => e.stopPropagation()}>
                    <Button size="sm" variant="outline" onClick={() => onShare(a)}>Share</Button>
                    <Button size="sm" variant="destructive" onClick={() => onMoveApp(a.id, null)}>Remove</Button>
                </div>
            ),
        },
    ];

    // One ROUTE renders four of these tabs, so each carries its own view
    // namespace and its own `urlScope` — without the scope they would all write
    // `?view=`/`?sort=` and a link saved on Sites would reopen on Services.
    const chrome = useTableChrome({
        columns,
        rows: sites,
        viewPageKey: 'workspace-sites',
        builtinViews: WORKSPACE_SITE_VIEWS,
        noun: 'sites',
        sorts,
        setSorts,
        hiddenKeys,
        setHiddenKeys,
        urlScope: 'sites',
    });

    return (
        <>
            {/* Inline chrome, not hoisted: this is a tab inside a detail page
                that already owns the top bar, so hoisting would hijack it. */}
            <GridViewPicker
                views={chrome.views}
                label="sites"
                onCreate={chrome.createView}
                actions={(
                    <>
                        <GridFilterButton
                            count={chrome.filterCount}
                            onClick={() => chrome.setDrawerOpen(true)}
                        />
                        <GridToolsMenu {...chrome.toolsProps} />
                    </>
                )}
            />

            <GridChips {...chrome.chipProps} />

            <DataTable
                columns={chrome.columns}
                data={sites}
                keyField="id"
                sorts={sorts}
                onSortsChange={setSorts}
                {...chrome.tableProps}
                onRowClick={(a) => navigate(`/services/${a.id}`)}
                className="ws-detail__tablecard"
                emptyState={(
                    <EmptyState icon={Globe} title="No sites in this workspace yet" description="Move one in below." />
                )}
                footer={(
                    <DataTableFooter
                        shown={chrome.shownCount}
                        total={sites.length}
                        noun="site"
                    />
                )}
            />

            <GridFilterDrawer {...chrome.drawerProps} />

            {appsOut.length > 0 && (
                <>
                    <div className="ws-pick-label">Move a site into this workspace</div>
                    <div className="ws-pick">
                        {appsOut.map(a => (
                            <div key={a.id} className="ws-pick__item" onClick={() => onMoveApp(a.id, wsId)}>
                                <ServiceTile name={a.name} size={28} className="ws-pick__tile" />
                                <span className="ws-pick__name">{a.name}</span>
                                <span className="sk-tag">{a.app_type}</span>
                                <Plus size={16} className="ws-pick__plus" />
                            </div>
                        ))}
                    </div>
                </>
            )}
        </>
    );
};

export default WorkspaceSitesTab;
