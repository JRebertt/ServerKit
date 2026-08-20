#!/usr/bin/env node
// Plan 79 ratchet 7 — writing-direction properties in SCSS.
//
// LocaleContext sets `<html dir>` from the language manifest, so the plumbing
// for a right-to-left locale exists. What does not exist is a stylesheet that
// can follow it: physical properties (`margin-left`, `padding-right`, bare
// `left:` / `right:`) are anchored to the page edge and ignore `dir`, so an
// RTL locale would render a mirrored language inside an unmirrored layout.
//
// This is a RATCHET, not a migration. Converting the existing population means
// looking at every page it touches, and the plan is explicit that no RTL
// locale ships until that happens. What the ratchet buys is that the number
// stops growing: new code writes `margin-inline-start` and friends, so the
// eventual conversion shrinks instead of racing the codebase.
//
// Usage (from frontend/):
//   node scripts/check-logical-properties.mjs            # check the ceiling
//   node scripts/check-logical-properties.mjs --report   # worst files first
//   node scripts/check-logical-properties.mjs --update   # write current count

import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, extname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const stylesDir = resolve(root, 'src', 'styles');
const ceilingFile = resolve(here, 'LOGICAL_PROPERTY_CEILING');

// Direction-anchored declarations. `text-align: left/right` is included for
// the same reason: it pins prose to a page edge that RTL moves.
const PATTERNS = [
    /\b(?:margin|padding|border)-(?:left|right)\s*:/g,
    /\bborder-(?:top|bottom)-(?:left|right)-radius\s*:/g,
    /(?:^|[\s;{])(?:left|right)\s*:/g,
    /\btext-align\s*:\s*(?:left|right)\b/g,
    /\bfloat\s*:\s*(?:left|right)\b/g,
];

function walk(dir) {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const path = join(dir, entry.name);
        return entry.isDirectory() ? walk(path) : (extname(path) === '.scss' ? [path] : []);
    });
}

export function census() {
    const byFile = new Map();
    for (const path of walk(stylesDir)) {
        const rel = relative(stylesDir, path).replaceAll('\\', '/');
        const lines = readFileSync(path, 'utf8').split(/\r?\n/);
        let hits = 0;
        let inBlock = false;
        for (const line of lines) {
            let code = line;
            if (inBlock) {
                const end = code.indexOf('*/');
                if (end === -1) continue;
                code = code.slice(end + 2);
                inBlock = false;
            }
            code = code.replace(/\/\*[^*]*\*\//g, '');
            const blockStart = code.indexOf('/*');
            if (blockStart !== -1) { inBlock = true; code = code.slice(0, blockStart); }
            const lineComment = code.indexOf('//');
            if (lineComment !== -1) code = code.slice(0, lineComment);

            for (const pattern of PATTERNS) {
                hits += [...code.matchAll(pattern)].length;
            }
        }
        if (hits) byFile.set(rel, hits);
    }
    return byFile;
}

const byFile = census();
const count = [...byFile.values()].reduce((total, hits) => total + hits, 0);

if (process.argv.includes('--update')) {
    writeFileSync(ceilingFile, `${count}\n`);
    console.log(`logical-property ceiling updated to ${count}`);
    process.exit(0);
}

if (process.argv.includes('--report')) {
    for (const [file, hits] of [...byFile].sort((a, b) => b[1] - a[1]).slice(0, 30)) {
        console.log(`  ${String(hits).padStart(4)}  ${file}`);
    }
    console.log(`\ntotal: ${count} direction-anchored declarations in ${byFile.size} files`);
    process.exit(0);
}

const ceiling = Number(readFileSync(ceilingFile, 'utf8').trim());

if (count > ceiling) {
    console.error('\nlogical property check failed:\n');
    console.error(`  ${count} direction-anchored declarations; the ceiling is ${ceiling}.`);
    console.error('  Use logical properties so the rule follows <html dir>:\n');
    console.error('      margin-left      ->  margin-inline-start');
    console.error('      padding-right    ->  padding-inline-end');
    console.error('      left: 0          ->  inset-inline-start: 0');
    console.error('      text-align: left ->  text-align: start\n');
    for (const [file, hits] of [...byFile].sort((a, b) => b[1] - a[1]).slice(0, 5)) {
        console.error(`  ${String(hits).padStart(4)}  ${file}`);
    }
    console.error('');
    process.exit(1);
}

if (ceiling - count > 20) {
    console.error(`\nlogical-property ceiling is ${ceiling} but only ${count} remain; run`);
    console.error('  node scripts/check-logical-properties.mjs --update\n');
    process.exit(1);
}

console.log(`✓ logical properties: ${count} direction-anchored declarations remain ratcheted (ceiling ${ceiling}).`);
