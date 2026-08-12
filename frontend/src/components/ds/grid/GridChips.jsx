import { X } from 'lucide-react';
import { byKey, columnLabel, opLabel, ruleText } from './fields';

// Active filter rules, spelled out above the grid. A filter you cannot see is
// a filter you will blame the data for — every rule gets a chip, and every chip
// can be removed on its own.
export function GridChips({ cfg, columns, onRemove, onClear, onMatchChange }) {
    const rules = cfg.filters.rules;
    if (!rules.length) return null;
    const map = byKey(columns);

    return (
        <div className="sk-gridchips">
            {rules.length > 1 && (
                <button
                    type="button"
                    className="sk-gridchip sk-gridchip--match"
                    onClick={() => onMatchChange(cfg.filters.match === 'all' ? 'any' : 'all')}
                    title="Toggle whether rows must match every condition or any one"
                >
                    match {cfg.filters.match}
                </button>
            )}
            {rules.map((rule) => {
                const column = map.get(rule.field);
                if (!column) return null;
                return (
                    <span key={rule.id} className="sk-gridchip">
                        <span className="sk-gridchip__k">{columnLabel(column)}</span>
                        <span className="sk-gridchip__op">{opLabel(column.type, rule.op)}</span>
                        <span className="sk-gridchip__v">{ruleText(rule, columns)}</span>
                        <button
                            type="button"
                            className="sk-gridchip__x"
                            onClick={() => onRemove(rule.id)}
                            aria-label={`Remove ${columnLabel(column)} filter`}
                        >
                            <X size={12} />
                        </button>
                    </span>
                );
            })}
            <button type="button" className="sk-gridchips__clear" onClick={onClear}>Clear all</button>
        </div>
    );
}

export default GridChips;
