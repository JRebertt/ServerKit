import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

// The selection bar: one component, one place on screen. Appears only when rows
// are picked, and holds the actions that only make sense in bulk — so the
// per-row menu doesn't have to carry "…and 40 others" variants of everything.
//
//   <GridBulkBar count={picked.length} noun="domain" onClear={…}>
//       <button onClick={…}><RefreshCw size={13}/> Check DNS</button>
//       <button className="is-danger" onClick={…}><Trash2 size={13}/> Remove</button>
//   </GridBulkBar>
//
// It floats at the bottom of the viewport rather than sitting inline above the
// table. Two reasons. It does not reflow the rows you are in the middle of
// picking — an inline bar pushed the whole table down the moment you ticked the
// first checkbox, moving the next row out from under the cursor. And it stays
// put while you scroll a long list, so the actions are reachable from row 400
// without scrolling back to the top.
//
// This used to exist twice: this component rendering inline at the top of the
// list, and a hand-rolled copy inside ResourceListPage floating at the bottom.
// Same feature, two places, two behaviours depending on which page you were on.
export function GridBulkBar({ count, noun = 'row', onClear, children }) {
    const { t } = useTranslation();
    if (!count) return null;
    return (
        <div className="sk-bulkbar" role="status">
            <span className="sk-bulkbar__count">
                {count} {noun}{count === 1 ? '' : 's'} selected
            </span>
            <div className="sk-bulkbar__actions">{children}</div>
            {onClear && (
                <button
                    type="button"
                    className="sk-bulkbar__clear"
                    onClick={onClear}
                    aria-label={t('app.gridBulkBar.clearSelection', 'Clear selection')}
                >
                    <X size={14} />
                </button>
            )}
        </div>
    );
}

export default GridBulkBar;
