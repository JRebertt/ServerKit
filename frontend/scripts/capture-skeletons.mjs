#!/usr/bin/env node
/**
 * Dev-time skeleton bone capture (Phase 2 of docs/plans/50_SKELETON_LOADING_UX_PLAN.md).
 *
 * Boneyard's insight is that the most accurate loading skeleton is the *real*
 * rendered layout, measured. This script drives a headless browser against a
 * running dev server (logged in as admin/admin, with seeded dev data), snapshots
 * designated page regions into "bones" — `{x, y, w, h, r}` where x/w are
 * percentages of the region width and y/h are absolute pixels — and bakes the
 * result into `frontend/src/skeletons/<key>.json` as a static asset.
 *
 * `SkeletonBoundary`'s optional `bones` prop replays these via `renderBones`
 * (SCSS-classed absolutely-positioned divs), so the shipped product never
 * imports boneyard or runs a browser — it just reads the baked JSON.
 *
 * The in-page snapshot is `src/utils/snapshotBones.js` — a faithful port of
 * boneyard-js `snapshotBones` (`packages/boneyard/src/extract.ts`), shared with
 * the runtime self-capture hook. We inject its source into the page rather than
 * the npm ESM bundle so the script stays runnable from a fresh checkout;
 * `boneyard-js` is kept as a devDependency for parity and as the upstream source
 * of truth for the bone format.
 *
 * Usage:
 *   1. Start the dev stack (backend on :47927, `npm run dev` frontend) with
 *      seeded data and the default admin/admin credentials.
 *   2. npm run capture:skeletons          # captures every target in TARGETS
 *      SK_ONLY=ssl npm run capture:skeletons   # just one target
 *
 * Env knobs:
 *   SK_BASE_URL   frontend base URL (default http://127.0.0.1:41921)
 *   SK_USER       login username (default admin)
 *   SK_PASS       login password (default admin)
 *   SK_ONLY       comma list of target keys to capture (default: all)
 *   SK_HEADED     set to watch the browser (default headless)
 *   SK_WIDTH      viewport width used for the capture (default 1440)
 */
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { snapshotBones } from '../src/utils/snapshotBones.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = path.resolve(__dirname, '..');
const OUT_DIR = path.join(FRONTEND_DIR, 'src', 'skeletons');

const BASE = (process.env.SK_BASE_URL || 'http://127.0.0.1:41921').replace(/\/$/, '');
const USER = process.env.SK_USER || 'admin';
const PASS = process.env.SK_PASS || 'admin';
const HEADLESS = !process.env.SK_HEADED;
const WIDTH = Number(process.env.SK_WIDTH) || 1440;
const ONLY = (process.env.SK_ONLY || '').split(',').map((s) => s.trim()).filter(Boolean);

// Regions to snapshot. `selector` is the element whose subtree becomes bones;
// `waitFor` gates the capture until the real (non-skeleton) content has rendered.
// A capture is only as good as the data behind it: `waitFor` must gate on real
// content, never on `.empty-state`. Bones measured from an empty page bake in
// an empty layout and would predict "nothing is coming" — worse than the
// generic placeholder. So a page belongs here only once the dev database
// reliably has rows for it; everything else is served by the PageSkeleton
// archetypes (components/PageSkeleton.jsx), which need no data at all.
const TARGETS = [
    { key: 'ssl', path: '/ssl', selector: '.ssl-page', waitFor: '.ssl-status-bar' },
    { key: 'wordpress-list', path: '/wordpress', selector: '.wordpress-page', waitFor: '.sk-table, .wp-sites-grid' },
    { key: 'services', path: '/services', selector: '.services-page', waitFor: '.sk-dtable tbody tr' },
    { key: 'domains', path: '/domains', selector: '.domains-page', waitFor: '.sk-dtable tbody tr' },
    // NOT captured: /templates. Its catalog grid measures ~975 bones over
    // 5700px — a skeleton nobody scrolls, at a node count that costs more to
    // animate than the page costs to load. Unbounded lists belong to the
    // `cards` PageSkeleton archetype, which draws a screenful in eight nodes.
];

// A skeleton is a hint, not a rendering of the whole page. Past this many
// leaves the capture is measuring an unbounded list and should be an archetype
// instead, so fail rather than bake it in.
const MAX_BONES = 220;

const log = (...a) => console.log('[bones]', ...a);

// ---- driver ---------------------------------------------------------------
async function loadPlaywright() {
    try {
        return (await import('playwright')).chromium;
    } catch {
        console.error(
            'Playwright is required for bone capture but is not installed.\n' +
            'Install it once (dev-only, not shipped):\n' +
            '  npm i -D playwright && npx playwright install chromium',
        );
        process.exit(2);
    }
}

async function login(page) {
    await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    // Already authenticated? A redirect away from /login means we're in.
    if (!/\/login/.test(page.url())) return;

    // Target the credential fields by id. A generic `input[type="text"]` also
    // matches the 2FA digit boxes rendered above this form, and filling one of
    // those silently leaves the real form empty — every target then times out
    // waiting for page content that never loads because we are still on /login.
    const user = page.locator('#email');
    const pass = page.locator('#password');
    await user.waitFor({ state: 'visible', timeout: 15000 });
    await user.fill(USER);
    await pass.fill(PASS);
    await Promise.all([
        page.waitForURL((u) => !/\/login/.test(String(u)), { timeout: 30000 }).catch(() => {}),
        page.locator('button[type="submit"]').first().click(),
    ]);

    if (/\/login/.test(page.url())) {
        throw new Error(
            `login as "${USER}" failed — still on /login. Check SK_USER/SK_PASS `
            + '(the dev default admin/admin only exists on a freshly seeded database).',
        );
    }

    // Pin the session for the rest of the run. The API client clears both
    // tokens from localStorage whenever any request 401s (a single admin-only
    // endpoint returning 401 is enough), which bounced every target after the
    // first couple to /login. Re-seeding the captured tokens before app code
    // runs on each navigation makes the run independent of that.
    const tokens = await page.evaluate(() => ({
        access: localStorage.getItem('access_token'),
        refresh: localStorage.getItem('refresh_token'),
    }));
    if (tokens.access) {
        await page.context().addInitScript(({ access, refresh }) => {
            localStorage.setItem('access_token', access);
            if (refresh) localStorage.setItem('refresh_token', refresh);
        }, tokens);
    }
}

async function main() {
    await mkdir(OUT_DIR, { recursive: true });
    const targets = ONLY.length ? TARGETS.filter((t) => ONLY.includes(t.key)) : TARGETS;
    if (!targets.length) { console.error(`No targets matched SK_ONLY=${ONLY.join(',')}`); process.exit(2); }

    const chromium = await loadPlaywright();
    const browser = await chromium.launch({ headless: HEADLESS });
    const context = await browser.newContext({ viewport: { width: WIDTH, height: 900 }, deviceScaleFactor: 1 });
    const page = await context.newPage();

    let failed = 0;
    try {
        await login(page);
        for (const t of targets) {
            process.stdout.write(`[bones] ${t.key.padEnd(16)} `);
            try {
                // Each target is a full page load, and a mid-run 401 can still
                // bounce one to /login despite the pinned tokens. Re-auth and
                // retry once, so a single flake doesn't cost a whole region.
                for (let attempt = 0; ; attempt += 1) {
                    await page.goto(`${BASE}${t.path}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
                    if (/\/login/.test(page.url())) await login(page);
                    try {
                        await page.waitForSelector(t.waitFor, { timeout: 15000, state: 'visible' });
                        break;
                    } catch (waitErr) {
                        if (attempt >= 1) throw waitErr;
                        await login(page);
                    }
                }
                await page.waitForTimeout(600); // let layout settle
                const snapshot = await page.evaluate(
                    ({ selector, key, fnSrc }) => {
                        const el = document.querySelector(selector);
                        if (!el) return null;
                        const fn = new Function(`return (${fnSrc})`)();
                        return fn(el, key);
                    },
                    { selector: t.selector, key: t.key, fnSrc: snapshotBones.toString() },
                );
                if (!snapshot || !snapshot.bones.length) throw new Error(`no bones captured for ${t.selector}`);
                if (snapshot.bones.length > MAX_BONES) {
                    throw new Error(
                        `${snapshot.bones.length} bones over ${snapshot.height}px exceeds the ${MAX_BONES} cap — `
                        + 'this region is an unbounded list; use a PageSkeleton archetype instead',
                    );
                }
                await writeFile(path.join(OUT_DIR, `${t.key}.json`), JSON.stringify(snapshot, null, 2) + '\n');
                console.log(`OK  (${snapshot.bones.length} bones, ${snapshot.height}px)`);
            } catch (e) {
                failed += 1;
                // A bare "waitForSelector timeout" hides the usual causes —
                // bounced to /login, route not found, or the page rendered its
                // empty state because the dev database has no rows for it. Say
                // which, so the fix is obvious.
                const url = page.url();
                let why = '';
                try {
                    if (/\/login/.test(url)) why = ' (bounced to /login — session lost)';
                    else if (await page.locator('.empty-state').count()) why = ' (page rendered its empty state — no seeded data for this target)';
                    else if (!(await page.locator(t.selector).count())) why = ` (root ${t.selector} not on the page — wrong route or class)`;
                } catch { /* page may be gone */ }
                console.log(`FAIL  ${e.message.split('\n')[0]}${why} [at ${url}]`);
            }
        }
    } finally {
        await context.close();
        await browser.close();
    }

    log(`done -> ${OUT_DIR}`);
    if (failed) process.exit(1);
}

main().catch((e) => { console.error(e); process.exit(1); });
