#!/usr/bin/env node
// Frontend browser-boundary ratchet.
//
// Shared helpers own browser APIs whose failure/auth/dialog semantics must stay
// consistent. New direct call sites fail lint. Clipboard has a finite legacy
// baseline so this can land without a risky all-at-once UI rewrite; the exact
// counts deliberately make every cleanup update (and shrink) the baseline.

import { readFileSync, readdirSync } from 'node:fs';
import { dirname, extname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const src = resolve(root, 'src');

const LEGACY_CLIPBOARD = new Map(Object.entries({
    'components/cloudflare/TunnelsPanel.jsx': 1,
    'components/databases/CreateTableModal.jsx': 2,
    'components/databases/DbUsersPanel.jsx': 2,
    'components/databases/EngineInstallDrawer.jsx': 1,
    'components/databases/ManagedDatabasesPanel.jsx': 2,
    'components/deploy-console/ErrorCard.jsx': 1,
    'components/docker/ContainersTab.jsx': 1,
    'components/serverdetail/CloudflaredTab.jsx': 1,
    'components/serverdetail/serverDetailShared.jsx': 1,
    'components/serverdetail/ServerSettingsTab.jsx': 1,
    'components/service-detail/LogsTab.jsx': 1,
    'components/settings/ApiKeyModal.jsx': 1,
    'components/settings/IconReferenceTab.jsx': 1,
    'components/settings/InvitationsTab.jsx': 1,
    'components/settings/InviteModal.jsx': 1,
    'components/settings/LoginLinksSection.jsx': 1,
    'components/settings/SecuritySettingsTab.jsx': 1,
    'components/settings/WebhooksTab.jsx': 1,
    'components/setup/SetupStepSecurity.jsx': 1,
    'pages/Databases.jsx': 1,
    'pages/DeployConsole.jsx': 1,
    'pages/Downloads.jsx': 1,
    'pages/FileManager.jsx': 1,
    'pages/Git.jsx': 6,
    'pages/StatusPages.jsx': 1,
}));

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

if (failures.length) {
    console.error('\nFrontend boundary check failed:\n');
    failures.forEach((failure) => console.error(`  - ${failure}`));
    console.error('');
    process.exit(1);
}

console.log(`✓ frontend boundaries: no browser confirm/raw UI fetch/token or workspace persistence reads/new clipboard or dialog bypasses (${LEGACY_CLIPBOARD.size} clipboard files remain ratcheted).`);
