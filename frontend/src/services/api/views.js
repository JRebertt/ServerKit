// Saved table views API — per-user named table states (filter/search/sort/
// columns/page-size) for list pages, with one default per page.

// List the current user's views for a page ('services', 'domains', …).
export async function getViews(page) {
    return this.request(`/views?page=${encodeURIComponent(page)}`);
}

// Save a new view: { page, name, state, is_default? }.
export async function createView(view) {
    return this.request('/views', { method: 'POST', body: JSON.stringify(view) });
}

// Rename / restate / (un)default a view: { name?, state?, is_default? }.
export async function updateView(id, patch) {
    return this.request(`/views/${id}`, { method: 'PUT', body: JSON.stringify(patch) });
}

export async function deleteView(id) {
    return this.request(`/views/${id}`, { method: 'DELETE' });
}
