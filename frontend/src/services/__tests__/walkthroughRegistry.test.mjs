import test from 'node:test';
import assert from 'node:assert/strict';

import {
    WALKTHROUGHS,
    WALKTHROUGH_BY_ID,
    localizeWalkthroughs,
} from '../../data/walkthroughs.js';


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
