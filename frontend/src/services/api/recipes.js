// Recipe registry API (the serverkit-recipes catalog) + run start.
// Browsing is read-only and offline-tolerant on the backend (bundled index
// fallback); starting a run is the same admin-gated deployment job surface as
// any other operation.

// Browse the curated catalog. Returns { recipes: [...], source }.
export async function getRecipeRegistry() {
    return this.request('/recipes/registry');
}

// One catalog entry + its full executable manifest text.
export async function getRecipeRegistryEntry(slug) {
    return this.request(`/recipes/registry/${encodeURIComponent(slug)}`);
}

// Start a recipe run. Body: { registry_slug | content | manifest,
// server_id | project_id, params?, slug?, title? }. Secret inputs are NOT
// params — they arrive as mid-run handoffs.
export async function startRecipeRun(body) {
    return this.request('/recipes/runs', { method: 'POST', body });
}
