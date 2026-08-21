import { useState, useMemo } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { statusKind } from './format';
import { useTranslation } from 'react-i18next';

// Card of the backup "Protection" panel: a Monday-first month grid of backup
// runs. Pairs with the .backup-calendar styles. Uses native Date math (no libs).

// Monday-first weekday headers, matching the column order of the grid.
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

// Worst-first status precedence for a day: failed > success > running.
// `statusKind` is reused to keep the day's status vocabulary aligned with Pills.
const STATUS_RANK = { failed: 2, success: 1, running: 0 };

function pad(n) {
    return String(n).padStart(2, '0');
}

// Local calendar-day key (YYYY-MM-DD) for a Date.
function dayKey(d) {
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function startOfMonth(d) {
    return new Date(d.getFullYear(), d.getMonth(), 1);
}

function daysInMonth(year, month) {
    // Day 0 of the next month is the last day of this month.
    return new Date(year, month + 1, 0).getDate();
}

// Count of leading blank cells before day 1, with Monday as the first column.
function leadingBlanks(year, month) {
    return (new Date(year, month, 1).getDay() + 6) % 7;
}

// Collapse a run's status into one of the three day buckets used for ranking.
function dayStatus(status) {
    if (status === 'failed') return 'failed';
    if (status === 'success') return 'success';
    return 'running'; // covers 'running' and 'verifying'
}

export default function BackupCalendar({ runs, onDayClick }) {
    const { t } = useTranslation();
    const [cursor, setCursor] = useState(() => new Date());

    // Map of dayKey -> { count, worst } built from all runs (month-independent).
    const dayMap = useMemo(() => {
        const map = new Map();
        (runs || []).forEach((run) => {
            if (!run || !run.started_at) return;
            const d = new Date(run.started_at);
            if (Number.isNaN(d.getTime())) return;
            const key = dayKey(d);
            const status = dayStatus(run.status);
            const existing = map.get(key);
            if (!existing) {
                map.set(key, { count: 1, worst: status });
                return;
            }
            existing.count += 1;
            if (STATUS_RANK[status] > STATUS_RANK[existing.worst]) {
                existing.worst = status;
            }
        });
        return map;
    }, [runs]);

    // Cells for the visible month: leading/trailing blanks are null, real days
    // carry their date, day number, and (if any) backup count + worst status.
    const cells = useMemo(() => {
        const year = cursor.getFullYear();
        const month = cursor.getMonth();
        const blanks = leadingBlanks(year, month);
        const total = daysInMonth(year, month);
        const result = [];

        for (let i = 0; i < blanks; i += 1) {
            result.push(null);
        }
        for (let day = 1; day <= total; day += 1) {
            const date = new Date(year, month, day);
            const info = dayMap.get(dayKey(date));
            result.push({
                date,
                day,
                count: info ? info.count : 0,
                worst: info ? info.worst : null,
            });
        }
        return result;
    }, [cursor, dayMap]);

    const monthLabel = cursor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });

    const prevMonth = () => setCursor((c) => new Date(c.getFullYear(), c.getMonth() - 1, 1));
    const nextMonth = () => setCursor((c) => new Date(c.getFullYear(), c.getMonth() + 1, 1));
    const goToday = () => setCursor(startOfMonth(new Date()));

    return (
        <div className="backup-calendar">
            <div className="backup-calendar__head">
                <button type="button" className="backup-calendar__nav" onClick={prevMonth} aria-label={t('app.backupCalendar.previousMonth', 'Previous month')}><ChevronLeft size={16} /></button>
                <span className="backup-calendar__month">{monthLabel}</span>
                <button type="button" className="backup-calendar__nav" onClick={nextMonth} aria-label={t('app.backupCalendar.nextMonth', 'Next month')}><ChevronRight size={16} /></button>
                <button type="button" className="backup-calendar__today" onClick={goToday}>{t('app.backupCalendar.today', 'Today')}</button>
            </div>
            <div className="backup-calendar__grid">
                {WEEKDAYS.map((d) => <div key={d} className="backup-calendar__dow">{d}</div>)}
                {cells.map((cell, i) => (
                    cell
                        ? (
                            <button
                                type="button"
                                key={i}
                                className={`backup-calendar__cell ${cell.count ? `backup-calendar__cell--has is-${cell.worst}` : ''}`}
                                disabled={!cell.count}
                                onClick={cell.count ? () => onDayClick(cell.date) : undefined}
                            >
                                <span className="backup-calendar__daynum">{cell.day}</span>
                                {cell.count > 0 && <span className="backup-calendar__badge">{cell.count}</span>}
                            </button>
                        )
                        : <span key={i} className="backup-calendar__cell backup-calendar__cell--empty" />
                ))}
            </div>
        </div>
    );
}
