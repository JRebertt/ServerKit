// The extension's own Gitea self-host client (/api/v1/git/* — server
// lifecycle + repo browsing), built on the panel's ApiClient via the SDK
// singleton — moved out of the host's services/api/files.js with the Git
// page (plan 52 Phase 6). The webhook + deployment endpoints stay CORE
// (they are the deploy pipeline); the page calls those through the core
// `api` object from serverkit-sdk.
import { api } from 'serverkit-sdk';

const giteaApi = {
    // Server lifecycle
    getGitServerStatus: () => api.request('/git/status'),
    getGitRequirements: () => api.request('/git/requirements'),
    installGit: (data) => api.request('/git/install', { method: 'POST', body: data }),
    uninstallGit: (removeData = false) => api.request('/git/uninstall', { method: 'POST', body: { removeData } }),
    startGit: () => api.request('/git/start', { method: 'POST' }),
    stopGit: () => api.request('/git/stop', { method: 'POST' }),
    restartGit: () => api.request('/git/restart', { method: 'POST' }),

    // Repositories
    getRepositories: (limit = 50) => api.request(`/git/repos?limit=${limit}`),
    getRepository: (owner, repo) => api.request(`/git/repos/${owner}/${repo}`),
    getRepoStats: (owner, repo) => api.request(`/git/repos/${owner}/${repo}/stats`),
    getBranches: (owner, repo) => api.request(`/git/repos/${owner}/${repo}/branches`),
    getBranch: (owner, repo, branch) => api.request(`/git/repos/${owner}/${repo}/branches/${branch}`),
    getCommits: (owner, repo, branch = null, page = 1, limit = 30) => {
        let url = `/git/repos/${owner}/${repo}/commits?page=${page}&limit=${limit}`;
        if (branch) url += `&branch=${branch}`;
        return api.request(url);
    },
    getCommit: (owner, repo, sha) => api.request(`/git/repos/${owner}/${repo}/commits/${sha}`),
    getRepoFiles: (owner, repo, ref = 'main', path = '') => {
        let url = `/git/repos/${owner}/${repo}/contents?ref=${ref}`;
        if (path) url += `&path=${path}`;
        return api.request(url);
    },
    getFileContent: (owner, repo, filepath, ref = 'main') => api.request(`/git/repos/${owner}/${repo}/contents/${filepath}?ref=${ref}`),
    getRepoReadme: (owner, repo, ref = null) => {
        let url = `/git/repos/${owner}/${repo}/readme`;
        if (ref) url += `?ref=${ref}`;
        return api.request(url);
    },
    getGiteaVersion: () => api.request('/git/version'),
};

export default giteaApi;
