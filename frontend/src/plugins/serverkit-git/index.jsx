// Git UI, contributed through the extension system. The full page lives in
// this extension now (pages/Git.jsx + styles/git.scss + its own Gitea API
// client) — plan 52 Phase 6. Imports go through 'serverkit-sdk' so the same
// source works baked in-tree (the panel's build-time glob) and as a
// runtime-ESM bundle once the extension leaves the tree.
//
// Two halves, one page: the Gitea self-host surface calls this extension's
// backend (/api/v1/git status/lifecycle/repos, mounted when installed); the
// webhooks + deployments tabs call the CORE deploy-pipeline endpoints, which
// exist on every panel.
//
// The SCSS side-effect import compiles the page styles through this
// extension's own module graph — the host's main.scss no longer carries a
// _git partial.
import './styles/git.scss';

import GitPage from './pages/Git';

export function GitExtensionPage() {
    return <GitPage basePath="/git" />;
}

// Backward compatibility for older installed manifests that still point
// at GitExtPage. Contribution normalization rewrites those manifests, but
// keeping the export avoids a blank route if stale metadata slips through.
export const GitExtPage = GitExtensionPage;
