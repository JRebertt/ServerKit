import { Activity, Bell, Gauge, ScrollText, SlidersHorizontal, Stethoscope } from 'lucide-react';

// Shared sub-nav for the Observability page group. The Monitoring page's own
// sections live HERE, in the group's one top bar, rather than in a second tab
// strip inside the page — a nav under a nav reads as two competing headers
// (and is what the design mock does: its tabs sit in the top bar).
//
// Which host each section describes is a separate axis, carried by the top-bar
// server picker as `?server=` — so Overview/Alerts/Capacity all follow the same
// scope. Fleet Monitor used to be a page of its own under Servers; its heatmap
// is now the Host health grid on Overview, and its analytics are Capacity.
//
// The Status Pages tab is contributed by the serverkit-status builtin extension
// (tab-group contribution, #43) and merged in by TabGroupLayout
// groupId="monitoring".
export const MONITOR_TABS = [
    { to: '/monitoring', label: 'Overview', end: true, icon: <Activity size={15} /> },
    { to: '/monitoring/alerts', label: 'Alerts', icon: <Bell size={15} /> },
    { to: '/monitoring/rules', label: 'Rules', icon: <SlidersHorizontal size={15} /> },
    { to: '/monitoring/capacity', label: 'Capacity', icon: <Gauge size={15} /> },
    { to: '/monitoring/doctor', label: 'Doctor', icon: <Stethoscope size={15} /> },
    { to: '/telemetry', label: 'Events', icon: <ScrollText size={15} /> },
];
