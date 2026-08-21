// statusInfo.dotClass → ds Pill kind now comes from the ONE shared status
// vocabulary — import { statusKind } from '@/components/ds/status'.

// Ingress plane → label + Pill kind. Host Nginx is the neutral default;
// a managed proxy stack reads as the accent (cyan) choice. NULL/undefined
// reads as host Nginx, matching the backend.
export const INGRESS_META = {
    proxy_stack: { labelKey: 'app.appDetailShared.proxyStack', label: 'Proxy stack', kind: 'cyan' },
    nginx: { labelKey: 'app.appDetailShared.nginx', label: 'Nginx', kind: 'gray' },
};
