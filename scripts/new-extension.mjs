#!/usr/bin/env node
/**
 * Scaffold a new ServerKit extension (task #40).
 *
 *   node scripts/new-extension.mjs <slug> [--backend] [--builtin]
 *   node scripts/new-extension.mjs --validate <path>
 *
 *   <slug>       kebab-case extension name, e.g. serverkit-uptime-badge
 *   --backend    also scaffold a backend/ blueprint + lifecycle skeleton
 *   --builtin    scaffold under builtin-extensions/<slug>/ (in-repo, pre-bundled)
 *                instead of a standalone ./<slug>/ folder for a third-party repo
 *   --validate   lint an existing plugin.json (or a folder containing one)
 *                against the same shape rules the panel enforces at install
 *                time (#52): module:attr refs, jobs/schedules shapes, required
 *                keys per contribution kind. Exits non-zero on problems;
 *                unknown contribution kinds only warn.
 *
 * After scaffolding, install it into a dev panel with:
 *   - builtin:      one-click from the Marketplace (Built-in), or
 *                   POST /api/v1/plugins/builtin/<slug>/install
 *   - standalone:   POST /api/v1/plugins/install-local  { "path": "<abs path>" }
 *
 * See docs/EXTENSIONS.md for the full authoring guide.
 */
import { promises as fs } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { validateWalkthroughDefinition } from '../frontend/src/services/walkthroughRegistry.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

const args = process.argv.slice(2);

// ---------------------------------------------------------------------------
// --validate mode: lint a manifest with the same rules plugin_service enforces
// at install. Keep in sync with _validate_manifest + GET /plugins/manifest-spec.
// ---------------------------------------------------------------------------
const MODULE_REF_RE = /^[A-Za-z_][\w.]*:[A-Za-z_]\w*$/;
const REQUIRED_CONTRIB_KEYS = {
    nav: ['id', 'label', 'route'],
    routes: ['path', 'component'],
    tabs: ['group', 'to', 'label'],
    command_palette: ['label', 'path'],
    widgets: ['slot', 'component'],
    layouts: ['id', 'component'],
    walkthroughs: ['id', 'title', 'description', 'steps'],
};
const KNOWN_CONTRIB_KINDS = new Set([...Object.keys(REQUIRED_CONTRIB_KEYS), 'page_titles', 'ai']);

function validateManifest(manifest) {
    const problems = [];
    const warnings = [];

    for (const field of ['name', 'display_name', 'version']) {
        if (!manifest[field]) problems.push(`missing required field: ${field}`);
    }
    if (manifest.name && !/^[a-zA-Z0-9_-]+$/.test(manifest.name)) {
        problems.push(`name must be alphanumeric/dashes/underscores: ${manifest.name}`);
    }

    for (const field of ['entry_point', 'socket_entry', 'models']) {
        const val = manifest[field];
        if (val && !(typeof val === 'string' && MODULE_REF_RE.test(val))) {
            problems.push(`${field} must be a 'module:attr' string (got ${JSON.stringify(val)})`);
        }
    }

    const lifecycle = manifest.lifecycle;
    if (lifecycle != null) {
        if (typeof lifecycle !== 'object' || Array.isArray(lifecycle)) {
            problems.push('lifecycle must be an object of phase -> module:func');
        } else {
            for (const [phase, target] of Object.entries(lifecycle)) {
                if (!(typeof target === 'string' && MODULE_REF_RE.test(target))) {
                    problems.push(`lifecycle.${phase} must be a 'module:func' string`);
                }
            }
        }
    }

    if (manifest.jobs != null) {
        if (!Array.isArray(manifest.jobs)) {
            problems.push('jobs must be a list of {kind, handler}');
        } else {
            manifest.jobs.forEach((j, i) => {
                if (!(j && typeof j === 'object' && j.kind
                        && typeof j.handler === 'string' && MODULE_REF_RE.test(j.handler))) {
                    problems.push(`jobs[${i}] must be {kind, handler: 'module:func'}`);
                }
            });
        }
    }

    if (manifest.schedules != null) {
        if (!Array.isArray(manifest.schedules)) {
            problems.push('schedules must be a list of {name, kind, cron?|interval_seconds?}');
        } else {
            manifest.schedules.forEach((s, i) => {
                if (!(s && typeof s === 'object' && s.name && s.kind)) {
                    problems.push(`schedules[${i}] needs name and kind`);
                }
            });
        }
    }

    const contrib = manifest.contributions;
    if (contrib != null && (typeof contrib !== 'object' || Array.isArray(contrib))) {
        problems.push('contributions must be an object');
    } else if (contrib) {
        for (const key of Object.keys(contrib)) {
            if (!KNOWN_CONTRIB_KINDS.has(key)) {
                warnings.push(`unknown contribution kind '${key}' (ignored by the panel)`);
            }
        }
        for (const [kind, req] of Object.entries(REQUIRED_CONTRIB_KEYS)) {
            const entries = contrib[kind];
            if (entries == null) continue;
            if (!Array.isArray(entries)) {
                problems.push(`contributions.${kind} must be a list`);
                continue;
            }
            entries.forEach((entry, i) => {
                if (!entry || typeof entry !== 'object') {
                    problems.push(`contributions.${kind}[${i}] must be an object`);
                    return;
                }
                const missing = req.filter((k) => !entry[k]);
                if (missing.length) {
                    problems.push(`contributions.${kind}[${i}] missing ${missing.join(', ')}`);
                }
            });
        }
        if (contrib.page_titles != null
                && (typeof contrib.page_titles !== 'object' || Array.isArray(contrib.page_titles))) {
            problems.push('contributions.page_titles must be an object of path -> title');
        }
        if (Array.isArray(contrib.walkthroughs)) {
            contrib.walkthroughs.forEach((walkthrough, i) => {
                for (const item of validateWalkthroughDefinition(walkthrough)) {
                    const suffix = item.path ? `.${item.path}` : '';
                    problems.push(`contributions.walkthroughs[${i}]${suffix}: ${item.message}`);
                }
            });
        }
    }

    return { problems, warnings };
}

const validateIdx = args.indexOf('--validate');
if (validateIdx !== -1) {
    const target = path.resolve(args[validateIdx + 1] || '.');
    let manifestPath = target;
    try {
        if ((await fs.stat(target)).isDirectory()) {
            manifestPath = path.join(target, 'plugin.json');
        }
    } catch {
        console.error(`Not found: ${target}`);
        process.exit(1);
    }

    let manifest;
    try {
        manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'));
    } catch (e) {
        console.error(`Cannot read ${manifestPath}: ${e.message}`);
        process.exit(1);
    }

    const { problems, warnings } = validateManifest(manifest);
    for (const w of warnings) console.warn(`  ⚠ ${w}`);
    if (problems.length) {
        for (const p of problems) console.error(`  ✘ ${p}`);
        console.error(`\n${problems.length} problem(s) in ${path.relative(process.cwd(), manifestPath)}`);
        process.exit(1);
    }
    console.log(`✔ ${path.relative(process.cwd(), manifestPath)} is a valid ServerKit extension manifest`);
    process.exit(0);
}

const slug = args.find((a) => !a.startsWith('--'));
const withBackend = args.includes('--backend');
const asBuiltin = args.includes('--builtin');

if (!slug || !/^[a-zA-Z0-9_-]+$/.test(slug)) {
    console.error('Usage: node scripts/new-extension.mjs <slug> [--backend] [--builtin]');
    console.error('       node scripts/new-extension.mjs --validate <path>');
    console.error('  <slug> must be alphanumeric/dashes/underscores.');
    process.exit(1);
}

const componentName = slug
    .split(/[-_]/)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join('') + 'Page';

const baseDir = asBuiltin
    ? path.join(ROOT, 'builtin-extensions', slug)
    : path.join(ROOT, slug);

const displayName = slug.replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

const manifest = {
    name: slug,
    display_name: displayName,
    version: '0.1.0',
    description: 'A ServerKit extension.',
    author: '',
    license: 'MIT',
    category: 'utility',
    permissions: [],
    min_panel_version: null,
    contributions: {
        nav: [{
            id: slug,
            label: slug.replace(/[-_]/g, ' '),
            route: `/${slug}`,
            category: 'system',
            icon: '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
        }],
        routes: [
            { path: slug, component: componentName },
            // Forwards every sub-path to the same component, so adding a tab
            // is just appending to TABS in frontend/index.jsx — no manifest edit.
            { path: `${slug}/:tab`, component: componentName },
        ],
        page_titles: { [`/${slug}`]: displayName },
        command_palette: [{ label: slug, path: `/${slug}`, category: 'Pages', keywords: slug }],
    },
};

if (withBackend) {
    manifest.entry_point = 'blueprint:ext_bp';
    manifest.url_prefix = `/api/v1/${slug}`;
    manifest.lifecycle = { install: 'lifecycle:on_install', uninstall: 'lifecycle:on_uninstall' };
}

const frontendIndex = `// ${manifest.display_name} — extension UI entry.
// Exports named components referenced by contributions.routes[].component.
//
// Layout: the same shell the core tab-group pages use (/services, /domains, …).
// The page renders the full-bleed .sk-tabgroup shell itself — a PageTopbar with
// a routed tab strip pinned to the top and centered content inside
// .sk-tabgroup__inner. Add a section by appending to TABS (the ${slug}/:tab
// route in plugin.json already forwards every sub-path here) and switching the
// rendered content on useParams().tab. Publish header buttons via PageTopbar's
// \`actions\` prop; use the @/components/ds primitives (DataTable, SegControl,
// MetricCard, …) for the body.
import { Puzzle } from 'lucide-react';
import { PageTopbar } from '@/components/ds';

const TABS = [
    { to: '/${slug}', label: 'Overview', end: true, icon: <Puzzle size={15} /> },
];

export function ${componentName}() {
    return (
        <div className="page-container page-container--full-bleed sk-tabgroup">
            <PageTopbar
                icon={<Puzzle size={18} />}
                title="${manifest.display_name}"
                tabs={TABS}
            />
            <div className="sk-tabgroup__content">
                <div className="sk-tabgroup__inner">
                    <p>Replace this with your extension UI.</p>
                </div>
            </div>
        </div>
    );
}
`;

const backendBlueprint = `"""${manifest.display_name} backend blueprint."""
from flask import Blueprint, jsonify
from app.plugins_sdk import jwt_required, current_user, logger

ext_bp = Blueprint('${slug.replace(/-/g, '_')}', __name__)
log = logger(__name__)


@ext_bp.route('/ping', methods=['GET'])
@jwt_required()
def ping():
    return jsonify({'ok': True, 'plugin': '${slug}'})
`;

const backendLifecycle = `"""Lifecycle hooks for ${manifest.display_name}."""
from app.plugins_sdk import logger

log = logger(__name__)


def on_install(plugin):
    log.info('Installing ${slug}')


def on_uninstall(plugin, purge=False):
    log.info('Uninstalling ${slug} (purge=%s)', purge)
`;

async function writeFile(rel, content) {
    const full = path.join(baseDir, rel);
    await fs.mkdir(path.dirname(full), { recursive: true });
    await fs.writeFile(full, content);
    console.log(`  created ${path.relative(ROOT, full)}`);
}

async function main() {
    try {
        await fs.access(baseDir);
        console.error(`Refusing to overwrite existing directory: ${baseDir}`);
        process.exit(1);
    } catch { /* doesn't exist — good */ }

    console.log(`Scaffolding ${asBuiltin ? 'builtin ' : ''}extension "${slug}"…`);
    await writeFile('plugin.json', JSON.stringify(manifest, null, 2) + '\n');
    await writeFile('frontend/index.jsx', frontendIndex);
    if (withBackend) {
        await writeFile('backend/blueprint.py', backendBlueprint);
        await writeFile('backend/lifecycle.py', backendLifecycle);
    }

    console.log('\nDone.');
    if (asBuiltin) {
        console.log('Pre-bundle the frontend:  node scripts/sync-builtin-frontends.mjs');
        console.log('Then install it from the Marketplace (Built-in).');
    } else {
        console.log(`Install into a dev panel:  POST /api/v1/plugins/install-local { "path": "${baseDir}" }`);
    }
    console.log('Guide: docs/EXTENSIONS.md');
}

main().catch((e) => { console.error(e); process.exit(1); });
