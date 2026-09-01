import test from 'node:test';
import assert from 'node:assert/strict';

import {
    WALKTHROUGHS,
    WALKTHROUGH_BY_ID,
    localizeWalkthroughs,
} from '../../data/walkthroughs.js';
import {
    buildWalkthroughRegistry,
    normalizeWalkthroughDefinition,
    validateWalkthroughDefinition,
    WALKTHROUGH_COMPLETION_TYPES,
} from '../walkthroughRegistry.js';


const OPTIONAL_IDS = [
    'publish-service',
    'monitor-service',
    'protect-with-backups',
    'connect-server',
    'invite-teammate',
];

test('keeps the two essentials prominent and the five added guides optional', () => {
    assert.deepEqual(
        WALKTHROUGHS.filter((guide) => !guide.secondary).map((guide) => guide.id),
        ['create-service', 'enable-two-factor'],
    );
    assert.deepEqual(
        WALKTHROUGHS.filter((guide) => guide.secondary).map((guide) => guide.id),
        OPTIONAL_IDS,
    );
});

test('walkthrough ids and step ids are stable and unique', () => {
    assert.equal(new Set(WALKTHROUGHS.map((guide) => guide.id)).size, WALKTHROUGHS.length);
    for (const guide of WALKTHROUGHS) {
        assert.equal(new Set(guide.steps.map((step) => step.id)).size, guide.steps.length);
        assert.ok(guide.steps.every((step) => step.title && step.description && step.action));
        assert.equal(WALKTHROUGH_BY_ID[guide.id], guide);
    }
});

test('optional guides finish on real product outcome signals', () => {
    const finalSignals = Object.fromEntries(OPTIONAL_IDS.map((id) => {
        const guide = WALKTHROUGH_BY_ID[id];
        return [id, guide.steps.at(-1).signal];
    }));

    assert.deepEqual(finalSignals, {
        'publish-service': 'service-ssl-enabled',
        'monitor-service': 'monitor-check-completed',
        'protect-with-backups': 'backup-created',
        'connect-server': 'server-paired',
        'invite-teammate': 'invitation-link-copied',
    });
});

test('every guide and step retains localized display copy', () => {
    const localized = localizeWalkthroughs((_key, fallback) => fallback);
    assert.equal(localized.length, WALKTHROUGHS.length);
    for (const guide of localized) {
        assert.ok(guide.title && guide.description && guide.duration);
        assert.ok(guide.steps.every((step) => step.title && step.description && step.action));
    }
});

const contributedGuide = {
    id: 'first-run',
    plugin: 'serverkit-demo',
    title: 'Try Demo',
    description: 'Complete the first Demo task.',
    duration: 'About 2 minutes',
    steps: [
        {
            id: 'open-demo',
            title: 'Open Demo',
            description: 'Navigate to Demo.',
            action: 'Open Demo',
            path: '/demo',
            target: 'demo-page',
            completion: { type: 'route', path: '/demo' },
        },
        {
            id: 'create-item',
            title: 'Create an item',
            description: 'Submit the form successfully.',
            target: 'demo-submit',
            completion: { type: 'signal', signal: 'demo.item-created' },
        },
    ],
};

test('normalizes extension walkthroughs into a namespaced runtime guide', () => {
    const guide = normalizeWalkthroughDefinition(contributedGuide);
    assert.equal(guide.id, 'serverkit-demo.first-run');
    assert.equal(guide.origin.plugin, 'serverkit-demo');
    assert.equal(guide.steps[0].route, '/demo');
    assert.equal(guide.steps[0].target, '[data-walkthrough="demo-page"]');
    assert.equal(guide.steps[1].signal, 'demo.item-created');
});

test('merges core, extension, and custom guides without id collisions', () => {
    const custom = { ...contributedGuide, id: 'first-run' };
    delete custom.plugin;
    const registry = buildWalkthroughRegistry({
        core: WALKTHROUGHS,
        contributed: [contributedGuide, contributedGuide],
        custom: [custom, custom],
    });
    assert.ok(registry.byId['serverkit-demo.first-run']);
    assert.ok(registry.byId['custom.first-run']);
    assert.equal(
        registry.walkthroughs.filter((guide) => guide.id.endsWith('.first-run')).length,
        2,
    );
});

test('supports five safe declarative completion modes and rejects selectors', () => {
    assert.deepEqual(
        WALKTHROUGH_COMPLETION_TYPES.map((type) => type.value),
        ['manual', 'route', 'signal', 'check', 'target'],
    );
    const invalid = structuredClone(contributedGuide);
    invalid.steps[0].target = '#password';
    assert.ok(validateWalkthroughDefinition(invalid).some((item) => item.path.endsWith('target')));
    assert.equal(normalizeWalkthroughDefinition(invalid), null);
});
