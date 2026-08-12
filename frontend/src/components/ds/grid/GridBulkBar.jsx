import { X } from 'lucide-react';

// The selection bar. Appears only when rows are picked, and holds the actions
// that only make sense in bulk — so the per-row menu doesn't have to carry
// "…and 40 others" variants of everything.
//
//   <GridBulkBar count={picked.length} noun="domain" onClear={…}>
//       <button onClick={…}><RefreshCw size={13}/> Check DNS</button>
//       <button className="is-danger" onClick={…}><Trash2 size={13}/> Remove</button>
//   </GridBulkBar>
export function GridBulkBar({ count, noun = 'row', onClear, children }) {
    if (!count) return null;
    return (
        <div className="sk-gridbulk">
            <span className="sk-gridbulk__count">{count}</span>
            <span className="sk-gridbulk__label">{noun}{count === 1 ? '' : 's'} selected</span>
            <div className="sk-gridbulk__acts">{children}</div>
            <button type="button" className="sk-gridbulk__clear" onClick={onClear}>
                <X size={13} /> Clear
            </button>
        </div>
    );
}

export default GridBulkBar;
