import { ChevronRight, ChevronDown, Table2, Loader2, MoreHorizontal, Plus } from 'lucide-react';
import { EngineIcon } from '../icons/DatabaseBrands';
import EngineGlyph from './EngineGlyph';

// Icon per node kind / engine. Brand glyphs come from DatabaseBrands; tint comes
// from `.is-<engine>` in SCSS (the brand icons use currentColor). An engine
// installed from a template carries its catalog entry in `iconEntry`, so it can
// fall back to the template's own icon when we ship no brand glyph for it.
function NodeIcon({ node }) {
    if (node.iconEntry) return <EngineGlyph entry={node.iconEntry} size={15} />;
    if (node.kind === 'engine' || node.kind === 'database') {
        return <EngineIcon engine={node.engine} size={15} />;
    }
    if (node.kind === 'app') return <EngineIcon engine="docker" size={15} />;
    if (node.kind === 'table') return <Table2 size={14} aria-hidden="true" />;
    return <EngineIcon engine={node.engine} size={15} />;
}

const STATUS_LABEL = {
    active: 'Running',
    inactive: 'Stopped',
    missing: 'Not installed',
    installing: 'Installing',
    failed: 'Failed',
};

function matches(node, filter) {
    return !filter || node.label.toLowerCase().includes(filter.toLowerCase());
}

function TreeRow({ node, depth, expanded, childrenCache, loading, activeKey, selectedId, filter, handlers }) {
    const isOpen = expanded.has(node.id);
    const isLoading = loading.has(node.id);
    const kids = childrenCache.get(node.id);
    // Error cache entries are either the legacy 'error' sentinel or
    // `{ __error: message }` carrying a specific reason (e.g. a dead container).
    const errorMsg = kids === 'error'
        ? "Couldn't load. Right-click to retry."
        : (kids && !Array.isArray(kids) && kids.__error) || null;
    const hadError = errorMsg != null;
    const childNodes = Array.isArray(kids) ? kids : [];
    const visibleChildren = childNodes.filter((c) => c.expandable || matches(c, filter));

    return (
        <li className="dbx-tree-node" role="none">
            <div
                className={`dbx-tree-row is-${node.engine || node.kind}`
                    + (selectedId === node.id ? ' is-selected' : '')
                    + (activeKey && activeKey === node.id ? ' is-active' : '')}
                style={{ paddingLeft: `${depth * 14 + 6}px` }}
                role="treeitem"
                aria-expanded={node.expandable ? isOpen : undefined}
                aria-selected={selectedId === node.id}
                tabIndex={0}
                onClick={() => handlers.onActivate(node)}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handlers.onActivate(node); }
                    if (e.key === 'ArrowRight' && node.expandable && !isOpen) handlers.onToggle(node);
                    if (e.key === 'ArrowLeft' && node.expandable && isOpen) handlers.onToggle(node);
                }}
                onContextMenu={(e) => handlers.onContext(e, node)}
            >
                {node.expandable ? (
                    <button
                        type="button"
                        className="dbx-tree-chevron"
                        onClick={(e) => { e.stopPropagation(); handlers.onToggle(node); }}
                        aria-label={isOpen ? 'Collapse' : 'Expand'}
                        tabIndex={-1}
                    >
                        {isLoading
                            ? <Loader2 size={13} className="dbx-spin" aria-hidden="true" />
                            : isOpen ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
                    </button>
                ) : (
                    <span className="dbx-tree-chevron dbx-tree-chevron--leaf" aria-hidden="true" />
                )}

                <span className="dbx-tree-icon"><NodeIcon node={node} /></span>
                <span className="dbx-tree-label">{node.label}</span>

                {node.kind === 'database' && node.source === 'docker' && (
                    <span className="dbx-tree-source" title={node.appName ? `Docker container · ${node.appName}` : 'Docker container'}>
                        <EngineIcon engine="docker" size={11} />
                        {node.appName || 'docker'}
                    </span>
                )}

                {node.kind === 'engine' && node.status && node.status !== 'available' && (
                    <span className={`dbx-tree-status is-${node.status}`}>
                        {node.status === 'installing'
                            ? <Loader2 size={11} className="dbx-spin" aria-hidden="true" />
                            : <span className="dbx-status-dot" aria-hidden="true" />}
                        {STATUS_LABEL[node.status]}
                    </span>
                )}
                {node.kind === 'table' && node.rows != null && (
                    <span className="dbx-tree-badge">{node.rows.toLocaleString()}</span>
                )}
                {node.kind === 'database' && node.sizeText && (
                    <span className="dbx-tree-badge">{node.sizeText}</span>
                )}

                {node.canCreate && handlers.onCreateChild && (
                    <button
                        type="button"
                        className="dbx-tree-add"
                        onClick={(e) => { e.stopPropagation(); handlers.onCreateChild(node); }}
                        aria-label={`Create a database in ${node.label}`}
                        title="Create a database"
                        tabIndex={-1}
                    >
                        <Plus size={12} aria-hidden="true" />
                    </button>
                )}

                <button
                    type="button"
                    className="dbx-tree-more"
                    onClick={(e) => { e.stopPropagation(); handlers.onContext(e, node); }}
                    aria-label="Actions"
                    tabIndex={-1}
                >
                    <MoreHorizontal size={14} aria-hidden="true" />
                </button>
            </div>

            {node.expandable && isOpen && (
                <ul className="dbx-tree-children" role="group">
                    {isLoading && childNodes.length === 0 && (
                        <li className="dbx-tree-leaf-msg" style={{ paddingLeft: `${(depth + 1) * 14 + 22}px` }}>Loading…</li>
                    )}
                    {hadError && (
                        <li className="dbx-tree-leaf-msg is-error" style={{ paddingLeft: `${(depth + 1) * 14 + 22}px` }}>
                            {errorMsg}
                        </li>
                    )}
                    {!isLoading && !hadError && childNodes.length === 0 && (
                        <li className="dbx-tree-leaf-msg" style={{ paddingLeft: `${(depth + 1) * 14 + 22}px` }}>
                            {node.kind === 'database' ? 'No tables yet' : 'Empty'}
                        </li>
                    )}
                    {visibleChildren.map((child) => (
                        <TreeRow
                            key={child.id}
                            node={child}
                            depth={depth + 1}
                            expanded={expanded}
                            childrenCache={childrenCache}
                            loading={loading}
                            activeKey={activeKey}
                            selectedId={selectedId}
                            filter={filter}
                            handlers={handlers}
                        />
                    ))}
                    {!isLoading && !hadError && childNodes.length > 0 && visibleChildren.length === 0 && (
                        <li className="dbx-tree-leaf-msg" style={{ paddingLeft: `${(depth + 1) * 14 + 22}px` }}>No match</li>
                    )}
                </ul>
            )}
        </li>
    );
}

export default function SourceTree({ roots, expanded, childrenCache, loading, activeKey, selectedId, filter, handlers }) {
    return (
        <ul className="dbx-tree" role="tree" aria-label="Database sources">
            {roots.map((node) => (
                <TreeRow
                    key={node.id}
                    node={node}
                    depth={0}
                    expanded={expanded}
                    childrenCache={childrenCache}
                    loading={loading}
                    activeKey={activeKey}
                    selectedId={selectedId}
                    filter={filter}
                    handlers={handlers}
                />
            ))}
        </ul>
    );
}
