export async function getWalkthroughState() {
    return this.request('/walkthroughs/state');
}

export async function updateWalkthroughState(state) {
    return this.request('/walkthroughs/state', {
        method: 'PUT',
        body: { state },
    });
}
