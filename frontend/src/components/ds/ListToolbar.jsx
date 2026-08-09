import { cn } from '@/lib/utils';

// The one list toolbar. Every list page used to hand-roll its own header row
// (.dom-listhead, .cron-listhead, .bk-listhead, .servers-listhead,
// .incidents-listhead, .wp-list__toolbar…) — same anatomy, a dozen names.
// This component is the anatomy:
//
//   [title?] [filters] [children]        [count?] [tools]
//
//   <ListToolbar
//     title="Cron jobs"                          // optional section title
//     filters={<SegControl … />}                 // primary quick filters, left
//     count={<>12 of 20 jobs · <b>8 active</b></>}  // mono meta, right
//     tools={<><ViewMenu … /><SortMenu … /><ColumnsMenu … /></>}
//   >
//     {/* optional extras between filters and the right group (e.g. a select) */}
//   </ListToolbar>
//
// Placement rule (see AGENTS.md "Page anatomy"): page-level actions,
// FilterButton and SearchField live in the shared topbar; quick filters,
// counts and the table menus live here.
export function ListToolbar({ title, filters, count, tools, children, className }) {
    return (
        <div className={cn('sk-listhead', className)}>
            {title && <h2 className="sk-listhead__title">{title}</h2>}
            {filters}
            {children}
            {(count || tools) && (
                <div className="sk-listhead__right">
                    {count && <span className="sk-listhead__count">{count}</span>}
                    {tools}
                </div>
            )}
        </div>
    );
}

export default ListToolbar;
