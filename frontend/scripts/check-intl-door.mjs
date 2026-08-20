#!/usr/bin/env node
// Plan 79 ratchet 5 — one locale-aware formatting door.
//
// Counts direct `toLocaleString` / `toLocaleDateString` / `toLocaleTimeString`
// calls and direct `new Intl.*` construction outside `src/utils/intl.js`.
//
// Every one of these is a locale bug, not merely a style problem: called with
// no argument they follow the BROWSER's locale rather than the panel's, so a
// panel switched to Spanish still renders English dates -- and a formatter
// built at module load can never follow a switch at all. They are also the
// slow path: tables construct one formatter per cell per render, which is the
// expensive half of Intl.
//
// Usage (from frontend/):
//   node scripts/check-intl-door.mjs            # check against the ceiling
//   node scripts/check-intl-door.mjs --report   # list the offenders
//   node scripts/check-intl-door.mjs --update   # write the current count

import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, extname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
// `--root <dir>` censuses another tree — an extension repo's own src/. An
// extension's `toLocaleDateString()` is the same bug as core's: with no
// argument it follows the BROWSER, so its dates disagree with every date
// around them on a panel set to another language.
const rootArg = process.argv.includes('--root')
    ? process.argv[process.argv.indexOf('--root') + 1]
    : null;
const srcDir = rootArg ? resolve(process.cwd(), rootArg) : resolve(root, 'src');
const ceilingFile = resolve(here, 'INTL_DOOR_CEILING');

// The door itself, and the tests that prove it behaves per locale.
const ALLOWED = new Set([
    'utils/intl.js',
    'utils/__tests__/intl.test.mjs',
]);

const PATTERN = /\.toLocale(?:Date|Time)?String\s*\(|new\s+Intl\.\w+/g;

function walk(dir) {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const path = join(dir, entry.name);
        if (entry.isDirectory()) {
            return entry.name === 'node_modules' ? [] : walk(path);
        }
        return ['.js', '.jsx', '.mjs'].includes(extname(entry.name)) ? [path] : [];
    });
}

export function census() {
    const byFile = new Map();
    for (const path of walk(srcDir)) {
        const rel = relative(srcDir, path).replaceAll('\\', '/');
        if (ALLOWED.has(rel)) continue;
        const hits = [];
        const lines = readFileSync(path, 'utf8').split(/\r?\n/);
        // Comments are stripped first: a doc comment that NAMES the pattern is
        // not a call, and counting it would mean a violation could be "fixed"
        // by commenting it out.
        let inBlock = false;
        lines.forEach((line, index) => {
            let code = line;
            if (inBlock) {
                const end = code.indexOf('*/');
                if (end === -1) return;
                code = code.slice(end + 2);
                inBlock = false;
            }
            code = code.replace(/\/\*[^*]*\*\//g, '');
            const blockStart = code.indexOf('/*');
            if (blockStart !== -1) {
                inBlock = true;
                code = code.slice(0, blockStart);
            }
            const lineComment = code.indexOf('//');
            if (lineComment !== -1) code = code.slice(0, lineComment);

            for (const match of code.matchAll(PATTERN)) {
                hits.push({ line: index + 1, text: match[0].trim() });
            }
        });
        if (hits.length) byFile.set(rel, hits);
    }
    return byFile;
}

const byFile = census();
const count = [...byFile.values()].reduce((total, hits) => total + hits.length, 0);

if (process.argv.includes('--update')) {
    if (rootArg) {
        console.error('--update writes the HOST ceiling; refusing to do that from --root.');
        process.exit(2);
    }
    writeFileSync(ceilingFile, `${count}\n`);
    console.log(`intl door ceiling updated to ${count}`);
    process.exit(0);
}

if (process.argv.includes('--report')) {
    const rows = [...byFile].sort((a, b) => b[1].length - a[1].length);
    for (const [file, hits] of rows) {
        console.log(`  ${String(hits.length).padStart(3)}  ${file}`);
        for (const hit of hits.slice(0, 3)) {
            console.log(`         :${hit.line}  ${hit.text}`);
        }
    }
    console.log(`\ntotal: ${count} direct calls in ${byFile.size} files`);
    process.exit(0);
}

const ceiling = Number(readFileSync(ceilingFile, 'utf8').trim());

if (count > ceiling) {
    const worst = [...byFile].sort((a, b) => b[1].length - a[1].length).slice(0, 5);
    console.error('\nintl door check failed:\n');
    console.error(`  ${count} direct Intl / toLocale* calls; the ceiling is ${ceiling}.`);
    console.error('  Format through the door so the value follows the PANEL locale:\n');
    console.error("      import useFormat from '@/hooks/useFormat';        // components");
    console.error("      import { formatDate } from '@/utils/intl';        // everything else\n");
    for (const [file, hits] of worst) {
        console.error(`  ${String(hits.length).padStart(3)}  ${file}`);
    }
    console.error('');
    process.exit(1);
}

if (ceiling - count > 5) {
    console.error(`\nintl door ceiling is ${ceiling} but only ${count} remain; run`);
    console.error('  node scripts/check-intl-door.mjs --update\n');
    process.exit(1);
}

console.log(`✓ intl door: ${count} direct Intl/toLocale calls remain ratcheted (ceiling ${ceiling}).`);
