import { useState, useMemo } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { PageTopbar } from '@/components/ds';
import { useContributions } from '@/plugins/contributions';
import { sanitizeSvgInner } from '@/utils/sanitizeSvg';

// Generic shell for a PageTopbar tab group (Servers, Domains, Services, Files,
// Monitoring, Marketplace, …). A parent route renders the PageTopbar + routed
// sub-nav ONCE and swaps only the content below, so the tabs behave like real
// tabs — no full-page remount — and the matching sidebar item stays lit (see
// sidebarItems.js `matchPrefixes`). Child pages render no top bar of their own;
// they publish their own top-bar actions via the useTopbarActions() hook.
//
//   <Route element={<TabGroupLayout tabs={DOMAIN_TABS} />}>
//       <Route path="domains" element={<Domains />} />
//       <Route path="dns" element={<DNSZones />} />
//       <Route path="ssl" element={<SSLCertificates />} />
//   </Route>
//
// Groups that accept extension-contributed tabs (#43) also pass a `groupId`
// (== the group's sidebar item id): installed extensions can then add entries
// to the strip via a `tabs` contribution, paired with `group`-nested routes
// mounted by App.jsx inside this same parent <Route>.
function matchTab(tab, path) {
    if (tab.end) return path === tab.to;
    // Segment-aware so "/fleet" doesn't swallow "/fleet-monitor".
    return path === tab.to || path.startsWith(tab.to + '/');
}

// Contributed tab icons arrive as raw inner-SVG markup (same convention as
// sidebar nav icons); wrap them in the lucide-compatible svg shell the core
// tab entries use.
function contributedIcon(inner) {
    if (!inner) return null;
    return (
        <svg
            width={15}
            height={15}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            focusable="false"
            dangerouslySetInnerHTML={{ __html: sanitizeSvgInner(inner) }}
        />
    );
}

export default function TabGroupLayout({ tabs, groupId }) {
    const location = useLocation();
    const [actions, setActions] = useState(null);
    const { tabs: contributedTabs } = useContributions();

    // Merge extension-contributed tabs for this group into the strip.
    // Dedup by `to` (core wins); optional numeric `order` picks the
    // insertion index, default appends at the end.
    const mergedTabs = useMemo(() => {
        if (!groupId) return tabs;
        const extras = (contributedTabs || [])
            .filter((t) => t && t.group === groupId && t.to && t.label)
            .filter((t) => !tabs.some((core) => core.to === t.to))
            .map((t) => ({
                to: t.to,
                label: t.label,
                end: !!t.end,
                icon: contributedIcon(t.icon),
                order: t.order,
            }));
        if (!extras.length) return tabs;
        const merged = [...tabs];
        for (const t of extras) {
            const { order, ...tab } = t;
            const idx = Number.isInteger(order)
                ? Math.min(Math.max(order, 0), merged.length)
                : merged.length;
            merged.splice(idx, 0, tab);
        }
        return merged;
    }, [tabs, groupId, contributedTabs]);

    // The group renders no page title: the tab strip IS the heading, so it runs
    // flush-left in the bar (the active tab already names the section, as does
    // the lit sidebar item). The active tab is still resolved to label the nav
    // for assistive tech.
    const active = useMemo(
        () => mergedTabs.find((t) => matchTab(t, location.pathname)) || mergedTabs[0],
        [mergedTabs, location.pathname]
    );

    return (
        <div className="page-container page-container--full-bleed sk-tabgroup">
            <PageTopbar
                navLabel={active.label}
                tabs={mergedTabs}
                actions={actions}
            />
            <div className="sk-tabgroup__content">
                <Outlet context={{ setTopbarActions: setActions }} />
            </div>
        </div>
    );
}
