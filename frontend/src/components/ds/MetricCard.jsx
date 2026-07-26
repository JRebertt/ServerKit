import { cn } from '@/lib/utils';
import { formatCompact, formatFull } from '../../utils/formatNumber';

// KPI / stat tile: icon chip + big value (+ optional unit) + label, with an
// optional trend delta in the top-right.
// tone: 'accent' | 'green' | 'cyan' | 'amber' | 'red' | 'violet'
// trendDir: 'up' | 'down' | 'flat'
//
// When `onClick` is provided the tile renders as a semantic <button> (keyboard
// accessible, design-system focus ring) so KPIs can drive a filter/navigation.
// `kind` is accepted as a deprecated alias for `tone` (dev-only console.warn) —
// this heals silent API misuse where a page passed a prop the tile dropped.
// `secondary` is read by KpiBand to force-fold a tile into the compact strip;
// it is not a visual prop on the tile itself.
// `compact` opts a numeric tile into space-tight formatting: a value ≥ 1000 is
// rendered compact (107814 → "107.8K") with the exact grouped number as the
// hover title. Non-numeric values (or values under 1000) render verbatim.
// `spark` takes a chart node (Sparkline / AreaChart) and bleeds it to the
// tile's edges along the bottom — the design mock's `.kpi-spark`. Passing it is
// what turns a bare stat into a trend tile; tiles without a series simply omit
// it and keep the same geometry, so a row can mix both.
export function MetricCard({
    icon,
    tone,
    kind,
    value,
    unit,
    label,
    trend,
    trendDir = 'flat',
    spark,
    onClick,
    compact = false,
    className,
    children,
    secondary: _secondary,   // consumed by KpiBand, kept out of DOM props
    ...props
}) {
    if (import.meta.env.DEV && kind && !tone) {
        console.warn(
            `[MetricCard] \`kind="${kind}"\` is deprecated — use \`tone\` instead ` +
            '(accent|green|cyan|amber|red|violet).'
        );
    }
    const resolvedTone = tone || kind || 'accent';

    // Compact tiles fold ≥1000 numeric values to a short form and expose the
    // exact grouped number as the title so the precise count is one hover away.
    const numericValue = typeof value === 'number' ? value : Number(value);
    const useCompact = compact && Number.isFinite(numericValue) && Math.abs(numericValue) >= 1000;
    const displayValue = useCompact ? formatCompact(numericValue) : value;
    const valueTitle = useCompact ? String(formatFull(numericValue)) : undefined;

    const inner = (
        <>
            <div className="sk-kpi__top">
                {icon && <span className={cn('sk-kpi__icon', `sk-kpi__icon--${resolvedTone}`)}>{icon}</span>}
                {trend != null && (
                    <span className={cn('sk-kpi__trend', `sk-kpi__trend--${trendDir}`)}>{trend}</span>
                )}
            </div>
            <div className="sk-kpi__val" title={valueTitle}>
                {displayValue}
                {unit && <small> {unit}</small>}
            </div>
            {label && <div className="sk-kpi__label">{label}</div>}
            {children}
            {spark && <div className="sk-kpi__spark">{spark}</div>}
        </>
    );

    if (onClick) {
        return (
            <button
                type="button"
                className={cn('sk-kpi', 'sk-kpi--clickable', className)}
                onClick={onClick}
                {...props}
            >
                {inner}
            </button>
        );
    }

    return (
        <div className={cn('sk-kpi', className)} {...props}>
            {inner}
        </div>
    );
}

export default MetricCard;
