import { Group } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';

// Toolbar popover for row grouping (Huly/Frappe "Group by"). Lists the
// table's groupable columns plus "No grouping"; the trigger shows the active
// grouping. Pair with DataTable's groupBy prop.
//
//   <GroupMenu columns={columns} groupBy={groupBy} onChange={setGroupBy} />
export function GroupMenu({ columns = [], groupBy = null, onChange, className }) {
    const { t } = useTranslation();
    const groupable = columns.filter((c) => c.groupable);
    if (!groupable.length) return null;

    const labelFor = (column) => (
        typeof column.header === 'string' && column.header ? column.header : column.key
    );
    const active = groupable.find((c) => c.key === groupBy);

    return (
        <Popover>
            <PopoverTrigger asChild>
                <Button
                    variant="outline"
                    size="sm"
                    className={cn('sk-filter-btn', active && 'sk-filter-btn--active', className)}
                >
                    <Group aria-hidden="true" />
                    {active ? labelFor(active) : 'Group'}
                </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="sk-tablemenu">
                <div className="sk-tablemenu__title">{t('app.groupMenu.groupBy', 'Group by')}</div>
                <div className="sk-tablemenu__list">
                    <button
                        type="button"
                        className={cn('sk-tablemenu__item', !active && 'is-on')}
                        onClick={() => onChange?.(null)}
                    >
                        {t('app.groupMenu.noGrouping', 'No grouping')}
                    </button>
                    {groupable.map((column) => (
                        <button
                            key={column.key}
                            type="button"
                            className={cn('sk-tablemenu__item', active?.key === column.key && 'is-on')}
                            onClick={() => onChange?.(column.key)}
                        >
                            {labelFor(column)}
                        </button>
                    ))}
                </div>
            </PopoverContent>
        </Popover>
    );
}

export default GroupMenu;
