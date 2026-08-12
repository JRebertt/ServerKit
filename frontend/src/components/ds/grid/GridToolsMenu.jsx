import { useState } from 'react';
import { MoreVertical, Download, RefreshCw, History, Check, Rows2, Rows3 } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { byKey, exportRows } from './fields';

// The toolbar's "⋮" — everything that is neither a filter nor a per-column
// action: export, refresh, row density, and discarding unsaved view changes.
// One button instead of four keeps the top bar the same shape on every page,
// which is the whole point of putting search there.
export function GridToolsMenu({
    cfg, columns, rows, selectedRows, viewName, noun = 'rows',
    onRefresh, onReset, onDensity, onExported,
}) {
    const [open, setOpen] = useState(false);
    const [pane, setPane] = useState('root');   // root | export
    const [scope, setScope] = useState('view');
    const [allCols, setAllCols] = useState(false);

    const map = byKey(columns);
    const set = scope === 'picked' ? selectedRows : rows;
    const exportCols = allCols ? columns : cfg.cols.map((k) => map.get(k)).filter(Boolean);

    const close = () => { setOpen(false); setPane('root'); };

    const go = (format) => {
        const n = exportRows(
            set,
            exportCols,
            format,
            (viewName || noun).toLowerCase().replace(/\s+/g, '-'),
        );
        onExported?.(n, exportCols.length, format);
        close();
    };

    return (
        <Popover
            open={open}
            onOpenChange={(o) => { setOpen(o); if (!o) setPane('root'); }}
        >
            <PopoverTrigger asChild>
                <button type="button" className="sk-gridicon" aria-label="More table options">
                    <MoreVertical size={16} />
                </button>
            </PopoverTrigger>
            <PopoverContent align="end" sideOffset={6} className="ui-popover-panel sk-gridmenu">
                {pane === 'root' ? (
                    <>
                        <button type="button" className="sk-gridmenu__opt" onClick={() => setPane('export')}>
                            <Download size={13} />Export…
                        </button>
                        {onRefresh && (
                            <button
                                type="button"
                                className="sk-gridmenu__opt"
                                onClick={() => { onRefresh(); close(); }}
                            >
                                <RefreshCw size={13} />Refresh data
                            </button>
                        )}
                        <div className="sk-gridmenu__sep" />
                        <div className="sk-gridmenu__head">Row density</div>
                        {[['cozy', 'Cozy', Rows2], ['compact', 'Compact', Rows3]].map(([value, text, Icon]) => (
                            <button
                                key={value}
                                type="button"
                                className={cn('sk-gridmenu__opt', cfg.density === value && 'is-on')}
                                onClick={() => onDensity(value)}
                            >
                                <span className="sk-gridmenu__box"><Check size={11} /></span>
                                <Icon size={13} />{text}
                            </button>
                        ))}
                        <div className="sk-gridmenu__sep" />
                        <button
                            type="button"
                            className="sk-gridmenu__opt"
                            onClick={() => { onReset(); close(); }}
                        >
                            <History size={13} />Reset view changes
                        </button>
                    </>
                ) : (
                    <>
                        <div className="sk-gridmenu__head">Export</div>
                        <button
                            type="button"
                            className={cn('sk-gridmenu__opt', scope === 'view' && 'is-on')}
                            onClick={() => setScope('view')}
                        >
                            <span className="sk-gridmenu__box"><Check size={11} /></span>
                            Rows in this view
                            <span className="sk-gridmenu__rest">{rows.length}</span>
                        </button>
                        <button
                            type="button"
                            className={cn('sk-gridmenu__opt', scope === 'picked' && 'is-on')}
                            disabled={!selectedRows.length}
                            onClick={() => setScope('picked')}
                        >
                            <span className="sk-gridmenu__box"><Check size={11} /></span>
                            Selected rows
                            <span className="sk-gridmenu__rest">{selectedRows.length}</span>
                        </button>
                        <div className="sk-gridmenu__sep" />
                        <button
                            type="button"
                            className={cn('sk-gridmenu__opt', allCols && 'is-on')}
                            onClick={() => setAllCols((v) => !v)}
                        >
                            <span className="sk-gridmenu__box"><Check size={11} /></span>
                            Include hidden fields
                            <span className="sk-gridmenu__rest">{exportCols.length}</span>
                        </button>
                        <div className="sk-gridmenu__foot">
                            <button type="button" onClick={() => go('json')}>JSON</button>
                            <button type="button" className="is-primary" onClick={() => go('csv')}>Download CSV</button>
                        </div>
                    </>
                )}
            </PopoverContent>
        </Popover>
    );
}

export default GridToolsMenu;
