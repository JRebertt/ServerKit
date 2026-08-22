import {
    Activity, AlertTriangle, Bug, Gauge, ListChecks, Radar, ScrollText,
    SlidersHorizontal, Stethoscope,
} from 'lucide-react';

// Shared sub-nav for the Monitoring page group. The Monitoring page's own
// sections live HERE, in the group's one top bar, rather than in a second tab
// strip inside the page — a nav under a nav reads as two competing headers
// (and is what the design mock does: its tabs sit in the top bar).
//
// Which host each section describes is a separate axis, carried by the top-bar
// server picker as `?server=` — so Overview/Capacity all follow the same scope.
// Fleet Monitor used to be a page of its own under Servers; its heatmap is now
// the Host health grid on Overview, and its analytics are Capacity.
//
// Monitors is the synthetic-check list (watch a URL, a service, a WordPress
// site). Incidents absorbed the old Alerts tab: a CPU threshold crossing on a
// host and a monitor going down are both "something is wrong right now", and
// splitting them was what made alerting look like it only ever described the
// panel's own machine. Host threshold alerting is unchanged, just rendered in
// the same timeline.
//
// Events is the telemetry stream and Jobs the unified job runner — both used to
// be top-level pages that read as rivals to this group.
//
// The Status Pages tab is contributed by the serverkit-status builtin extension
// (tab-group contribution, #43) and merged in by TabGroupLayout
// groupId="monitoring". TabGroupLayout overflows the tail into "⋯ More".
export const MONITOR_TABS = [
    { to: '/monitoring', labelKey: 'common.labels.overview', label: 'Overview', end: true, icon: <Activity size={15} /> },
    { to: '/monitoring/monitors', labelKey: 'app.monitorTabs.monitors', label: 'Monitors', icon: <Radar size={15} /> },
    { to: '/monitoring/incidents', labelKey: 'app.monitorTabs.incidents', label: 'Incidents', icon: <AlertTriangle size={15} /> },
    { to: '/monitoring/rules', labelKey: 'app.monitorTabs.rules', label: 'Rules', icon: <SlidersHorizontal size={15} /> },
    { to: '/monitoring/capacity', labelKey: 'app.monitorTabs.capacity', label: 'Capacity', icon: <Gauge size={15} /> },
    { to: '/telemetry', labelKey: 'app.monitorTabs.events', label: 'Events', icon: <ScrollText size={15} /> },
    { to: '/monitoring/jobs', labelKey: 'app.monitorTabs.jobs', label: 'Jobs', icon: <ListChecks size={15} /> },
    { to: '/monitoring/errors', labelKey: 'app.monitorTabs.errors', label: 'Errors', icon: <Bug size={15} /> },
    { to: '/monitoring/doctor', labelKey: 'app.monitorTabs.doctor', label: 'Doctor', icon: <Stethoscope size={15} /> },
];
