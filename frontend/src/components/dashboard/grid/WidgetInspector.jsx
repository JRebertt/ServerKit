import { useEffect, useMemo } from 'react';
import {
    Copy, LayoutGrid, Minus, Plus, Trash2, X,
} from 'lucide-react';
import { SegControl } from '@/components/ds';
import { Switch } from '@/components/ui/switch';
import {
    AGGREGATIONS, getMetric, metricsForResource, metricsForSource,
} from '../widgets/metrics';
// Single source of truth for shortcut targets: what a user can pick here is
// exactly what the renderer can draw.
import { QUICK_ACTION_OPTIONS } from '../widgets/renderers';
import { GRID_COLS } from './layout';

// Tallest a widget may be dragged/stepped to. Twelve columns wide is the board;
// height is only bounded so a stepper can't run away.
const MAX_ROWS = 20;
const FALLBACK_MIN = [2, 2];
// Log widgets count lines, everything else counts rows — different granularity.
const LINE_STEP = 20;
const LINE_MIN = 20;
const ROW_MIN = 2;


const TABLE_SOURCES = [
    ['services', 'Services'],
    ['servers', 'Servers'],
    ['containers', 'Containers'],
    ['deploys', 'Deploys'],
];
const TOPN_DIMENSIONS = [['servers', 'Servers'], ['services', 'Services']];
const LOG_LEVELS = [['all', 'All'], ['out', 'Info'], ['warn', 'Warn'], ['err', 'Error']];
const SEVERITIES = [['all', 'All'], ['critical', 'Critical'], ['high', 'High'], ['low', 'Low']];

const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const toOptions = (pairs) => pairs.map(([value, label]) => ({ value, label }));

// A metric saved before the resource changed is kept in the list, flagged,
// rather than silently swapped out from under the operator.
function asOptions(catalog, selected) {
    const options = catalog.map((metric) => [metric.id, metric.label]);
    if (selected && !catalog.some((metric) => metric.id === selected)) {
        options.push([selected, `${getMetric(selected).label} · unavailable here`]);
    }
    return options;
}

/**
 * Metric dropdown options for a resource. metrics.js is explicit that config
 * UIs must build this from the resource's own catalog, so a dead option
 * (network on the local host, load average on an agent) never reaches a user.
 * The `$server` variable can resolve either way, so it gets the union.
 */
function metricOptionsFor(resource, selected) {
    const catalog = !resource || resource === '$server'
        ? [...new Set([...metricsForSource('local'), ...metricsForSource('server')])]
        : metricsForResource(resource);
    return asOptions(catalog, selected);
}

/** Top N ranks servers/services, never the panel host. */
function topnMetricOptions(selected) {
    return asOptions(metricsForSource('server'), selected);
}

const iconOf = (type) => {
    const candidate = type?.icon;
    const usable = typeof candidate === 'function' || (candidate && typeof candidate === 'object');
    return usable ? candidate : LayoutGrid;
};

// The stylesheet targets `.skw-ins__row > label`, so the caption stays a bare
// <label> element.
function InspectorRow({ label, hint, children }) {
    return (
        <div className="skw-ins__row">
            <label>{label}</label>
            {children}
            {hint && <div className="skw-ins__hint">{hint}</div>}
        </div>
    );
}

function InspectorSelect({ value, onChange, options, label }) {
    return (
        <select
            className="skw-ins__select"
            value={value}
            aria-label={label}
            onChange={(event) => onChange(event.target.value)}
        >
            {options.map(([optionValue, optionLabel]) => (
                <option key={optionValue} value={optionValue}>{optionLabel}</option>
            ))}
        </select>
    );
}

// `.skw-stepper` styles its `button`/`span` children directly.
function Stepper({ label, value, onStep, suffix }) {
    return (
        <div className="skw-stepper">
            <button
                type="button"
                title={`Decrease ${label}`}
                aria-label={`Decrease ${label}`}
                onClick={() => onStep(-1)}
            >
                <Minus size={13} />
            </button>
            <span className="mono">{value}{suffix ? ` ${suffix}` : ''}</span>
            <button
                type="button"
                title={`Increase ${label}`}
                aria-label={`Increase ${label}`}
                onClick={() => onStep(1)}
            >
                <Plus size={13} />
            </button>
        </div>
    );
}

/**
 * Right-hand configuration panel for the selected widget. Every field writes
 * straight through `onChange` with a whole new widget instance — the board owns
 * the list and decides when to persist.
 */
export function WidgetInspector({
    widget,
    type,
    resources = [],
    onChange,
    onClose,
    onDuplicate,
    onRemove,
}) {
    useEffect(() => {
        const onKeyDown = (event) => { if (event.key === 'Escape') onClose?.(); };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [onClose]);

    const resourceOptions = useMemo(() => [
        ['$server', 'Dashboard variable'],
        ...resources.map((resource) => [
            resource.id,
            resource.kind ? `${resource.label} · ${resource.kind}` : resource.label,
        ]),
    ], [resources]);

    if (!widget) return null;

    const cfg = widget.cfg || {};
    const kind = widget.type;
    const [minW, minH] = type?.min || FALLBACK_MIN;
    const Icon = iconOf(type);

    const set = (key, value) => onChange?.({ ...widget, cfg: { ...cfg, [key]: value } });
    const setSeries = (index, key, value) => set(
        'series',
        (cfg.series || []).map((series, i) => (i === index ? { ...series, [key]: value } : series)),
    );
    const stepSize = (key, delta) => {
        const min = key === 'w' ? minW : minH;
        const max = key === 'w' ? GRID_COLS : MAX_ROWS;
        onChange?.({ ...widget, [key]: clamp((widget[key] || min) + delta, min, max) });
    };

    const countsLines = kind === 'logs';
    const countKey = countsLines ? 'lines' : 'limit';
    const countValue = countsLines ? (cfg.lines || 60) : (cfg.limit || 6);
    const stepCount = (direction) => {
        const step = countsLines ? LINE_STEP : 1;
        const floor = countsLines ? LINE_MIN : ROW_MIN;
        set(countKey, Math.max(floor, countValue + step * direction));
    };

    return (
        <aside className="skw-ins" aria-label="Widget settings">
            <div className="skw-ins__head">
                <span className="skw-ins__ic"><Icon size={15} aria-hidden="true" /></span>
                <div className="skw-ins__title">
                    {cfg.title || type?.name || kind}
                    <div className="skw-ins__sub mono">{type?.name || kind} · {widget.w}×{widget.h}</div>
                </div>
                <button
                    type="button"
                    className="skw-iconbtn skw-iconbtn--bare"
                    title="Close widget settings"
                    aria-label="Close widget settings"
                    onClick={onClose}
                >
                    <X size={17} />
                </button>
            </div>

            <div className="skw-ins__body">
                <InspectorRow label="Title">
                    <div className="skw-ins__field">
                        <input
                            type="text"
                            aria-label="Widget title"
                            value={cfg.title || ''}
                            onChange={(event) => set('title', event.target.value)}
                        />
                    </div>
                </InspectorRow>

                {['stat', 'gauge', 'specs'].includes(kind) && (
                    <InspectorRow label="Resource">
                        <InspectorSelect
                            label="Resource"
                            value={cfg.resource || '$server'}
                            onChange={(value) => set('resource', value)}
                            options={resourceOptions}
                        />
                    </InspectorRow>
                )}

                {['stat', 'gauge'].includes(kind) && (
                    <InspectorRow label="Metric">
                        <InspectorSelect
                            label="Metric"
                            value={cfg.metric || 'cpu'}
                            onChange={(value) => set('metric', value)}
                            options={metricOptionsFor(cfg.resource, cfg.metric || 'cpu')}
                        />
                    </InspectorRow>
                )}

                {['stat', 'gauge', 'topn'].includes(kind) && (
                    <InspectorRow label="Aggregation">
                        <SegControl
                            options={toOptions(AGGREGATIONS)}
                            value={cfg.agg || 'last'}
                            onChange={(value) => set('agg', value)}
                        />
                    </InspectorRow>
                )}

                {['stat', 'gauge'].includes(kind) && (
                    <InspectorRow label="Thresholds" hint="Value colours turn amber, then red.">
                        <div className="skw-ins__pair">
                            {[0, 1].map((index) => (
                                <div className="skw-ins__field" key={index}>
                                    <span className="skw-ins__prefix mono">{index ? 'red ≥' : 'amber ≥'}</span>
                                    <input
                                        type="number"
                                        aria-label={index ? 'Red threshold' : 'Amber threshold'}
                                        value={(cfg.thresholds || [])[index] ?? ''}
                                        onChange={(event) => {
                                            const next = [...(cfg.thresholds || [null, null])];
                                            next[index] = event.target.value === '' ? null : Number(event.target.value);
                                            set('thresholds', next);
                                        }}
                                    />
                                </div>
                            ))}
                        </div>
                    </InspectorRow>
                )}

                {kind === 'stat' && (
                    <InspectorRow label="Sparkline">
                        <Switch
                            checked={cfg.spark !== false}
                            aria-label="Show sparkline"
                            onCheckedChange={(checked) => set('spark', checked)}
                        />
                    </InspectorRow>
                )}

                {kind === 'timeseries' && (
                    <>
                        <InspectorRow label="Series">
                            <div className="skw-ins__series">
                                {(cfg.series || []).map((series, index) => (
                                    <div className="skw-ins__ser" key={index}>
                                        <InspectorSelect
                                            label={`Series ${index + 1} resource`}
                                            value={series.resource}
                                            onChange={(value) => setSeries(index, 'resource', value)}
                                            options={resourceOptions}
                                        />
                                        <InspectorSelect
                                            label={`Series ${index + 1} metric`}
                                            value={series.metric}
                                            onChange={(value) => setSeries(index, 'metric', value)}
                                            options={metricOptionsFor(series.resource, series.metric)}
                                        />
                                        <button
                                            type="button"
                                            className="skw-iconbtn skw-iconbtn--bare"
                                            title={`Remove series ${index + 1}`}
                                            aria-label={`Remove series ${index + 1}`}
                                            onClick={() => set('series', (cfg.series || []).filter((_, i) => i !== index))}
                                        >
                                            <Trash2 size={13} />
                                        </button>
                                    </div>
                                ))}
                                <button
                                    type="button"
                                    className="skw-ins__add"
                                    onClick={() => set('series', [...(cfg.series || []), { resource: '$server', metric: 'cpu' }])}
                                >
                                    <Plus size={12} aria-hidden="true" /> Add series
                                </button>
                            </div>
                        </InspectorRow>
                        <InspectorRow label="Legend">
                            <Switch
                                checked={cfg.legend !== false}
                                aria-label="Show legend"
                                onCheckedChange={(checked) => set('legend', checked)}
                            />
                        </InspectorRow>
                        <InspectorRow label="Area fill">
                            <Switch
                                checked={cfg.fill !== false}
                                aria-label="Fill the area under each series"
                                onCheckedChange={(checked) => set('fill', checked)}
                            />
                        </InspectorRow>
                    </>
                )}

                {kind === 'topn' && (
                    <>
                        <InspectorRow label="Dimension">
                            <SegControl
                                options={toOptions(TOPN_DIMENSIONS)}
                                value={cfg.dim || 'servers'}
                                onChange={(value) => set('dim', value)}
                            />
                        </InspectorRow>
                        {/* Top N always ranks remote resources, so it offers the
                            server-side catalog whatever the board variable is. */}
                        <InspectorRow label="Metric">
                            <InspectorSelect
                                label="Metric"
                                value={cfg.metric || 'cpu'}
                                onChange={(value) => set('metric', value)}
                                options={topnMetricOptions(cfg.metric || 'cpu')}
                            />
                        </InspectorRow>
                    </>
                )}

                {kind === 'table' && (
                    <InspectorRow label="Source">
                        <InspectorSelect
                            label="Source"
                            value={cfg.source || 'services'}
                            onChange={(value) => set('source', value)}
                            options={TABLE_SOURCES}
                        />
                    </InspectorRow>
                )}

                {kind === 'logs' && (
                    <>
                        <InspectorRow label="Source">
                            <InspectorSelect
                                label="Log source"
                                value={cfg.source || '$server'}
                                onChange={(value) => set('source', value)}
                                options={resourceOptions}
                            />
                        </InspectorRow>
                        <InspectorRow label="Level">
                            <SegControl
                                options={toOptions(LOG_LEVELS)}
                                value={cfg.level || 'all'}
                                onChange={(value) => set('level', value)}
                            />
                        </InspectorRow>
                    </>
                )}

                {kind === 'alerts' && (
                    <InspectorRow label="Severity">
                        <SegControl
                            options={toOptions(SEVERITIES)}
                            value={cfg.severity || 'all'}
                            onChange={(value) => set('severity', value)}
                        />
                    </InspectorRow>
                )}

                {['table', 'logs', 'deploys', 'feed'].includes(kind) && (
                    <InspectorRow label={countsLines ? 'Lines' : 'Rows'}>
                        <Stepper
                            label={countsLines ? 'lines' : 'rows'}
                            value={countValue}
                            onStep={stepCount}
                        />
                    </InspectorRow>
                )}

                {kind === 'actions' && (
                    <InspectorRow label="Shortcuts">
                        <div className="skw-ins__checks">
                            {QUICK_ACTION_OPTIONS.map(([key, label]) => {
                                const on = (cfg.items || []).includes(key);
                                return (
                                    <label className="skw-ins__check" key={key}>
                                        <input
                                            type="checkbox"
                                            checked={on}
                                            onChange={() => set(
                                                'items',
                                                on
                                                    ? (cfg.items || []).filter((item) => item !== key)
                                                    : [...(cfg.items || []), key],
                                            )}
                                        />
                                        {label}
                                    </label>
                                );
                            })}
                        </div>
                    </InspectorRow>
                )}

                {kind === 'note' && (
                    <InspectorRow label="Text" hint="**bold** and `code` are supported.">
                        <textarea
                            className="skw-ins__textarea"
                            aria-label="Note text"
                            value={cfg.text || ''}
                            onChange={(event) => set('text', event.target.value)}
                        />
                    </InspectorRow>
                )}

                <InspectorRow label="Size">
                    <div className="skw-ins__pair">
                        <Stepper label="width" value={widget.w} suffix="wide" onStep={(d) => stepSize('w', d)} />
                        <Stepper label="height" value={widget.h} suffix="tall" onStep={(d) => stepSize('h', d)} />
                    </div>
                </InspectorRow>
            </div>

            <div className="skw-ins__foot">
                <button type="button" className="btn btn-sm" onClick={onDuplicate}>
                    <Copy size={13} aria-hidden="true" /> Duplicate
                </button>
                <button type="button" className="btn btn-sm btn-danger skw-ins__remove" onClick={onRemove}>
                    <Trash2 size={13} aria-hidden="true" /> Remove
                </button>
            </div>
        </aside>
    );
}

export default WidgetInspector;
