import assert from 'node:assert/strict';
import test from 'node:test';

import {
    MAX_AI_ATTACHMENTS,
    addAttachment,
    applyAttachmentWarning,
    markAttachmentsResolved,
    toAttachmentPayload,
} from './attachments.js';

test('attachment drafts normalize service aliases, deduplicate, and cap', () => {
    let items = addAttachment([], { type: 'app', id: 7, label: 'API', path: '/services/7' });
    items = addAttachment(items, { type: 'service', id: '7', label: 'Duplicate' });
    assert.equal(items.length, 1);
    assert.equal(items[0].type, 'service');

    for (let index = 1; index < MAX_AI_ATTACHMENTS + 3; index += 1) {
        items = addAttachment(items, { type: 'server', id: index, label: `Node ${index}` });
    }
    assert.equal(items.length, MAX_AI_ATTACHMENTS);
});

test('resolver warnings update only the matching chip', () => {
    const items = [
        { type: 'service', id: '1', label: 'API', status: null },
        { type: 'server', id: '2', label: 'Worker', status: null },
    ];
    const warned = applyAttachmentWarning(items, {
        type: 'server', id: '2', status: 'denied', message: 'Access denied',
    });
    const resolved = markAttachmentsResolved(warned);
    assert.equal(resolved[0].status, 'resolved');
    assert.equal(resolved[1].status, 'denied');
    assert.equal(resolved[1].warning, 'Access denied');
});

test('attachment payload contains references but not presentation fields', () => {
    assert.deepEqual(toAttachmentPayload({
        type: 'run', id: '42', label: 'Backup', sublabel: 'failed',
        path: '/jobs/42', runKind: 'job', status: 'resolved',
    }), {
        type: 'run', id: '42', label: 'Backup', run_kind: 'job',
    });
});
