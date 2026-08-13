import { Columns3, Eye, EyeOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

// Toolbar popover for column show/hide (datatables.net "column visibility"
// button). Lists every hideable column with an eye toggle; the trigger shows
// how many columns are currently hidden. Pair with useColumnVisibility and
// pass the same hiddenKeys to DataTable.
//
//   const { hiddenKeys, toggleColumn, showAllColumns } = useColumnVisibility();
//   <ColumnsMenu columns={columns} hiddenKeys={hiddenKeys}
//     onToggle={toggleColumn} onShowAll={showAllColumns} />
export function ColumnsMenu({ columns = [], hiddenKeys = [], onToggle, onShowAll, className }) {
    const hideable = columns.filter((c) => c.hideable !== false);
    const labelFor = (column) => (
        typeof column.header === 'string' && column.header ? column.header : column.key
    );

    return (
        <Popover>
            <PopoverTrigger asChild>
                <Button
                    variant="outline"
                    size="sm"
                    className={cn('sk-filter-btn', hiddenKeys.length > 0 && 'sk-filter-btn--active', className)}
                >
                    <Columns3 aria-hidden="true" />
                    Columns
                    {hiddenKeys.length > 0 && <span className="sk-filter-btn__badge">{hiddenKeys.length}</span>}
                </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="sk-tablemenu">
                <div className="sk-tablemenu__title">Toggle columns</div>
                <div className="sk-tablemenu__list">
                    {hideable.map((column) => {
                        const hidden = hiddenKeys.includes(column.key);
                        return (
                            <button
                                key={column.key}
                                type="button"
                                className={cn('sk-tablemenu__item', 'sk-tablemenu__item--toggle', hidden && 'is-off')}
                                onClick={() => onToggle?.(column.key)}
                                aria-pressed={!hidden}
                            >
                                {hidden ? <EyeOff size={13} /> : <Eye size={13} />}
                                {labelFor(column)}
                            </button>
                        );
                    })}
                </div>
                <div className="sk-tablemenu__footer">
                    <Button variant="ghost" size="sm" onClick={onShowAll} disabled={hiddenKeys.length === 0}>
                        Show all
                    </Button>
                </div>
            </PopoverContent>
        </Popover>
    );
}

export default ColumnsMenu;
