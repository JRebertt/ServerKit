export const WALKTHROUGH_COMPLETION_TYPES = Object.freeze([
    { value: 'manual', key: 'walkthroughStudio.completionManual', fallback: 'Manual confirmation' },
    { value: 'route', key: 'walkthroughStudio.completionRouteReached', fallback: 'Route reached' },
    { value: 'signal', key: 'walkthroughStudio.completionSignal', fallback: 'Success signal received' },
    { value: 'check', key: 'walkthroughStudio.completionCheck', fallback: 'Named status check' },
    { value: 'target', key: 'walkthroughStudio.completionTarget', fallback: 'Target becomes visible' },
]);

export const WALKTHROUGH_LIBRARY_EVENT = 'serverkit:walkthrough-library-changed';
export const WALKTHROUGH_SIGNAL_EVENT = 'serverkit:walkthrough-signal';

const ID_RE = /^[a-z0-9][a-z0-9._-]{0,79}$/;
const TOKEN_RE = /^[a-z0-9][a-z0-9._:-]{0,119}$/;
const TARGET_RE = /^[a-z0-9][a-z0-9._:-]{0,79}$/;
const COMPLETION_TYPES = new Set(WALKTHROUGH_COMPLETION_TYPES.map((item) => item.value));
const GUIDE_FIELDS = new Set([
    '$schema', 'plugin', 'id', 'title', 'title_key', 'titleKey', 'description',
    'description_key', 'descriptionKey', 'duration', 'duration_key', 'durationKey',
    'icon', 'tone', 'secondary', 'permissions', 'steps',
]);
const STEP_FIELDS = new Set([
    'id', 'title', 'title_key', 'titleKey', 'description', 'description_key',
    'descriptionKey', 'action', 'action_key', 'actionKey', 'path', 'target',
    'completion', 'route', 'signal', 'check',
]);
const COMPLETION_FIELDS = new Set(['type', 'path', 'signal', 'check']);

function text(value) {
    return typeof value === 'string' ? value.trim() : '';
}

function translated(translator, key, fallback) {
    const cleanKey = text(key);
    return cleanKey && translator ? translator(cleanKey, fallback) : fallback;
}

function issue(path, message) {
    return { path, message };
}

export function validateWalkthroughDefinition(definition) {
    const issues = [];
    if (!definition || typeof definition !== 'object' || Array.isArray(definition)) {
        return [issue('', 'Walkthrough must be an object.')];
    }

    const unknownGuideFields = Object.keys(definition).filter((key) => !GUIDE_FIELDS.has(key));
    if (unknownGuideFields.length) {
        issues.push(issue('', `Unsupported fields: ${unknownGuideFields.join(', ')}.`));
    }

    if (!ID_RE.test(text(definition.id))) issues.push(issue('id', 'Use a stable lowercase id.'));
    if (!text(definition.title)) issues.push(issue('title', 'Title is required.'));
    if (text(definition.title).length > 120) issues.push(issue('title', 'Title is too long.'));
    if (!text(definition.description)) issues.push(issue('description', 'Description is required.'));
    if (text(definition.description).length > 320) issues.push(issue('description', 'Description is too long.'));
    if (definition.permissions != null && !Array.isArray(definition.permissions)) {
        issues.push(issue('permissions', 'Permissions must be a list.'));
    } else {
        (definition.permissions || []).forEach((permission, index) => {
            if (!text(permission?.feature)) issues.push(issue(`permissions.${index}.feature`, 'Feature is required.'));
            if (!['read', 'write', 'admin'].includes(permission?.level)) {
                issues.push(issue(`permissions.${index}.level`, 'Choose read, write, or admin.'));
            }
        });
    }
    if (!Array.isArray(definition.steps) || definition.steps.length === 0) {
        issues.push(issue('steps', 'Add at least one step.'));
        return issues;
    }
    if (definition.steps.length > 32) issues.push(issue('steps', 'A walkthrough can have at most 32 steps.'));

    const stepIds = new Set();
    definition.steps.forEach((step, index) => {
        const base = `steps.${index}`;
        if (!step || typeof step !== 'object' || Array.isArray(step)) {
            issues.push(issue(base, 'Step must be an object.'));
            return;
        }
        const unknownStepFields = Object.keys(step).filter((key) => !STEP_FIELDS.has(key));
        if (unknownStepFields.length) {
            issues.push(issue(base, `Unsupported fields: ${unknownStepFields.join(', ')}.`));
        }
        const stepId = text(step.id);
        if (!ID_RE.test(stepId)) issues.push(issue(`${base}.id`, 'Use a stable lowercase step id.'));
        if (stepIds.has(stepId)) issues.push(issue(`${base}.id`, 'Step ids must be unique.'));
        stepIds.add(stepId);
        if (!text(step.title)) issues.push(issue(`${base}.title`, 'Step title is required.'));
        if (!text(step.description)) issues.push(issue(`${base}.description`, 'Step description is required.'));
        if (step.path && !text(step.path).startsWith('/')) {
            issues.push(issue(`${base}.path`, 'Paths must begin with /.'));
        }
        if (step.target && !TARGET_RE.test(text(step.target))) {
            issues.push(issue(`${base}.target`, 'Use a data-walkthrough token, not a CSS selector.'));
        }

        const completion = step.completion || { type: 'manual' };
        if (!completion || typeof completion !== 'object' || Array.isArray(completion)) {
            issues.push(issue(`${base}.completion`, 'Completion must be an object.'));
            return;
        }
        const unknownCompletionFields = Object.keys(completion)
            .filter((key) => !COMPLETION_FIELDS.has(key));
        if (unknownCompletionFields.length) {
            issues.push(issue(
                `${base}.completion`,
                `Unsupported fields: ${unknownCompletionFields.join(', ')}.`,
            ));
        }
        const completionType = text(completion.type) || 'manual';
        if (!COMPLETION_TYPES.has(completionType)) {
            issues.push(issue(`${base}.completion.type`, 'Choose a supported completion type.'));
        } else if (completionType === 'route') {
            const path = text(completion.path) || text(step.path);
            if (!path.startsWith('/')) issues.push(issue(`${base}.completion.path`, 'Route completion needs a path.'));
        } else if (completionType === 'signal' && !TOKEN_RE.test(text(completion.signal))) {
            issues.push(issue(`${base}.completion.signal`, 'Signal completion needs a stable event token.'));
        } else if (completionType === 'check' && !TOKEN_RE.test(text(completion.check))) {
            issues.push(issue(`${base}.completion.check`, 'Check completion needs a named host check.'));
        } else if (completionType === 'target' && !text(step.target)) {
            issues.push(issue(`${base}.target`, 'Target completion needs a target token.'));
        }
    });

    return issues;
}

function completionFor(step) {
    if (step.completion && typeof step.completion === 'object') return step.completion;
    if (step.signal) return { type: 'signal', signal: step.signal };
    if (step.check) return { type: 'check', check: step.check };
    if (step.route) return { type: 'route', path: step.route };
    return { type: 'manual' };
}

function targetSelector(target) {
    const token = text(target);
    if (!token) return null;
    if (token.startsWith('[data-walkthrough=')) return token;
    return TARGET_RE.test(token) ? `[data-walkthrough="${token}"]` : null;
}

export function normalizeWalkthroughDefinition(definition, {
    plugin = definition?.plugin || null,
    source = plugin ? 'extension' : 'custom',
    t = null,
} = {}) {
    if (validateWalkthroughDefinition(definition).length > 0) return null;
    const rawId = text(definition.id);
    const namespace = plugin || (source === 'custom' ? 'custom' : null);
    const id = namespace && !rawId.startsWith(`${namespace}.`)
        ? `${namespace}.${rawId}`
        : rawId;
    if (!ID_RE.test(id)) return null;

    const steps = definition.steps.map((step) => {
        const completion = completionFor(step);
        const completionType = completion.type || 'manual';
        const path = text(step.path) || null;
        const normalized = {
            id: text(step.id),
            title: translated(t, step.title_key || step.titleKey, text(step.title)),
            description: translated(
                t,
                step.description_key || step.descriptionKey,
                text(step.description),
            ),
            action: translated(
                t,
                step.action_key || step.actionKey,
                text(step.action) || (path ? 'Open' : 'Continue'),
            ),
            path,
            target: targetSelector(step.target),
            completionType,
        };
        if (completionType === 'route') normalized.route = text(completion.path) || path;
        if (completionType === 'signal') normalized.signal = text(completion.signal);
        if (completionType === 'check') normalized.check = text(completion.check);
        if (completionType === 'target') normalized.completeWhenTargetVisible = true;
        return normalized;
    });

    return {
        id,
        definitionId: rawId,
        icon: text(definition.icon) || 'guide',
        tone: text(definition.tone) || 'cyan',
        secondary: definition.secondary !== false,
        title: translated(t, definition.title_key || definition.titleKey, text(definition.title)),
        description: translated(
            t,
            definition.description_key || definition.descriptionKey,
            text(definition.description),
        ),
        duration: translated(
            t,
            definition.duration_key || definition.durationKey,
            text(definition.duration) || `${steps.length} steps`,
        ),
        permissions: Array.isArray(definition.permissions) ? definition.permissions : [],
        steps,
        origin: { source, plugin },
    };
}

export function buildWalkthroughRegistry({ core = [], contributed = [], custom = [], t = null }) {
    const walkthroughs = [...core];
    const seen = new Set(core.map((guide) => guide.id));

    const append = (definitions, source) => {
        for (const definition of definitions || []) {
            const guide = normalizeWalkthroughDefinition(definition, {
                plugin: source === 'extension' ? definition?.plugin : null,
                source,
                t,
            });
            if (!guide || seen.has(guide.id)) continue;
            seen.add(guide.id);
            walkthroughs.push(guide);
        }
    };

    append(contributed, 'extension');
    append(custom, 'custom');
    return {
        walkthroughs,
        byId: Object.fromEntries(walkthroughs.map((guide) => [guide.id, guide])),
    };
}

export function emitWalkthroughSignal(type, detail = {}) {
    if (!TOKEN_RE.test(text(type)) || typeof window === 'undefined') return false;
    window.dispatchEvent(new CustomEvent(WALKTHROUGH_SIGNAL_EVENT, {
        detail: { ...detail, type },
    }));
    return true;
}

export function notifyWalkthroughLibraryChanged() {
    if (typeof window === 'undefined') return;
    window.dispatchEvent(new Event(WALKTHROUGH_LIBRARY_EVENT));
}
