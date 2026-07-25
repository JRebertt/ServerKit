// Where a service can actually be opened in a browser.
//
// A published domain is the real answer when there is one; this covers the
// other common case — a container with nothing in front of it but a port, which
// the panel used to render as the dead text "Port 3001" with no way to reach it.
export function servicePortUrl(service) {
    if (!service?.port) return null;
    // Running only: linking to a stopped container just produces a refused
    // connection, which reads as the panel being wrong rather than the app
    // being down.
    if (service.status && service.status !== 'running') return null;
    // Apps on a remote server are deliberately excluded. The payload carries
    // `server_name`, which is a label ("Production box"), not a hostname —
    // guessing an address from it would hand out links that quietly fail.
    if (service.server_id) return null;
    // The panel and the container share a host in this case, so whatever host
    // the panel is being viewed on is the one to use. Always http: a bare
    // published port has no certificate.
    return `http://${window.location.hostname}:${service.port}`;
}
