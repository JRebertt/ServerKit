import { Link } from 'react-router-dom';
import { Boxes, Terminal } from 'lucide-react';
import { useResourceTier } from '../contexts/ResourceTierContext';

/**
 * Explains a Dockerless install instead of letting the page fail at click time.
 *
 * The Minimal install profile ships without Docker on purpose. Everything that
 * hosts a workload — containers, services, deployments — needs it, and without
 * this the pages render as if they work and then error on the first action.
 *
 * Fails open: when capacity has not loaded, or the viewer is not an admin (the
 * context only fetches for admins), `canHostApps` is true and children render
 * as normal. A capability probe must never be able to hide a working page.
 */
const RequiresDocker = ({ children, what = 'This page' }) => {
    const { canHostApps, loading, profile, profiles } = useResourceTier();

    if (loading || canHostApps) return children;

    const profileLabel = profiles?.[profile]?.label || 'Minimal';

    return (
        <div className="requires-docker">
            <div className="requires-docker__icon">
                <Boxes size={40} />
            </div>

            <h2 className="requires-docker__title">Docker isn&apos;t available</h2>

            <p className="requires-docker__text">
                {what} needs Docker to run containers, and this server was
                installed with the <strong>{profileLabel}</strong> profile, which
                leaves it out. Nothing is locked — adding Docker turns this page
                on.
            </p>

            <div className="requires-docker__how">
                <div className="requires-docker__how-label">
                    <Terminal size={15} />
                    Install it on the server, then restart ServerKit:
                </div>
                <code className="requires-docker__cmd">
                    curl -fsSL https://get.docker.com | sh
                </code>
                <code className="requires-docker__cmd">
                    sudo systemctl restart serverkit
                </code>
            </div>

            <p className="requires-docker__footnote">
                ServerKit re-checks for Docker automatically. Monitoring, domains,
                certificates, cron and DNS keep working without it — see{' '}
                <Link to="/settings?tab=system">Settings → System</Link> for this
                install&apos;s profile.
            </p>
        </div>
    );
};

export default RequiresDocker;
