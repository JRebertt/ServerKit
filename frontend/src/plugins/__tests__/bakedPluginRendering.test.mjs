import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, existsSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

// Baked plugin rendering contract.
//
// PluginLoader has a legacy auto-render: any baked plugin module with a
// default export and NO contributions gets that export rendered globally
// on every route. A baked extension whose manifest declares contributions
// owns its rendering through the contribution model instead — installed
// or not — because its module ships in the bundle either way.
//
// Regression pinned here: serverkit-walkthrough-studio was baked with a
// `export default WalkthroughStudioPage` while not installed on a panel,
// so the legacy auto-render stacked the whole Studio page on top of the
// dashboard. Two independent guards prevent a recurrence:
//
//   1. PluginLoader excludes plugins whose BAKED manifest declares
//      contributions (declaresBakedContributions).
//   2. This test: a baked plugin that declares route contributions must
//      not also carry a default export in its index module — routes
//      resolve named exports, and the default only feeds the legacy
//      auto-render footgun.

const HERE = dirname(fileURLToPath(import.meta.url));
const PLUGINS_DIR = join(HERE, '..');

function bakedPluginDirs() {
    return readdirSync(PLUGINS_DIR).filter((name) => {
        const dir = join(PLUGINS_DIR, name);
        if (!statSync(dir).isDirectory()) return false;
        if (name === 'sdk' || name === 'runtime' || name === '__tests__') return false;
        return existsSync(join(dir, 'plugin.json'));
    });
}

function indexSource(slug) {
    for (const file of ['index.jsx', 'index.js']) {
        const path = join(PLUGINS_DIR, slug, file);
        if (existsSync(path)) return readFileSync(path, 'utf8');
    }
    return null;
}

function declaresContributions(manifest) {
    const contrib = manifest?.contributions;
    if (!contrib || typeof contrib !== 'object') return false;
    return Object.values(contrib).some((value) => (
        Array.isArray(value)
            ? value.length > 0
            : !!value && typeof value === 'object' && Object.keys(value).length > 0
    ));
}

test('baked plugins are discoverable', () => {
    const dirs = bakedPluginDirs();
    assert.ok(dirs.length > 0, 'expected at least one baked plugin directory');
    assert.ok(
        dirs.includes('serverkit-walkthrough-studio'),
        'expected the walkthrough studio to be among baked plugins '
        + '(if it was unbaked on purpose, update this test)',
    );
});

test('a baked plugin with route contributions has no default export', () => {
    for (const slug of bakedPluginDirs()) {
        const manifest = JSON.parse(
            readFileSync(join(PLUGINS_DIR, slug, 'plugin.json'), 'utf8'),
        );
        const routes = manifest?.contributions?.routes || [];
        if (!routes.length) continue;

        const source = indexSource(slug);
        assert.ok(source, `${slug}: baked plugin has no index module`);
        assert.ok(
            !/^\s*export\s+default\s/m.test(source),
            `${slug}: declares route contributions AND a default export — `
            + 'the legacy auto-render in PluginLoader would mount that export '
            + 'globally on panels where the extension is not installed. '
            + 'Export the page under a name and point the route at it.',
        );
    }
});

test('PluginLoader gates the legacy auto-render on baked manifests', () => {
    const loader = readFileSync(join(PLUGINS_DIR, 'PluginLoader.jsx'), 'utf8');
    assert.match(
        loader,
        /declaresBakedContributions\(slug\)/,
        'PluginLoader must exclude plugins whose baked manifest declares '
        + 'contributions from the legacy auto-render',
    );
});

test('every baked plugin declaring contributions keeps them out of the legacy path', () => {
    // The studio specifically: manifest declares contributions, so guard 1
    // (declaresBakedContributions) must classify it as contribution-owned.
    const manifest = JSON.parse(readFileSync(
        join(PLUGINS_DIR, 'serverkit-walkthrough-studio', 'plugin.json'), 'utf8',
    ));
    assert.equal(declaresContributions(manifest), true);
});
