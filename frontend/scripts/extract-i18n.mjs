#!/usr/bin/env node
// Plan 79 D1 — generate src/i18n/locales/en.json from the source tree.
//
// The inline English default IS the source of truth:
//
//     t('apps.empty.title', 'No applications yet')
//
// en.json is generated from those defaults and must never be hand-edited. Two
// properties follow from that, and they are what make a migration of this size
// survivable:
//
//   * A key that has not been extracted yet still renders correct English, so
//     a half-migrated page is never broken and never shows a raw key path to a
//     user.
//   * Renaming the English copy is a one-place edit in the component; the
//     translations for other locales stay keyed and are visibly stale rather
//     than silently wrong.
//
// Usage (from frontend/):
//   node scripts/extract-i18n.mjs           # write en.json
//   node scripts/extract-i18n.mjs --check   # fail if en.json is out of date

import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, extname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'espree';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const srcDir = resolve(root, 'src');
const outFile = resolve(srcDir, 'i18n', 'locales', 'en.json');

const SKIP_DIRS = new Set(['node_modules', '__mocks__']);
const SKIP_FILE = /\.(test|spec|stories)\.[jt]sx?$/;

function walk(dir) {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const path = join(dir, entry.name);
        if (entry.isDirectory()) return SKIP_DIRS.has(entry.name) ? [] : walk(path);
        if (!['.js', '.jsx'].includes(extname(entry.name))) return [];
        if (SKIP_FILE.test(entry.name)) return [];
        return [path];
    });
}

// Bare `t(...)` only -- the `const { t } = useTranslation()` idiom.
//
// Deliberately NOT `<anything>.t(...)`: `i18next.t(key, ...)` inside the
// format door re-dispatches a key it was handed, so its argument is a variable
// by construction. Flagging that would make the door unextractable while the
// literal keys at its own call sites are right there to collect.
function isTranslationCall(node) {
    return node.type === 'CallExpression'
        && node.callee.type === 'Identifier'
        && node.callee.name === 't';
}

/** The English default declared at a call site, or null. */
function defaultValueOf(node) {
    const [, second, third] = node.arguments;
    if (second?.type === 'Literal' && typeof second.value === 'string') return second.value;
    for (const candidate of [second, third]) {
        if (candidate?.type !== 'ObjectExpression') continue;
        for (const property of candidate.properties) {
            if (property.type !== 'Property' || property.computed) continue;
            const key = property.key.name || property.key.value;
            if (key === 'defaultValue' && property.value.type === 'Literal') {
                return String(property.value.value);
            }
        }
    }
    return null;
}

function visit(node, onCall) {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node)) {
        for (const child of node) visit(child, onCall);
        return;
    }
    if (!node.type) return;
    if (isTranslationCall(node)) onCall(node);
    for (const key of Object.keys(node)) {
        if (key === 'type' || key === 'loc' || key === 'range') continue;
        visit(node[key], onCall);
    }
}

export function collect() {
    const entries = new Map();       // key -> { value, sites: [] }
    const problems = [];

    for (const path of walk(srcDir)) {
        const rel = relative(root, path).replaceAll('\\', '/');
        let ast;
        try {
            ast = parse(readFileSync(path, 'utf8'), {
                ecmaVersion: 'latest',
                sourceType: 'module',
                ecmaFeatures: { jsx: true },
                loc: true,
            });
        } catch (error) {
            problems.push(`${rel}: parse failed — ${error.message}`);
            continue;
        }

        visit(ast, (node) => {
            const first = node.arguments[0];
            const site = `${rel}:${node.loc.start.line}`;

            if (first?.type !== 'Literal' || typeof first.value !== 'string') {
                // A computed key cannot be extracted, so its English can only
                // live in en.json by hand -- which the generated file forbids.
                problems.push(`${site}: t() called with a non-literal key`);
                return;
            }
            const key = first.value;
            const value = defaultValueOf(node);
            if (value === null) {
                problems.push(`${site}: t('${key}') has no inline English default`);
                return;
            }

            const existing = entries.get(key);
            if (existing && existing.value !== value) {
                problems.push(
                    `${site}: key '${key}' redefines the English default\n`
                    + `        here:  ${JSON.stringify(value)}\n`
                    + `        there: ${JSON.stringify(existing.value)} (${existing.sites[0]})`,
                );
                return;
            }
            if (existing) {
                existing.sites.push(site);
                return;
            }
            entries.set(key, { value, sites: [site] });
        });
    }

    return { entries, problems };
}

/** Dotted keys into the nested shape the locale files use. */
export function nest(entries) {
    const tree = {};
    const problems = [];

    for (const key of [...entries.keys()].sort()) {
        const parts = key.split('.');
        let node = tree;
        let ok = true;
        for (const part of parts.slice(0, -1)) {
            if (typeof node[part] === 'string') {
                problems.push(`key '${key}' nests under '${part}', which is already a string`);
                ok = false;
                break;
            }
            node[part] = node[part] || {};
            node = node[part];
        }
        if (!ok) continue;
        const leaf = parts[parts.length - 1];
        if (node[leaf] && typeof node[leaf] === 'object') {
            problems.push(`key '${key}' is both a string and a namespace`);
            continue;
        }
        node[leaf] = entries.get(key).value;
    }

    return { tree, problems };
}

const { entries, problems: collectProblems } = collect();
const { tree, problems: nestProblems } = nest(entries);
const problems = [...collectProblems, ...nestProblems];

if (problems.length) {
    console.error('\ni18n extraction failed:\n');
    for (const problem of problems) console.error(`  ${problem}`);
    console.error('\n  Every t() needs a literal key and an inline English default:');
    console.error("      t('apps.empty.title', 'No applications yet')\n");
    process.exit(1);
}

const serialized = `${JSON.stringify(tree, null, 4)}\n`;

if (process.argv.includes('--check')) {
    let current = '';
    try {
        current = readFileSync(outFile, 'utf8');
    } catch {
        current = '';
    }
    if (current !== serialized) {
        console.error('\nen.json is out of date — it is generated, not written.\n');
        console.error('  node scripts/extract-i18n.mjs\n');
        process.exit(1);
    }
    console.log(`✓ en.json is current (${entries.size} keys).`);
    process.exit(0);
}

writeFileSync(outFile, serialized);
console.log(`✓ wrote ${relative(root, outFile).replaceAll('\\', '/')} — ${entries.size} keys.`);
