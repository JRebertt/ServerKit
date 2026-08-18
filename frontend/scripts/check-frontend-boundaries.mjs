#!/usr/bin/env node
// Frontend browser-boundary ratchet.
//
// Shared helpers own browser APIs whose failure/auth/dialog semantics must stay
// consistent. New direct call sites fail lint. Clipboard has a finite legacy
// baseline so this can land without a risky all-at-once UI rewrite; the exact
// counts deliberately make every cleanup update (and shrink) the baseline.

import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, extname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const src = resolve(root, 'src');
const repoRoot = resolve(root, '..');

// Styles owned by a builtin extension must enter the bundle through that
// extension's module graph, not through core styles/main.scss. Keeping this
// declaration here makes ownership executable: both the source-of-truth and
// its checked-in pre-bundled copy must expose the same style entry, while core
// is forbidden from quietly taking the page partial back.
const EXTENSION_OWNED_STYLES = [
    {
        slug: 'serverkit-remote-access',
        importPath: './styles/remote-access.scss',
        forbiddenCoreImports: ['pages/_remote-access', 'pages/remote-access'],
    },
];

// Emptied 2026-08-18 (plan 76, F3): every call site now goes through
// copyToClipboard/useClipboard, whose execCommand fallback is what makes copy
// buttons work on an HTTP-served panel — navigator.clipboard is undefined in an
// insecure context, and SSL is optional by policy. This map must stay empty.
const LEGACY_CLIPBOARD = new Map();

// These are purpose-built experiences whose geometry/content is intentionally
// richer than the ordinary Modal contract. Any new exception needs review.
const LOW_LEVEL_DIALOG_EXCEPTIONS = new Set([
    'components/settings/connections/ConnectProviderModal.jsx',
    'components/settings/ThemeBrowseModal.jsx',
    'components/settings/ThemeStudioModal.jsx',
]);

function walk(dir) {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const path = join(dir, entry.name);
        return entry.isDirectory() ? walk(path) : [path];
    });
}

const files = walk(src).filter((path) => ['.js', '.jsx'].includes(extname(path)));
const failures = [];
const seenClipboard = new Set();

function rel(path) {
    return relative(src, path).replaceAll('\\', '/');
}

function count(source, pattern) {
    return [...source.matchAll(pattern)].length;
}

for (const path of files) {
    const file = rel(path);
    const source = readFileSync(path, 'utf8');

    if (file !== 'utils/clipboard.js') {
        const actual = count(source, /navigator\s*\.\s*clipboard/g);
        const expected = LEGACY_CLIPBOARD.get(file) || 0;
        if (actual !== expected) {
            failures.push(`${file}: direct navigator.clipboard count is ${actual}; legacy baseline is ${expected}. Use useClipboard/copyToClipboard and shrink the baseline.`);
        }
        if (expected) seenClipboard.add(file);
    }

    if (/(?:(?:window|globalThis)\s*\.\s*)?confirm\s*\(\s*['"`]/m.test(source)) {
        failures.push(`${file}: use useConfirm() instead of the browser confirm dialog.`);
    }

    const isUiCode = /^(?:components|contexts|data|hooks|pages)\//.test(file);
    if (isUiCode) {
        const rawFetch = source.split(/\r?\n/).some((line) => (
            /(?:^|[^.\w])(?:(?:window|globalThis)\s*\.\s*)?fetch\s*\(/.test(line)
            && !/\b(?:async\s+)?fetch\s*\([^)]*\)\s*\{/.test(line)
        ));
        if (rawFetch) {
            failures.push(`${file}: route authenticated requests through services/api instead of calling fetch directly.`);
        }
    }

    const isFeatureCode = /^(?:components|data|hooks|pages)\//.test(file);
    if (isFeatureCode && /localStorage\s*\.\s*getItem\s*\(\s*['"](?:accessToken|access_token|refresh_token)['"]/.test(source)) {
        failures.push(`${file}: do not read auth tokens in feature code; the centralized API client owns token access.`);
    }

    if (
        file !== 'services/workspaceStore.js'
        && /localStorage\s*\.\s*(?:getItem|setItem|removeItem)\s*\(\s*['"](?:active_workspace_id|active_workspace|workspace_accent)['"]/.test(source)
    ) {
        failures.push(`${file}: use WorkspaceContext/workspaceStore instead of reading or writing workspace persistence directly.`);
    }

    if (
        /(?:^|\/)ui\/dialog['"]/.test(source)
        && file !== 'components/Modal.jsx'
        && file !== 'components/ui/command.jsx'
        && !LOW_LEVEL_DIALOG_EXCEPTIONS.has(file)
    ) {
        failures.push(`${file}: use components/Modal for ordinary dialogs.`);
    }
}

for (const file of LEGACY_CLIPBOARD.keys()) {
    if (!seenClipboard.has(file)) {
        failures.push(`${file}: legacy clipboard entry is stale; remove it from the boundary baseline.`);
    }
}

const mainStylesPath = resolve(src, 'styles', 'main.scss');
const mainStyles = readFileSync(mainStylesPath, 'utf8');
for (const ownership of EXTENSION_OWNED_STYLES) {
    for (const importPath of ownership.forbiddenCoreImports) {
        const escaped = importPath.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        if (new RegExp(`@(?:import|use)\\s+['\"]${escaped}['\"]`).test(mainStyles)) {
            failures.push(
                `styles/main.scss: ${ownership.slug} owns ${importPath}; import its styles from the extension entry instead.`,
            );
        }
    }

    const entryPaths = [
        resolve(repoRoot, 'builtin-extensions', ownership.slug, 'frontend', 'index.jsx'),
        resolve(src, 'plugins', ownership.slug, 'index.jsx'),
    ];
    for (const entryPath of entryPaths) {
        const displayPath = relative(repoRoot, entryPath).replaceAll('\\', '/');
        if (!existsSync(entryPath)) {
            failures.push(`${displayPath}: missing extension frontend entry.`);
            continue;
        }
        const entry = readFileSync(entryPath, 'utf8');
        const escaped = ownership.importPath.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        if (!new RegExp(`import\\s+['\"]${escaped}['\"]`).test(entry)) {
            failures.push(`${displayPath}: must import ${ownership.importPath}.`);
        }

        const stylePath = resolve(dirname(entryPath), ownership.importPath);
        if (!existsSync(stylePath)) {
            failures.push(`${relative(repoRoot, stylePath).replaceAll('\\', '/')}: missing extension-owned stylesheet.`);
        }
    }
}

if (failures.length) {
    console.error('\nFrontend boundary check failed:\n');
    failures.forEach((failure) => console.error(`  - ${failure}`));
    console.error('');
    process.exit(1);
}

console.log(`✓ frontend boundaries: browser/API/dialog boundaries and ${EXTENSION_OWNED_STYLES.length} extension style ownership rule(s) hold (${LEGACY_CLIPBOARD.size} clipboard files remain ratcheted).`);
