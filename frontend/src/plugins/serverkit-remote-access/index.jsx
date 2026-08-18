// Remote Access (fleet-wide WireGuard tunnels), contributed through the
// extension system. The page component and its /api/v1/tunnels backend stay in
// core for now (two-speed extraction, D2) — the page is ALSO embedded by the
// core server detail screen (<RemoteAccess serverId={…}/>), which keeps working
// regardless of this extension's install state. This extension owns the
// fleet-wide tab in the core Servers group via a tab-group contribution (#43)
// plus the route/palette entries in its manifest.
//
// After sync this file lives at frontend/src/plugins/serverkit-remote-access/
// so the relative import resolves against the host's pages directory.
import './styles/remote-access.scss';
import RemoteAccess from '../../pages/RemoteAccess';

export function RemoteAccessPage() {
    return <RemoteAccess />;
}
