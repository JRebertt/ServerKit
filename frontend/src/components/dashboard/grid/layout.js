// Pure geometry helpers for the dashboard widget grid.
//
// The board is a fixed 12-column grid. A widget instance is
// `{ i, type, x, y, w, h, cfg }` where x/y are cell coordinates and w/h are
// spans in cells. Everything in here is side-effect free and returns new
// arrays, so callers can drive React state straight from the result.

/** Columns in the board grid. */
export const GRID_COLS = 12;
/** Gutter between cells, in px. */
export const GRID_GAP = 12;
/** Height of one row unit, in px. */
export const GRID_ROW = 88;

// findFreeSpot gives up after this many rows rather than looping forever on a
// pathological board.
const MAX_SCAN_ROWS = 200;

/**
 * True when two widget rectangles intersect. A widget never overlaps itself,
 * so the same `i` short-circuits to false.
 */
export function overlaps(a, b) {
    return (
        a.i !== b.i
        && a.x < b.x + b.w
        && a.x + a.w > b.x
        && a.y < b.y + b.h
        && a.y + a.h > b.y
    );
}

/**
 * Gravity-up compaction: walk the widgets top-to-bottom, left-to-right and
 * float each one as far up as it can go without hitting an already-placed
 * neighbour. Returns a new array of new objects.
 */
export function compact(list) {
    const out = [...list]
        .sort((a, b) => a.y - b.y || a.x - b.x)
        .map((widget) => ({ ...widget }));
    const placed = [];
    out.forEach((widget) => {
        let y = widget.y;
        while (y > 0 && !placed.some((other) => overlaps(other, { ...widget, y: y - 1 }))) y -= 1;
        widget.y = y;
        placed.push(widget);
    });
    return out;
}

/**
 * Apply `moved` to the board, push anything it lands on straight down (and
 * anything those hit, recursively), then re-compact. Returns a new array.
 */
export function pushDown(list, moved) {
    const out = list.map((widget) => (widget.i === moved.i ? { ...moved } : { ...widget }));
    const seen = new Set();
    const walk = (target) => {
        if (!target || seen.has(target.i)) return;
        seen.add(target.i);
        out.filter((widget) => overlaps(widget, target)).forEach((widget) => {
            widget.y = target.y + target.h;
            walk(widget);
        });
    };
    walk(out.find((widget) => widget.i === moved.i));
    return compact(out);
}

/** Lowest unused `w<N>` id for this board. */
export function nextWidgetId(list) {
    let n = 1;
    while (list.some((widget) => widget.i === `w${n}`)) n += 1;
    return `w${n}`;
}

/**
 * First cell (scanning row by row, left to right) where a `w`×`h` widget fits
 * without overlapping anything. Falls back to the origin — compaction will
 * sort out the collision.
 */
export function findFreeSpot(list, w, h) {
    for (let y = 0; y < MAX_SCAN_ROWS; y += 1) {
        for (let x = 0; x <= GRID_COLS - w; x += 1) {
            const candidate = { i: '__new', x, y, w, h };
            if (!list.some((other) => overlaps(other, candidate))) return { x, y };
        }
    }
    return { x: 0, y: 0 };
}
