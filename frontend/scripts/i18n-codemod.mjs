#!/usr/bin/env node
// Mechanical i18n conversion, for the long tail.
//
// Converting a 44-file extension by hand is how typos and half-converted files
// get in. This does the four shapes the census counts — and ONLY those, using
// the same `isCopy` rule, so what it converts is exactly what the ratchet
// measures:
//
//   1. JSX text        Save            -> {t('k', 'Save')}
//   2. JSX copy props  label="Save"    -> label={t('k', 'Save')}
//   3. Toast args      toast.error('x')-> toast.error(t('k', 'x'))
//   4. Data copy keys  { label: 'x' }  -> { labelKey: 'k', label: 'x' }
//
// It deliberately REFUSES rather than guesses:
//   * template literals (they need interpolation restructuring by hand);
//   * any hit whose enclosing function is not a component, because the fix
//     there is to thread `t` through a helper's arguments — a design decision,
//     not a rewrite.
// Refusals are printed and left untouched, so the ratchet still sees them.
//
// Usage:
//   node i18n-codemod.mjs --root <dir> --prefix wp [--sdk serverkit-sdk] [--dry]

import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { extname, join, relative, resolve } from 'node:path';
import { parse } from 'espree';

const arg = (name, fallback = null) => (process.argv.includes(name)
    ? process.argv[process.argv.indexOf(name) + 1]
    : fallback);

const rootDir = resolve(process.cwd(), arg('--root', 'src'));
const prefix = arg('--prefix', 'app');
const sdkModule = arg('--sdk', 'react-i18next');
const dry = process.argv.includes('--dry');
const onlyFile = arg('--file');

const COPY_PROPS = new Set([
    'label', 'placeholder', 'title', 'description', 'helpText', 'help',
    'emptyText', 'emptyMessage', 'confirmText', 'cancelText', 'submitText',
    'heading', 'subtitle', 'subheading', 'caption', 'hint', 'tooltip',
    'alt', 'aria-label', 'aria-description', 'aria-placeholder',
    'message', 'text', 'buttonText', 'actionLabel', 'header',
]);
const COPY_KEYS = new Set([
    'label', 'title', 'description', 'placeholder', 'helpText', 'help',
    'emptyText', 'emptyMessage', 'confirmText', 'cancelText', 'submitText',
    'heading', 'subtitle', 'subheading', 'caption', 'hint', 'tooltip',
    'message', 'buttonText', 'actionLabel', 'header', 'summary',
]);
const COPY_CALLS = new Set([
    'success', 'error', 'info', 'warning', 'warn', 'message', 'loading',
    'showToast', 'toast', 'notify', 'confirm', 'alert',
]);
const TOAST_OBJECTS = new Set(['toast', 'toasts', 'sonner', 'notifications']);
const SKIP_DIRS = new Set(['__tests__', '__mocks__', 'node_modules', 'dist']);
const SKIP_FILE = /\.(test|spec|stories)\.[jt]sx?$/;

function isCopy(raw) {
    const value = String(raw).trim();
    if (value.length < 2) return false;
    if (!/[A-Za-z]/.test(value)) return false;
    if (/^https?:\/\//.test(value)) return false;
    if (/^[/#.]/.test(value)) return false;
    if (/^[a-z0-9]+([-_.:][a-z0-9]+)+$/.test(value)) return false;
    if (/^[A-Z0-9]+(_[A-Z0-9]+)*$/.test(value)) return false;
    if (/^[a-z]+$/.test(value)) return false;
    if (/^\{\{.*\}\}$/.test(value)) return false;
    if (/^[a-z][a-zA-Z0-9]*$/.test(value)) return false;
    return /\s/.test(value) || /^[A-Z].{2,}/.test(value);
}

function walk(dir) {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        if (entry.isDirectory()) {
            return SKIP_DIRS.has(entry.name) ? [] : walk(join(dir, entry.name));
        }
        const ext = extname(entry.name);
        if (!['.js', '.jsx'].includes(ext) || SKIP_FILE.test(entry.name)) return [];
        return [join(dir, entry.name)];
    });
}

const camel = (text, words = 6) => text
    .replace(/[^A-Za-z0-9 ]/g, ' ')
    .trim().split(/\s+/).slice(0, words)
    .map((word, i) => (i === 0
        ? word.toLowerCase()
        : word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()))
    .join('') || 'text';

// Newlines need escaping, not just quotes: a placeholder like
// '-----BEGIN OPENSSH PRIVATE KEY-----\n…' carries a real line break, and
// emitting it raw produces an unterminated string literal.
const jsString = (value) => `'${value
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/\n/g, '\\n')
    .replace(/\r/g, '\\r')
    .replace(/\t/g, '\\t')}'`;

function isTranslationCall(node) {
    if (node.type !== 'CallExpression') return false;
    const callee = node.callee;
    if (callee.type === 'Identifier') return callee.name === 't';
    return callee.type === 'MemberExpression' && !callee.computed && callee.property?.name === 't';
}

/** Is this function a React component (uppercase name)? */
function componentName(node, parent) {
    if (node.type === 'FunctionDeclaration' && node.id) return node.id.name;
    if (parent?.type === 'VariableDeclarator' && parent.id?.type === 'Identifier') {
        return parent.id.name;
    }
    if (parent?.type === 'ExportDefaultDeclaration') return 'default';
    return null;
}


/**
 * A template literal becomes ONE key with named placeholders:
 *
 *     `Deployment failed: ${err.message}`
 *   -> t('k', 'Deployment failed: {{message}}', { message: err.message })
 *
 * One key, not a prefix/suffix pair, because the value lands in a different
 * place in other languages. Placeholder names come from the expression itself
 * (`err.message` -> message) so the translator sees something meaningful.
 */
function templateToKeyed(node, source, keyFor, camelFn, jsStringFn) {
    const names = new Map();
    const nameFor = (expr, index) => {
        let base = 'value';
        if (expr.type === 'Identifier') base = expr.name;
        else if (expr.type === 'MemberExpression' && !expr.computed && expr.property?.name) {
            base = expr.property.name;
        }
        base = base.replace(/[^A-Za-z0-9]/g, '') || 'value';
        let name = base;
        let n = 2;
        while (names.has(name)) { name = `${base}${n}`; n += 1; }
        names.set(name, source.slice(expr.range[0], expr.range[1]));
        return name;
    };

    let pattern = '';
    node.quasis.forEach((quasi, i) => {
        pattern += quasi.value.cooked ?? '';
        if (i < node.expressions.length) pattern += `{{${nameFor(node.expressions[i], i)}}}`;
    });
    pattern = pattern.replace(/\s+/g, ' ').trim();

    // Nothing readable outside the placeholders — not copy, leave it alone.
    const literalPart = node.quasis.map((q) => q.value.cooked ?? '').join(' ').trim();
    if (!literalPart || literalPart.length < 3 || !/[A-Za-z]{3}/.test(literalPart)) return null;

    const values = [...names].map(([name, expr]) => `${name}: ${expr}`).join(', ');
    return `t(${jsStringFn(keyFor(literalPart))}, ${jsStringFn(pattern)}, { ${values} })`;
}

let converted = 0;
let refused = 0;
const refusals = [];
const filesTouched = [];

for (const path of walk(rootDir)) {
    const rel = relative(rootDir, path).replaceAll('\\', '/');
    if (onlyFile && !rel.endsWith(onlyFile)) continue;

    const source = readFileSync(path, 'utf8');
    let ast;
    try {
        ast = parse(source, {
            ecmaVersion: 'latest', sourceType: 'module',
            ecmaFeatures: { jsx: true }, loc: true, range: true,
        });
    } catch (error) {
        refusals.push(`${rel}: parse failed — ${error.message}`);
        continue;
    }

    // Keep the file's own camelCase — `camel()` would flatten WordPressSiteCard
    // to "wordpresssitecard", and a key nobody can read is a key nobody reuses.
    const base = rel.split('/').pop().replace(/\.[jt]sx?$/, '');
    const fileSlug = base.charAt(0).toLowerCase() + base.slice(1).replace(/[^A-Za-z0-9]/g, '');
    const used = new Map();
    const keyFor = (text) => {
        const base = `${prefix}.${fileSlug}.${camel(text)}`;
        const seen = used.get(base) || 0;
        used.set(base, seen + 1);
        return seen ? `${base}${seen + 1}` : base;
    };

    const edits = [];
    const hookInto = new Set();      // function nodes needing `const { t } = …`
    const stack = [];                // [{node, name}] innermost last

    const enclosingComponent = () => {
        for (let i = stack.length - 1; i >= 0; i -= 1) {
            const frame = stack[i];
            if (frame.name && /^[A-Z]/.test(frame.name)) return frame;
            if (frame.name === 'default') return frame;
        }
        return null;
    };

    const record = (node, text, replacement, needsHook = true) => {
        if (!isCopy(text)) return;
        if (needsHook) {
            const frame = enclosingComponent();
            if (!frame) {
                refused += 1;
                refusals.push(`${rel}:${node.loc.start.line}: "${text.trim().slice(0, 40)}" is outside a component — thread \`t\` through by hand`);
                return;
            }
            hookInto.add(frame.node);
        }
        edits.push({ start: node.range[0], end: node.range[1], text: replacement });
        converted += 1;
    };

    /**
     * Key every copy string inside an expression, in place.
     *
     * Copy hides in `err.message || 'Failed…'` and `x ? 'A' : 'B'` as often as
     * it sits directly in a call or prop. Replacing each literal in place keeps
     * the surrounding expression intact.
     *
     * It stops at nested JSX: a `title={cond ? 'A' : <b rel="noopener">}` must
     * not have the nested element's OWN attributes rewritten — `rel` is not
     * copy, and the outer walk reaches that element on its own terms anyway.
     */
    const keyStringsIn = (expr) => {
        if (!expr || typeof expr !== 'object') return;
        if (Array.isArray(expr)) { expr.forEach(keyStringsIn); return; }
        if (!expr.type || isTranslationCall(expr)) return;
        if (expr.type.startsWith('JSXElement') || expr.type === 'JSXFragment') return;
        if (expr.type === 'Literal' && typeof expr.value === 'string' && isCopy(expr.value)) {
            record(expr, expr.value,
                `t(${jsString(keyFor(expr.value))}, ${jsString(expr.value)})`);
            return;
        }
        if (expr.type === 'TemplateLiteral') {
            const keyed = templateToKeyed(expr, source, keyFor, camel, jsString);
            if (keyed) {
                const literal = expr.quasis.map((q) => q.value.cooked ?? '').join(' ').trim();
                record(expr, literal, keyed);
            }
            return;
        }
        for (const key of Object.keys(expr)) {
            if (['type', 'loc', 'range', 'parent'].includes(key)) continue;
            keyStringsIn(expr[key]);
        }
    };

    const visit = (node, parent) => {
        if (!node || typeof node !== 'object') return;
        if (Array.isArray(node)) { for (const child of node) visit(child, parent); return; }
        if (!node.type) return;
        if (isTranslationCall(node)) return;

        const isFn = ['FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression']
            .includes(node.type);
        if (isFn) stack.push({ node, name: componentName(node, parent) });

        switch (node.type) {
            case 'JSXText': {
                const text = node.value;
                const trimmed = text.trim();
                if (isCopy(trimmed)) {
                    const lead = text.slice(0, text.indexOf(trimmed.charAt(0)));
                    const tail = text.slice(lead.length + trimmed.length);
                    // JSX collapses internal whitespace at render, so a default
                    // spanning source lines must be collapsed too — emitting the
                    // raw text would put literal newlines inside a quoted string
                    // and fail to parse.
                    const flat = trimmed.replace(/\s+/g, ' ');
                    record(node, flat,
                        `${lead}{t(${jsString(keyFor(flat))}, ${jsString(flat)})}${tail}`);
                }
                break;
            }
            case 'JSXAttribute': {
                const name = node.name?.type === 'JSXNamespacedName'
                    ? `${node.name.namespace.name}:${node.name.name.name}`
                    : node.name?.name;
                if (name && COPY_PROPS.has(name)
                    && node.value?.type === 'Literal' && typeof node.value.value === 'string'
                    && isCopy(node.value.value)) {
                    const text = node.value.value;
                    record(node.value, text,
                        `{t(${jsString(keyFor(text))}, ${jsString(text)})}`);
                } else if (name && COPY_PROPS.has(name)
                    && node.value?.type === 'JSXExpressionContainer') {
                    keyStringsIn(node.value.expression);
                }
                break;
            }
            case 'CallExpression': {
                const callee = node.callee;
                const name = callee.type === 'Identifier' ? callee.name
                    : (callee.type === 'MemberExpression' && !callee.computed
                        ? callee.property?.name : null);
                const object = callee.type === 'MemberExpression'
                    && callee.object?.type === 'Identifier' ? callee.object.name : null;
                if (name && COPY_CALLS.has(name)
                    && (object === null || TOAST_OBJECTS.has(object) || name === 'confirm')) {
                    // See keyStringsIn above.
                    node.arguments.forEach(keyStringsIn);
                }
                break;
            }
            case 'Property': {
                if (node.computed) break;
                const key = node.key?.name
                    || (typeof node.key?.value === 'string' ? node.key.value : null);
                if (key && COPY_KEYS.has(key)
                    && node.value?.type === 'Literal' && typeof node.value.value === 'string'
                    && isCopy(node.value.value)) {
                    // Declarative pair — no hook needed, it resolves at render.
                    const text = node.value.value;
                    record(node, text,
                        `${key}Key: ${jsString(keyFor(text))}, ${key}: ${jsString(text)}`,
                        false);
                    if (isFn) stack.pop();
                    return;   // do not descend; the whole property is replaced
                }
                break;
            }
            default: break;
        }

        for (const key of Object.keys(node)) {
            if (['type', 'loc', 'range', 'parent'].includes(key)) continue;
            visit(node[key], node);
        }
        if (isFn) stack.pop();
    };

    visit(ast, null);
    if (!edits.length) continue;

    // Hook lines, innermost-first so ranges stay valid.
    for (const fn of hookInto) {
        const body = fn.body;
        if (body.type !== 'BlockStatement') {
            refusals.push(`${rel}: component with an expression body needs \`t\` by hand`);
            continue;
        }
        edits.push({
            start: body.range[0] + 1, end: body.range[0] + 1,
            text: '\n    const { t } = useTranslation();',
        });
    }

    // Two rules can claim the same source range — `confirm({ title: 'x' })`
    // matches BOTH the data-object rule (declarative pair) and the copy-call
    // rule (inner t()). Applying both corrupts the file, so keep the INNERMOST:
    // for a call, `t()` is the right answer because nothing resolves a
    // `titleKey` there. A genuine data object never overlaps, since the
    // recursive rule only runs inside a copy call.
    const kept = [];
    for (const edit of [...edits].sort((a, b) => (a.end - a.start) - (b.end - b.start))) {
        const overlaps = kept.some((k) => edit.start < k.end && k.start < edit.end);
        if (!overlaps) kept.push(edit);
    }

    let output = source;
    for (const edit of kept.sort((a, b) => b.start - a.start)) {
        output = output.slice(0, edit.start) + edit.text + output.slice(edit.end);
    }

    if (!/useTranslation/.test(source)) {
        const lastImport = [...output.matchAll(/^import .*?;$/gm)].pop();
        const line = `import { useTranslation } from '${sdkModule}';`;
        output = lastImport
            ? output.slice(0, lastImport.index + lastImport[0].length) + `\n${line}`
                + output.slice(lastImport.index + lastImport[0].length)
            : `${line}\n${output}`;
    }

    filesTouched.push(rel);
    if (!dry) writeFileSync(path, output);
}

for (const refusal of refusals) console.log(`  REFUSED ${refusal}`);
console.log(`\n${dry ? '[dry] ' : ''}${converted} literals keyed across ${filesTouched.length} files; ${refused} refused.`);
