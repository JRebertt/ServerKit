// Unified entity omnisearch (plan 41, Phase 4).
export async function search(q) {
    const response = await this.request(`/search?q=${encodeURIComponent(q)}`);
    return {
        ...response,
        // The backend keeps `results` during the public API migration. Prefer
        // the canonical envelope here so the browser exercises the new path.
        results: response?.data ?? response?.results ?? [],
    };
}
