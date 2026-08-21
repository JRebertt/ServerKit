import { ArrowUp, ArrowDown, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';
import { translateLabel } from '../../i18n/labels';

// Active-sort chip bar (Twenty's EditableSortChip pattern). Renders one chip
// per sort level above the table: click the chip body to flip direction, ✕ to
// remove the level, "Reset" clears all. Collapses to nothing when no sort is
// active — the bar never sits empty.
//
//   const { sorts, setSorts } = useTableSort();
//   <SortChipBar columns={columns} sorts={sorts} onChange={setSorts} />
export function SortChipBar({ columns = [], sorts = [], onChange, className }) {
    const { t } = useTranslation();
    if (!sorts.length) return null;

    const labelFor = (key) => {
        const column = columns.find((c) => c.key === key);
        if (!column) return key;
        return typeof column.header === 'string' && column.header ? translateLabel(t, column, 'header') : column.key;
    };

    const flip = (key) => onChange?.(
        sorts.map((s) => (s.key === key
            ? { ...s, direction: s.direction === 'asc' ? 'desc' : 'asc' }
            : s)),
    );
    const remove = (key) => onChange?.(sorts.filter((s) => s.key !== key));

    return (
        <div className={cn('sk-sortchips', className)} role="list" aria-label={t('app.sortChipBar.activeSorting', 'Active sorting')}>
            {sorts.map((sort, index) => (
                <span key={sort.key} className="sk-sortchips__chip" role="listitem">
                    {sorts.length > 1 && (
                        <span className="sk-sortchips__priority">{index + 1}</span>
                    )}
                    <button
                        type="button"
                        className="sk-sortchips__body"
                        onClick={() => flip(sort.key)}
                        title={t('app.sortChipBar.clickToFlipDirection', 'Click to flip direction')}
                    >
                        <span className="sk-sortchips__label">{labelFor(sort.key)}</span>
                        {sort.direction === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
                    </button>
                    <button
                        type="button"
                        className="sk-sortchips__remove"
                        onClick={() => remove(sort.key)}
                        aria-label={t('app.sortChipBar.removeSortOn', 'Remove sort on {{value}}', { value: labelFor(sort.key) })}
                    >
                        <X size={12} />
                    </button>
                </span>
            ))}
            <button
                type="button"
                className="sk-sortchips__reset"
                onClick={() => onChange?.([])}
            >
                {t('app.sortChipBar.reset', 'Reset')}
            </button>
        </div>
    );
}

export default SortChipBar;
