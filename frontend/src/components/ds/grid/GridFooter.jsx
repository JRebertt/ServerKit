import { ChevronDown, ChevronsLeft, ChevronsRight, ChevronLeft, ChevronRight } from 'lucide-react';
import { byKey, columnLabel } from './fields';

// Footer: what you are looking at on the left, how to page through it on the
// right. The sort/group summary is here rather than in a toolbar chip because
// it answers a question you only ask while reading the rows.
export function GridFooter({
    from, to, total, noun = 'rows', cfg, columns,
    page, pageCount, perPage, onPage, onPerPage,
}) {
    const map = byKey(columns);
    const sortCol = cfg.sort.key ? map.get(cfg.sort.key) : null;
    const groupCol = cfg.group ? map.get(cfg.group) : null;

    return (
        <div className="sk-gridfoot">
            <span>{total ? `${from}–${to} of ${total}` : '0'} {noun}</span>
            {sortCol && (
                <>
                    <span>·</span>
                    <span>sorted by {columnLabel(sortCol)} {cfg.sort.dir === 'asc' ? '↑' : '↓'}</span>
                </>
            )}
            {groupCol && (
                <>
                    <span>·</span>
                    <span>grouped by {columnLabel(groupCol)}</span>
                </>
            )}
            <span className="sk-gridfoot__sp" />
            <div className="sk-gridpager">
                <span className="sk-gridpager__label">Rows</span>
                <div className="sk-gridpager__sel">
                    <select
                        value={perPage}
                        onChange={(e) => onPerPage(e.target.value === 'all' ? 'all' : Number(e.target.value))}
                        aria-label="Rows per page"
                    >
                        {[10, 25, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}
                        <option value="all">All</option>
                    </select>
                    <ChevronDown size={12} />
                </div>
                <button type="button" disabled={page <= 1} onClick={() => onPage(1)} aria-label="First page">
                    <ChevronsLeft size={13} />
                </button>
                <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
                    <ChevronLeft size={14} />
                </button>
                <span className="sk-gridpager__pos">{page} / {pageCount}</span>
                <button type="button" disabled={page >= pageCount} onClick={() => onPage(page + 1)} aria-label="Next page">
                    <ChevronRight size={14} />
                </button>
                <button type="button" disabled={page >= pageCount} onClick={() => onPage(pageCount)} aria-label="Last page">
                    <ChevronsRight size={13} />
                </button>
            </div>
        </div>
    );
}

export default GridFooter;
