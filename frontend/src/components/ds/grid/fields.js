// DataGrid field model + filter-rule engine.
//
// A grid column is a superset of the legacy DataTable column descriptor, so a
// column list can be moved from one to the other. The extra keys are what let
// the per-column header menu build itself:
//
//   {
//     key: 'ssl',
//     header: 'SSL',                    // plain-text label (menus need a string)
//     type: 'enum',                     // text | enum | num | bool | date
//     width: 'minmax(140px,1fr)',       // a CSS grid track, not a px number
//     value: (row) => row.ssl.state,    // raw value: sorts, filters, groups, exports
//     render: (row) => <Pill…/>,        // cell JSX (defaults to the raw value)
//     enumOrder: ['valid','expiring','none'],   // menu order for enums, else A-Z
//     unit: 'd',                        // suffix shown on numeric chips
//     quick: [{ op:'lt', value:30, label:'under 30' }],   // one-tap numeric filters
//     locked: true,                     // never hidden, never leaves slot 0
//     hideable / sortable / filterable / groupable        // explicit opt-out
//     align: 'right',
//   }
//
// `type` is the only new required-ish key: it picks the operator set and the
// filter UI. A column without one is still sortable and still renders — it just
// doesn't offer filtering.

export const FIELD_TYPES = ['text', 'enum', 'num', 'bool', 'date'];

// Operator sets per type: [op, label]. Order matters — first is the default.
export const OPS = {
    text: [
        ['contains', 'contains'],
        ['ncontains', 'does not contain'],
        ['is', 'is'],
        ['starts', 'starts with'],
    ],
    enum: [
        ['any', 'is any of'],
        ['none', 'is none of'],
    ],
    num: [
        ['lt', 'is under'],
        ['gt', 'is over'],
        ['eq', 'equals'],
    ],
    date: [
        ['before', 'is before'],
        ['after', 'is after'],
    ],
    bool: [
        ['is', 'is'],
    ],
};

export const opLabel = (type, op) => (OPS[type] || []).find(([o]) => o === op)?.[1] ?? op;

let seq = 0;
export const ruleId = () => `r${(seq += 1)}${Math.random().toString(36).slice(2, 6)}`;

// ---------------------------------------------------------------- column API

export const columnLabel = (column) => (
    typeof column?.header === 'string' && column.header ? column.header : column?.key ?? ''
);

// The raw value behind a cell. `value` is the grid name; `sortValue` is
// accepted so legacy DataTable column lists keep working unchanged.
export function fieldValue(column, row) {
    if (!column) return undefined;
    if (typeof column.value === 'function') return column.value(row);
    if (typeof column.sortValue === 'function') return column.sortValue(row);
    return row?.[column.key];
}

export const isFilterable = (c) => c?.filterable !== false && FIELD_TYPES.includes(c?.type);

// An action / chevron column: no label and nothing to sort. 31 of the app's
// 275 column descriptors are these, and a header menu on one is meaningless.
export const isDecorative = (c) => (
    !c || (typeof c.header === 'string' && c.header.trim() === '' && c.sortable !== true)
);

const ISO_DATE = /^\d{4}-\d{2}-\d{2}([T ]|$)/;

// Guess a column's filter type from the data when it doesn't declare one.
//
// This is what makes the header menu work on the ~50 tables in the app that
// were written before types existed: they get filtering for free, and a page
// that cares can override by declaring `type` explicitly. Deliberately
// conservative — an unrecognised shape stays `text`, which offers
// contains/is/starts-with and is never wrong, just less specific.
export function inferColumnType(column, rows) {
    if (column.type) return column.type;
    if (column.filterable === false || isDecorative(column)) return null;

    const sample = [];
    for (const row of rows) {
        const v = fieldValue(column, row);
        if (v != null && v !== '') sample.push(v);
        if (sample.length >= 60) break;
    }
    if (!sample.length) return 'text';

    if (sample.every((v) => typeof v === 'boolean')) return 'bool';
    if (sample.every((v) => typeof v === 'number' && Number.isFinite(v))) return 'num';
    if (sample.every((v) => v instanceof Date || (typeof v === 'string' && ISO_DATE.test(v)))) return 'date';

    if (sample.every((v) => typeof v === 'string')) {
        const distinct = new Set(sample);
        // Low-cardinality strings are statuses, kinds, owners — the things you
        // pick from a list. High-cardinality ones are names and paths, which
        // you type a fragment of. The test is "values repeat", with a hard cap
        // so a 40-value column never becomes an unusable checklist. The ratio
        // has to stay loose enough for SMALL tables: a 5-row table with 3
        // statuses is still obviously a pick-list, and a stricter ratio
        // silently downgraded every short table in the app to plain text.
        if (distinct.size <= 12 && distinct.size <= sample.length * 0.8) return 'enum';
    }
    return 'text';
}

// Column list with inferred types filled in. Memoise at the call site: it
// walks the data.
export function withInferredTypes(columns, rows) {
    return columns.map((c) => {
        const type = inferColumnType(c, rows);
        return type && type !== c.type ? { ...c, type } : c;
    });
}
export const isGroupable = (c) => (
    c?.groupable !== undefined ? !!c.groupable : c?.type === 'enum' || c?.type === 'bool'
);
export const isSortable = (c) => c?.sortable !== false;
export const isHideable = (c) => c?.hideable !== false && !c?.locked;

export const byKey = (columns) => {
    const map = new Map();
    for (const c of columns || []) map.set(c.key, c);
    return map;
};

// ---------------------------------------------------------------- rule engine

const asText = (v) => String(v ?? '').toLowerCase();
const asTime = (v) => {
    if (v == null || v === '') return null;
    const t = v instanceof Date ? v.getTime() : new Date(v).getTime();
    return Number.isNaN(t) ? null : t;
};

export function ruleMatches(row, rule, columns) {
    const column = columns.get(rule.field);
    if (!column) return true;
    const value = fieldValue(column, row);

    switch (rule.op) {
        case 'contains': return asText(value).includes(asText(rule.value));
        case 'ncontains': return !asText(value).includes(asText(rule.value));
        case 'starts': return asText(value).startsWith(asText(rule.value));
        case 'is':
            return column.type === 'bool'
                ? !!value === (rule.value === true || rule.value === 'true')
                : asText(value) === asText(rule.value);
        case 'any': return !rule.value?.length || rule.value.includes(String(value));
        case 'none': return !rule.value?.length || !rule.value.includes(String(value));
        case 'lt': return Number(value) < Number(rule.value);
        case 'gt': return Number(value) > Number(rule.value);
        case 'eq': return Number(value) === Number(rule.value);
        case 'before': {
            const a = asTime(value); const b = asTime(rule.value);
            return a != null && b != null && a < b;
        }
        case 'after': {
            const a = asTime(value); const b = asTime(rule.value);
            return a != null && b != null && a > b;
        }
        default: return true;
    }
}

// A rule with no value yet (a half-typed condition) must not filter anything
// out — otherwise the table blanks the moment you add a condition row.
export const ruleIsArmed = (rule) => !!rule?.field && !!rule?.op && (
    Array.isArray(rule.value) ? rule.value.length > 0 : rule.value !== '' && rule.value != null
);

export function applyFilters(rows, filters, columns) {
    const armed = (filters?.rules || []).filter(ruleIsArmed);
    if (!armed.length) return rows;
    const map = byKey(columns);
    const test = filters.match === 'any'
        ? (row) => armed.some((r) => ruleMatches(row, r, map))
        : (row) => armed.every((r) => ruleMatches(row, r, map));
    return rows.filter(test);
}

// Short human text for a filter chip: "valid, expiring +2", "30d", "on".
export function ruleText(rule, columns) {
    const column = byKey(columns).get(rule.field);
    if (!column) return '';
    if (column.type === 'bool') return rule.value === true || rule.value === 'true' ? 'on' : 'off';
    if (Array.isArray(rule.value)) {
        return rule.value.length > 2
            ? `${rule.value.slice(0, 2).join(', ')} +${rule.value.length - 2}`
            : rule.value.join(', ');
    }
    return String(rule.value) + (column.type === 'num' && column.unit ? column.unit : '');
}

// The blank value a freshly added rule of this type should start from.
export function emptyValueFor(type) {
    if (type === 'enum') return [];
    if (type === 'bool') return true;
    if (type === 'num') return '';
    return '';
}

export function coerceValue(type, raw) {
    if (type === 'num') return raw === '' ? '' : Number(raw);
    if (type === 'bool') return raw === true || raw === 'true';
    return raw;
}

// ---------------------------------------------------------------- sort / group

export function applySort(rows, sort, columns) {
    if (!sort?.key) return rows;
    const column = byKey(columns).get(sort.key);
    if (!column) return rows;
    const dir = sort.dir === 'desc' ? -1 : 1;
    const numeric = column.type === 'num';
    const temporal = column.type === 'date';

    return [...rows].sort((a, b) => {
        const av = fieldValue(column, a);
        const bv = fieldValue(column, b);
        // Nulls always sink, regardless of direction — an empty cell is never
        // "the most urgent row" just because you flipped the arrow.
        const aNull = av == null || av === '';
        const bNull = bv == null || bv === '';
        if (aNull && bNull) return 0;
        if (aNull) return 1;
        if (bNull) return -1;
        if (numeric) return (Number(av) - Number(bv)) * dir;
        if (temporal) return ((asTime(av) ?? 0) - (asTime(bv) ?? 0)) * dir;
        return String(av).localeCompare(String(bv)) * dir;
    });
}

export function groupRows(rows, groupKey, columns) {
    if (!groupKey) return [[null, rows]];
    const column = byKey(columns).get(groupKey);
    if (!column) return [[null, rows]];
    const buckets = new Map();
    for (const row of rows) {
        const raw = fieldValue(column, row);
        const label = column.type === 'bool'
            ? (raw ? 'on' : 'off')
            : String(raw ?? '—');
        if (!buckets.has(label)) buckets.set(label, []);
        buckets.get(label).push(row);
    }
    return [...buckets.entries()];
}

// Distinct values of an enum/bool column with row counts — powers the
// checkbox list in the column menu.
export function valueCounts(rows, column) {
    const counts = new Map();
    for (const row of rows) {
        const key = String(fieldValue(column, row));
        counts.set(key, (counts.get(key) || 0) + 1);
    }
    return counts;
}

export function optionsFor(rows, column) {
    if (column.type === 'bool') return ['true', 'false'];
    if (column.enumOrder) return column.enumOrder;
    return [...valueCounts(rows, column).keys()].sort();
}

// ---------------------------------------------------------------- export

function exportCell(column, row) {
    const value = fieldValue(column, row);
    if (column.type === 'bool') return value ? 'yes' : 'no';
    return value == null ? '' : String(value);
}

const csvEscape = (s) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);

export function exportRows(rows, columns, format, filename) {
    let body; let mime; let ext;
    if (format === 'json') {
        body = JSON.stringify(
            rows.map((row) => Object.fromEntries(columns.map((c) => [c.key, fieldValue(c, row)]))),
            null,
            2,
        );
        mime = 'application/json';
        ext = 'json';
    } else {
        body = [
            columns.map((c) => csvEscape(columnLabel(c))).join(','),
            ...rows.map((row) => columns.map((c) => csvEscape(exportCell(c, row))).join(',')),
        ].join('\n');
        mime = 'text/csv';
        ext = 'csv';
    }
    const url = URL.createObjectURL(new Blob([body], { type: mime }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `${filename || 'export'}.${ext}`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    return rows.length;
}
