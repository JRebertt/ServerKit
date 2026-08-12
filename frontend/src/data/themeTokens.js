// ============================================
// ServerKit theme token whitelist + alias table + validators
// ============================================
// A ServerKit theme is DATA, not code (see docs/THEMING.md and plan 60): a map
// of canonical CSS custom-property names to values. This module is the single
// client-side source of truth for
//   - which token names a theme may set (the whitelist),
//   - how canonical names expand to the legacy `--bg-*/--text-*/--border-*`
//     aliases the stylesheet still reads (the alias table), and
//   - what a token's value may look like (the validators).
//
// KEEP IN SYNC with backend/app/services/theme_tokens.py — the backend runs the
// same whitelist + validation server-side on import and registry install.
//
// Accent tokens (--accent*, --accent-primary, …) are intentionally NOT in the
// whitelist: they are derived at runtime from a theme's single `accent` field
// by ThemeContext.applyAccentToDOM, so a workspace/user accent keeps precedence.

// Canonical writable tokens, grouped for the Theme Studio color-picker UI.
// Authors write these ~37 names; the alias table below fans each out to the
// legacy names so all ~60 theme-sensitive stylesheet variables get painted.
export const TOKEN_GROUPS = {
    surfaces: ['--bg-body', '--bg-sidebar', '--surface-0', '--surface', '--surface-2', '--surface-3', '--surface-hover'],
    borders: ['--border', '--border-soft', '--border-strong'],
    text: ['--text', '--text-dim', '--text-faint', '--text-ghost'],
    semantic: ['--green', '--green-bg', '--amber', '--amber-bg', '--red', '--red-bg', '--cyan', '--cyan-bg', '--violet', '--violet-bg'],
    radius: ['--radius', '--radius-sm', '--radius-lg'],
    fonts: ['--sans', '--mono'],
    shadows: ['--shadow-sm', '--shadow-md', '--shadow-lg'],
    scrollbar: ['--scrollbar-track', '--scrollbar-thumb', '--scrollbar-thumb-hover'],
    code: ['--bg-code', '--text-code'],
    chrome: ['--grid-color'],
};

// Human labels for each group (Theme Studio section headers).
export const GROUP_LABELS = {
    surfaces: 'Surfaces',
    borders: 'Borders',
    text: 'Text',
    semantic: 'Semantic colors',
    radius: 'Radius',
    fonts: 'Fonts',
    shadows: 'Shadows',
    scrollbar: 'Scrollbar',
    code: 'Code / terminal',
    chrome: 'Chrome',
};

// Which validator applies to each group.
const GROUP_TYPE = {
    surfaces: 'color',
    borders: 'color',
    text: 'color',
    semantic: 'color',
    radius: 'length',
    fonts: 'font',
    shadows: 'shadow',
    scrollbar: 'color',
    code: 'color',
    chrome: 'color',
};

// Flat whitelist + token -> value-type index.
export const CANONICAL_TOKENS = Object.values(TOKEN_GROUPS).flat();

export const TOKEN_TYPE = (() => {
    const out = {};
    for (const [group, tokens] of Object.entries(TOKEN_GROUPS)) {
        for (const t of tokens) out[t] = GROUP_TYPE[group];
    }
    return out;
})();

// Canonical name -> legacy names that must receive the same value. Applying a
// canonical token also sets its aliases so pages still reading `$bg-card` etc.
// (which resolve to the legacy custom properties) track the skin.
export const ALIAS_MAP = {
    '--surface': ['--bg-card'],
    '--surface-2': ['--bg-elevated', '--bg-secondary'],
    '--surface-3': ['--bg-tertiary'],
    '--surface-hover': ['--bg-hover'],
    '--border': ['--border-default'],
    '--border-soft': ['--border-subtle'],
    '--border-strong': ['--border-active', '--border-hover'],
    '--text': ['--text-primary'],
    '--text-dim': ['--text-secondary'],
    '--text-faint': ['--text-tertiary'],
};

// Every property name a skin may ever set (canonical + aliases). Used to clear
// a previous skin cleanly before applying the next one — never touches accent.
export const ALL_SKIN_PROPERTIES = [
    ...CANONICAL_TOKENS,
    ...Object.values(ALIAS_MAP).flat(),
];

// --------------------------------------------
// Value validation
// --------------------------------------------
// Reject anything that could break out of a single CSS declaration or smuggle a
// network fetch / script. Even though we apply per-token via setProperty (which
// the browser sanitises), this keeps the stored/exported theme.json clean and
// makes the same rules enforceable server-side and in the registry CI.
const FORBIDDEN = /url\(|expression\(|javascript:|@import|[@;{}<>]|\/\*/i;

const HEX = /^#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;
const FUNC_COLOR = /^(rgb|rgba|hsl|hsla)\(\s*[0-9.,%\s/]+\)$/i;
const NAMED_COLOR = /^[a-zA-Z]{3,24}$/; // transparent, currentColor, white, …
const LENGTH = /^-?(?:0|\d*\.?\d+)(px|rem|em|%|vh|vw)?$/;
const FONT_STACK = /^[a-zA-Z0-9 ,"'-]{1,200}$/;
const SHADOW = /^[0-9a-zA-Z.,%()#\s/-]{1,200}$/; // numbers, rgba(), inset, none

function isColor(v) {
    return HEX.test(v) || FUNC_COLOR.test(v) || NAMED_COLOR.test(v);
}

const VALIDATORS = {
    color: isColor,
    length: (v) => LENGTH.test(v),
    font: (v) => FONT_STACK.test(v),
    shadow: (v) => SHADOW.test(v) || v === 'none',
};

/**
 * Validate a single token value. Returns the trimmed value if the token is
 * whitelisted and the value passes its type check (and contains no forbidden
 * substring), otherwise null.
 */
export function validateTokenValue(token, value) {
    const type = TOKEN_TYPE[token];
    if (!type) return null;                       // not whitelisted
    if (typeof value !== 'string') return null;
    const v = value.trim();
    if (!v || v.length > 200) return null;
    if (FORBIDDEN.test(v)) return null;
    return VALIDATORS[type](v) ? v : null;
}

/**
 * Drop unknown / invalid entries from a raw token map, returning only the
 * whitelisted, validated canonical tokens. Unknown keys degrade gracefully
 * (forward-compat: a newer theme on an older panel just loses the new tokens).
 */
export function sanitizeTokens(raw) {
    const out = {};
    if (!raw || typeof raw !== 'object') return out;
    for (const [token, value] of Object.entries(raw)) {
        const clean = validateTokenValue(token, value);
        if (clean !== null) out[token] = clean;
    }
    return out;
}

/**
 * Expand a validated canonical token map to include its legacy aliases, ready
 * to hand to setProperty. Canonical values win over any alias collision.
 */
export function expandAliases(cleanTokens) {
    const out = { ...cleanTokens };
    for (const [token, value] of Object.entries(cleanTokens)) {
        for (const alias of ALIAS_MAP[token] || []) {
            if (!(alias in cleanTokens)) out[alias] = value;
        }
    }
    return out;
}
