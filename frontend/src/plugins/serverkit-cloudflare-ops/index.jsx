// Cloudflare Zone Ops UI, contributed through the extension system. Both
// halves live in this extension: the zone-ops backend (the /api/v1/cloudflare
// blueprint + CloudflareService) under backend/, and the full page here
// (pages/CloudflareZoneSettings.jsx + the WAF/Workers/Tunnels/Storage panels
// + its own API client + SCSS). Imports go through 'serverkit-sdk' so the
// same source works baked in-tree (the panel's build-time glob) and as a
// runtime-ESM bundle once the extension leaves the tree (plan 52 Phase 2).
//
// DNS records and the Cloudflare connection itself stay core (they back
// /domains) — this page only adds the per-zone control panel, reached from
// the "Open in Cloudflare" button on a Cloudflare-managed domain.
//
// It's a single plain full-bleed route (cloudflare/zones/:zoneId, own
// PageTopbar + internal Settings/WAF/Workers/Tunnels/Storage tabs), so no
// tab-group shell or self-rendered sub-router is needed — unlike WordPress.
import './styles/cloudflare-zone.scss';

import CloudflareZoneSettings from './pages/CloudflareZoneSettings';

export function CloudflareZoneSettingsPage() {
    return <CloudflareZoneSettings />;
}

// No default export on purpose: PluginLoader legacy-auto-renders any plugin
// default export globally (the page then runs with zoneId=undefined). The
// route contribution resolves the NAMED export via resolveComponent.
