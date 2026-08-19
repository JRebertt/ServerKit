#!/usr/bin/env node
// Plan 77 D3 ratchet — ONE frontend status→tone vocabulary.
//
// Fails when a file outside src/components/ds/status.js defines its own
// status→color/kind/variant object map. Run with: npm run check:status
//
// The allowlist below is the frozen 2026-08-19 population of files whose
// matches are NOT status color maps (rank orders, label-only maps, icon
// metadata, raw CSS-var renderers deferred to the D4 SCSS pass). Shrinking
// it is progress; adding to it needs a reason that is not "my page wants
// its own colors" — extend ds/status.js instead.

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const SRC = new URL('../src', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1');

const ALLOWED = new Set([
  'components/ds/status.js',            // the one door
  'components/backups/BackupCalendar.jsx', // STATUS_RANK: severity ordering, not colors
  'components/databases/SourceTree.jsx',   // STATUS_LABEL: labels only
  'pages/DeployConsole.jsx',               // STATUS_META: labels+icons+css classes (D4 territory)
  'components/dashboard/widgets/renderers.jsx', // raw CSS-var renderer (D4 territory)
  'components/NotificationBell.jsx',       // SEVERITY_DOT hex dots (D4 territory)
  'pages/Notifications.jsx',               // SEVERITY_DOT hex dots (D4 territory)
  'components/LinkedAppsSection.jsx',      // css-class map (D4 territory)
  'components/apps/AppWafPanel.jsx',       // WAF mode map (block=green is domain-inverted) + ModSec severities
  'components/monitoring/MonitoringOverview.jsx', // metric-series colors (cpu/mem/disk), not statuses
  'components/security/FirewallTab.jsx',   // firewall rule-TYPE tones, not statuses
  'pages/PublicStatusPage.jsx',            // status-page meta bundle (labels+icons), public surface
  'pages/StatusPages.jsx',                 // status-page meta bundle (labels+icons+dots)
]);

// A "status map" smell: an object-literal or switch mapping status-ish keys
// to Pill kinds / Badge variants.
const DEF_RE = /(?:const|let|var)\s+\w*(?:STATUS|SEVERITY|TONE|PILL)\w*\s*=\s*\{[^}]*(?:'green'|'amber'|'red'|'cyan'|'violet'|'gray'|'success'|'destructive'|'warning'|'info'|'outline'|'secondary')/s;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) yield* walk(p);
    else if (/\.(jsx?|mjs)$/.test(name)) yield p;
  }
}

const offenders = [];
for (const file of walk(SRC)) {
  const rel = relative(SRC, file).replaceAll('\\', '/');
  if (ALLOWED.has(rel)) continue;
  const text = readFileSync(file, 'utf8');
  if (DEF_RE.test(text)) offenders.push(rel);
}

if (offenders.length) {
  console.error('New local status→tone maps (extend src/components/ds/status.js instead):');
  for (const f of offenders) console.error('  ' + f);
  process.exit(1);
}
console.log('status one-door: OK');
