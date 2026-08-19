#!/usr/bin/env node
// Style-ownership ratchet (plan 76, milestone G).
//
// A class defined at the top level of more than one partial has no owner. All
// of the definitions apply, merged per-property in main.scss import order, so
// the rendered element is a composite nobody wrote and editing any one file
// changes only the properties that file happens to win.
//
// `.empty-state` is the worked example. Three partials define it —
// components/_empty-state.scss (flex column, min-height 200px),
// components/_cards.scss (card background, solid border, radius) and
// components/_users.scss (padding, colour) — and the compiled stylesheet
// carries five competing top-level rules for it. What actually renders takes
// its background and dashed border from one, its padding and display from
// another, and its colour from a third.
//
// This is deliberately a ratchet and not a migration. Merging these correctly
// means reproducing the computed result of the cascade, and there is no
// byte-identical-output proof available the way there was for @keyframes — so
// it needs eyes on the affected pages (plan invariant 9: no repo-wide
// mechanical rewrite without behavioural tests). The count may only go down.
//
// Usage (from frontend/):
//   node scripts/check-style-ownership.mjs            # check against the ceiling
//   node scripts/check-style-ownership.mjs --report   # list the offenders
//   node scripts/check-style-ownership.mjs --update   # write the current count

import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, extname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const stylesDir = resolve(root, 'src', 'styles');
const ceilingFile = resolve(here, 'STYLE_OWNERSHIP_CEILING');

function walk(dir) {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const path = join(dir, entry.name);
        return entry.isDirectory() ? walk(path) : [path];
    });
}

export function census() {
    const owners = new Map();
    for (const path of walk(stylesDir).filter((p) => extname(p) === '.scss')) {
        const rel = relative(stylesDir, path).replaceAll('\\', '/');
        let depth = 0;
        for (const line of readFileSync(path, 'utf8').split(/\r?\n/)) {
            // Column 0 only: a nested `.foo {}` is scoped by its parent and is
            // not competing for ownership of the bare class.
            const match = depth === 0 ? /^\.([A-Za-z][\w-]*)\s*\{/.exec(line) : null;
            if (match) {
                if (!owners.has(match[1])) owners.set(match[1], new Set());
                owners.get(match[1]).add(rel);
            }
            for (const ch of line) {
                if (ch === '{') depth += 1;
                else if (ch === '}') depth -= 1;
            }
        }
    }
    return new Map([...owners].filter(([, files]) => files.size > 1));
}

const shared = census();
// Count DEFINITIONS, not names. Counting names would let a class that is
// already shared spread to a fourth and fifth partial without moving the
// number — the failure mode this is meant to stop.
const count = [...shared.values()].reduce((total, files) => total + files.size, 0);

if (process.argv.includes('--update')) {
    writeFileSync(ceilingFile, `${count}\n`);
    console.log(`style-ownership ceiling updated to ${count}`);
    process.exit(0);
}

if (process.argv.includes('--report')) {
    const rows = [...shared].sort((a, b) => b[1].size - a[1].size);
    for (const [name, files] of rows) {
        console.log(`  .${name.padEnd(28)} ${files.size}  (${[...files].join(', ')})`);
    }
    console.log(`\ntotal: ${count}`);
    process.exit(0);
}

const ceiling = Number(readFileSync(ceilingFile, 'utf8').trim());

if (count > ceiling) {
    const worst = [...shared].sort((a, b) => b[1].size - a[1].size).slice(0, 5);
    console.error(`\nStyle ownership check failed:\n`);
    console.error(`  ${count} top-level definitions share ${shared.size} class names across`);
    console.error(`  partials; the ceiling is ${ceiling}. Give the class one owner, or scope`);
    console.error(`  the new rule under its page/component instead of redefining the bare`);
    console.error(`  class.\n`);
    for (const [name, files] of worst) {
        console.error(`  .${name} — ${[...files].join(', ')}`);
    }
    console.error('');
    process.exit(1);
}

if (ceiling - count > 5) {
    console.error(`\nStyle ownership ceiling is ${ceiling} but only ${count} remain; run`);
    console.error(`  node scripts/check-style-ownership.mjs --update\n`);
    process.exit(1);
}

console.log(`✓ style ownership: ${count} shared definitions across ${shared.size} class names remain ratcheted (ceiling ${ceiling}).`);
