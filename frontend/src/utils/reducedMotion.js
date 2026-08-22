/**
 * prefers-reduced-motion for imperative (JS) callers.
 *
 * CSS transitions/animations are already neutralized globally in
 * styles/base/_reset.scss, but JS-driven scrolling bypasses stylesheets —
 * so scroll calls ask here instead of hardcoding `behavior: 'smooth'`.
 */
export function prefersReducedMotion() {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function scrollBehavior() {
    return prefersReducedMotion() ? 'auto' : 'smooth';
}
