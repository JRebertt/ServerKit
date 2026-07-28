// 90-day uptime strip: one bar per day, from the design mock.
//
// A day with no samples renders as its own "unwatched" state rather than a full
// green bar — "we weren't looking" and "it was fine" are different facts, and
// conflating them is how uptime widgets end up lying about their own history.
import { cn } from '@/lib/utils';

function tooltipFor(day) {
    if (day.state === 'none') return `${day.date} — not monitored`;
    const pct = day.uptime != null ? `${day.uptime.toFixed(3)}%` : '—';
    return `${day.date} — ${pct} uptime, ${day.checks} check${day.checks === 1 ? '' : 's'}`
        + (day.down_checks ? `, ${day.down_checks} failed` : '');
}

export default function UptimeBars({ days = [], selected, onSelect, className }) {
    if (!days.length) return null;
    return (
        <div className={cn('uptime-bars', className)}>
            {days.map((day) => (
                // A bar in a chart is not a <Button>: 90 of them, each a bare
                // 6px sliver with no label or affordance of its own. Semantic
                // <button> keeps it keyboard-reachable without dragging the
                // full button styling into a data visualisation.
                // eslint-disable-next-line no-restricted-syntax
                <button
                    key={day.date}
                    type="button"
                    className={cn(
                        'uptime-bars__bar',
                        `uptime-bars__bar--${day.state}`,
                        selected === day.date && 'is-selected',
                    )}
                    title={tooltipFor(day)}
                    aria-label={tooltipFor(day)}
                    onClick={() => onSelect?.(day)}
                />
            ))}
        </div>
    );
}
