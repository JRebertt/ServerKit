#!/usr/bin/env node
// Plan 77 D4 ratchet — status colors go through @mixin status-variant.
//
// The mechanical `background: <tone-bg>; color: <tone>;` pairs (174 of them)
// were converted to `@include status-variant(...)`; this check keeps the
// count of raw convertible pairs at ZERO so the shape cannot re-roll.
// Run via: npm run lint  (or node scripts/check-status-scss.mjs)

import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const ROOTS = ['src/styles/pages', 'src/styles/components'];

const TOK = String.raw`(?:var\(--[\w-]+\)|\$[\w-]+)`;
const TOKBG = String.raw`(?:var\(--[\w-]+-bg\)|\$[\w-]+-bg)`;

const PATTERNS = [
  new RegExp(String.raw`^(\s*)background: ${TOKBG};\n\1color: ${TOK};`, 'm'),
  new RegExp(String.raw`^(\s*)color: ${TOK};\n\1background: ${TOKBG};`, 'm'),
  new RegExp(String.raw`\{ background: ${TOKBG}; color: ${TOK}; \}`),
];

const offenders = [];
for (const root of ROOTS) {
  for (const name of readdirSync(root)) {
    if (!name.endsWith('.scss')) continue;
    const text = readFileSync(join(root, name), 'utf8');
    for (const pattern of PATTERNS) {
      if (pattern.test(text)) {
        offenders.push(`${root}/${name}`);
        break;
      }
    }
  }
}

if (offenders.length) {
  console.error('Raw status color pairs (use @include status-variant($color, $bg, $border) from _mixins.scss):');
  for (const f of offenders) console.error('  ' + f);
  process.exit(1);
}
console.log('status scss one-door: OK');
