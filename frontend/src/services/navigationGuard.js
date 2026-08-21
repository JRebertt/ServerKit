export function internalNavigationTarget(event, location) {
    if (event.defaultPrevented || event.button !== 0
            || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
    const anchor = event.target?.closest?.('a[href]');
    if (!anchor || anchor.target || anchor.hasAttribute('download')) return null;
    const url = new URL(anchor.href, location.href);
    if (url.origin !== location.origin) return null;
    const destination = `${url.pathname}${url.search}${url.hash}`;
    const current = `${location.pathname}${location.search}${location.hash}`;
    return destination === current ? null : destination;
}
