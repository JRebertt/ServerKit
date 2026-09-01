export async function getWalkthroughState() {
    return this.request('/walkthroughs/state');
}

export async function updateWalkthroughState(state) {
    return this.request('/walkthroughs/state', {
        method: 'PUT',
        body: { state },
    });
}

export async function getWalkthroughDefinitions() {
    return this.request('/walkthroughs/definitions');
}

export async function updateWalkthroughDefinitions(definitions) {
    return this.request('/walkthroughs/definitions', {
        method: 'PUT',
        body: { definitions },
    });
}
