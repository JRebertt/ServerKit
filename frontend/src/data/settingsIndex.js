// Searchable settings index (plan 41, Phase 2). Every meaningful settings card
// or field — not just the tab — becomes a palette result that lands you on the
// exact card via `/settings/<tab>?focus=setting:<id>` (see hooks/useSettingFocus).
//
// Shape: { id, label, description, keywords, tab, adminOnly }. `id` is unique
// across the whole index and is the value carried in the `?focus=setting:<id>`
// deep link. `adminOnly` mirrors the tab's gate in pages/Settings.jsx so a
// member never finds an admin-only card here.
//
// Completeness is enforced at lint time by scripts/check-settings-index.mjs:
// every settings tab must have at least one entry, so a new tab can't ship
// invisible to search.

export const SETTINGS_INDEX = [
    { id: 'profile-username', label: 'Update username', description: 'Change your account username', keywords: 'name account profile', tab: 'profile', adminOnly: false },
    { id: 'profile-email', label: 'Update email address', description: 'Change your account email', keywords: 'email contact', tab: 'profile', adminOnly: false },

    { id: 'security-password', label: 'Change password', description: 'Update your account password', keywords: 'password login authentication', tab: 'security', adminOnly: false },
    { id: 'security-2fa', label: 'Two-factor authentication', description: 'Enable or disable 2FA for your account with an authenticator app', keywords: '2fa mfa otp totp authenticator two factor', tab: 'security', adminOnly: false },
    { id: 'security-2fa-policy', label: 'Require two-factor for all members', description: 'Enforce 2FA across every account', keywords: '2fa mfa policy require enforce members', tab: 'security', adminOnly: true },
    { id: 'security-backup-codes', label: 'Backup codes', description: 'Regenerate or download backup codes for 2FA recovery', keywords: 'backup codes recovery 2fa', tab: 'security', adminOnly: false },
    { id: 'security-sessions', label: 'Active sessions', description: 'View and manage your active login sessions', keywords: 'sessions login devices', tab: 'security', adminOnly: false },
    { id: 'security-linked-accounts', label: 'Linked accounts', description: 'Connect or disconnect SSO identity providers to your account', keywords: 'sso oauth github google linked accounts', tab: 'security', adminOnly: false },

    { id: 'notifications-enable', label: 'Enable notifications', description: 'Turn notifications on or off', keywords: 'notifications enable disable', tab: 'notifications', adminOnly: false },
    { id: 'notifications-channels', label: 'Notification channels', description: 'Choose how to receive notifications (email, Discord, Slack, Telegram)', keywords: 'channels email discord slack telegram', tab: 'notifications', adminOnly: false },
    { id: 'notifications-email', label: 'Email notifications', description: 'Configure email settings for notifications', keywords: 'email smtp notifications', tab: 'notifications', adminOnly: false },
    { id: 'notifications-discord-webhook', label: 'Personal Discord webhook', description: 'Set up Discord direct message or channel notifications', keywords: 'discord webhook notifications', tab: 'notifications', adminOnly: false },
    { id: 'notifications-telegram', label: 'Personal Telegram', description: 'Configure Telegram chat for notifications', keywords: 'telegram bot notifications', tab: 'notifications', adminOnly: false },
    { id: 'notifications-severity', label: 'Alert severity levels', description: 'Choose which alert types to receive (critical, warning, info, success)', keywords: 'severity levels alerts critical warning', tab: 'notifications', adminOnly: false },
    { id: 'notifications-categories', label: 'Notification categories', description: 'Select event types that trigger notifications (system, security, backups, apps)', keywords: 'categories events system security backups', tab: 'notifications', adminOnly: false },
    { id: 'notifications-quiet-hours', label: 'Quiet hours', description: 'Pause non-critical notifications during specific hours', keywords: 'quiet hours silent do not disturb', tab: 'notifications', adminOnly: false },
    { id: 'notifications-email-smtp', label: 'Email SMTP configuration', description: 'Set up SMTP server for sending email notifications', keywords: 'smtp email server notifications', tab: 'notifications', adminOnly: true },
    { id: 'notifications-webhook', label: 'Generic notification webhook', description: 'Send notifications to a custom webhook endpoint', keywords: 'webhook generic json payload', tab: 'notifications', adminOnly: true },

    { id: 'appearance-theme', label: 'Theme mode', description: 'Choose between dark, light, or system default theme', keywords: 'theme dark light system mode', tab: 'appearance', adminOnly: false },
    { id: 'appearance-theme-gallery', label: 'Color theme', description: 'Pick a color theme from the gallery (Paper, Nord Deep, Gruvbox, Phosphor, High Contrast)', keywords: 'theme color skin gallery paper nord gruvbox phosphor high contrast palette', tab: 'appearance', adminOnly: false },
    { id: 'appearance-accent-color', label: 'Accent color', description: 'Select the primary accent color for the UI', keywords: 'color accent primary indigo ocean forest sunset rose', tab: 'appearance', adminOnly: false },
    { id: 'appearance-widgets', label: 'Dashboard widgets', description: 'Toggle visibility and reorder widgets on the dashboard', keywords: 'widgets dashboard visibility order', tab: 'appearance', adminOnly: false },

    { id: 'sidebar-view-profiles', label: 'Sidebar view profiles', description: 'Choose a preset layout or customize sidebar items individually', keywords: 'sidebar layout preset recommended custom', tab: 'sidebar', adminOnly: false },
    { id: 'sidebar-items', label: 'Sidebar items', description: 'Toggle individual sidebar items on or off', keywords: 'sidebar items menu visibility', tab: 'sidebar', adminOnly: false },

    { id: 'whitelabel-branding', label: 'Custom branding', description: 'Enable white label mode and replace ServerKit branding', keywords: 'white label branding custom logo', tab: 'whitelabel', adminOnly: false },
    { id: 'whitelabel-mode', label: 'Branding mode', description: 'Choose how to display custom branding (logo + text, full-width, or text only)', keywords: 'branding mode logo text', tab: 'whitelabel', adminOnly: false },
    { id: 'whitelabel-brand-name', label: 'Brand name', description: 'Set your custom brand name to replace ServerKit', keywords: 'brand name company', tab: 'whitelabel', adminOnly: false },
    { id: 'whitelabel-logo', label: 'Logo image', description: 'Upload a custom logo for the sidebar', keywords: 'logo image upload', tab: 'whitelabel', adminOnly: false },

    { id: 'about-version', label: 'Version information', description: 'View ServerKit version and check for updates', keywords: 'version updates check', tab: 'about', adminOnly: false },
    { id: 'about-links', label: 'Links and resources', description: 'Access documentation, GitHub, support, and bug reports', keywords: 'github documentation support issues', tab: 'about', adminOnly: false },

    { id: 'users-management', label: 'User management', description: 'Create, edit, and manage user accounts', keywords: 'users add create edit delete', tab: 'users', adminOnly: true },
    { id: 'users-role-permission', label: 'User roles and permissions', description: 'Assign roles (admin, developer, viewer) to users', keywords: 'role permission admin developer viewer', tab: 'users', adminOnly: true },
    { id: 'users-active-status', label: 'Activate or disable users', description: 'Enable or disable user account access', keywords: 'active disable deactivate status', tab: 'users', adminOnly: true },
    { id: 'users-login-links', label: 'One-time login links', description: 'Generate single-use sign-in URLs for users', keywords: 'login links one-time auth temporary', tab: 'users', adminOnly: true },
    { id: 'users-invitations', label: 'User invitations', description: 'Invite users to join via email', keywords: 'invitations email invite', tab: 'users', adminOnly: true },

    { id: 'activity-dashboard', label: 'Activity dashboard', description: 'Monitor team activity and view statistics', keywords: 'activity dashboard stats graphs', tab: 'activity', adminOnly: true },
    { id: 'activity-audit-log', label: 'Audit log', description: 'View a detailed audit trail of all system actions and user activities', keywords: 'audit log history actions', tab: 'activity', adminOnly: true },

    { id: 'site-registration', label: 'Public user registration', description: 'Allow or disable new user registration on the login page', keywords: 'registration public signup', tab: 'site', adminOnly: true },
    { id: 'site-appearance', label: 'Panel title & login layout', description: 'Set the panel name shown in the browser tab and on the sign-in page, and pick the login page layout', keywords: 'title brand name login layout appearance tab centered split minimal', tab: 'site', adminOnly: true },
    { id: 'site-app-ports', label: 'Managed app ports', description: 'Control the base port assigned to new applications', keywords: 'ports app wordpress container', tab: 'site', adminOnly: true },
    { id: 'site-base-domains', label: 'Base domains', description: 'Register and manage domains for publishing managed sites', keywords: 'base domain sites registry subdomain', tab: 'site', adminOnly: true },
    { id: 'site-server-ip', label: 'Server public IP', description: 'Configure the public IP address for DNS A records', keywords: 'server public ip dns', tab: 'site', adminOnly: true },
    { id: 'site-dns-mode', label: 'DNS mode', description: 'Choose between wildcard or per-site DNS records', keywords: 'dns mode wildcard per-site', tab: 'site', adminOnly: true },
    { id: 'site-https-setup', label: 'HTTPS certificate setup', description: 'Set up wildcard SSL certificates for base domains', keywords: 'https ssl certificate letsencrypt', tab: 'site', adminOnly: true },
    { id: 'site-dev-mode', label: 'Developer mode', description: 'Enable developer tools and diagnostics', keywords: 'dev mode developer tools debug', tab: 'site', adminOnly: true },
    { id: 'site-registry-url', label: 'Extension registry URL', description: 'Set the source URL for the Extensions registry index', keywords: 'registry url marketplace extensions index', tab: 'site', adminOnly: true },

    { id: 'connections-github', label: 'GitHub connection', description: 'Connect GitHub for source code repositories and deployments', keywords: 'github source control oauth', tab: 'connections', adminOnly: true },
    { id: 'connections-gitlab', label: 'GitLab connection', description: 'Connect GitLab for source code repositories', keywords: 'gitlab source control oauth', tab: 'connections', adminOnly: true },
    { id: 'connections-cloud-provider', label: 'Cloud providers', description: 'Connect cloud accounts for server provisioning', keywords: 'cloud provider digitalocean hetzner vultr linode', tab: 'connections', adminOnly: true },
    { id: 'connections-dns-provider', label: 'DNS providers', description: 'Connect DNS providers for domain and HTTPS management', keywords: 'dns provider cloudflare route53 godaddy', tab: 'connections', adminOnly: true },
    { id: 'connections-registrar', label: 'Domain registrar', description: 'Connect domain registrars to manage domain portfolio and expiry', keywords: 'registrar domains portfolio expiry', tab: 'connections', adminOnly: true },
    { id: 'connections-storage', label: 'Backup storage', description: 'Configure S3-compatible or B2 storage for offsite backups', keywords: 'storage backup s3 backblaze b2', tab: 'connections', adminOnly: true },
    { id: 'connections-email-relay', label: 'Email relay', description: 'Set up an email relay service for outgoing mail', keywords: 'email relay smtp outgoing', tab: 'connections', adminOnly: true },
    { id: 'connections-container-registry', label: 'Container registry', description: 'Connect container registries for Docker image pulls', keywords: 'container registry docker docker hub', tab: 'connections', adminOnly: true },

    { id: 'sso-general-settings', label: 'SSO general settings', description: 'Configure auto-provisioning, default roles, and allowed domains', keywords: 'sso auto provision default role', tab: 'sso', adminOnly: true },
    { id: 'sso-force-mode', label: 'SSO-only mode', description: 'Require all users to authenticate via SSO', keywords: 'sso only mode password disabled', tab: 'sso', adminOnly: true },
    { id: 'sso-google', label: 'Google OAuth', description: 'Configure Google as an SSO provider', keywords: 'google sso oauth', tab: 'sso', adminOnly: true },
    { id: 'sso-github', label: 'GitHub OAuth', description: 'Configure GitHub as an SSO provider', keywords: 'github sso oauth', tab: 'sso', adminOnly: true },
    { id: 'sso-oidc', label: 'OIDC provider', description: 'Configure a generic OpenID Connect provider', keywords: 'oidc openid connect', tab: 'sso', adminOnly: true },
    { id: 'sso-saml', label: 'SAML 2.0', description: 'Configure a SAML 2.0 identity provider', keywords: 'saml saml2 enterprise idp', tab: 'sso', adminOnly: true },

    { id: 'api-keys', label: 'API keys', description: 'Create, rotate, and revoke API keys for programmatic access', keywords: 'api key token authentication', tab: 'api', adminOnly: false },
    { id: 'api-key-scopes', label: 'API key scopes', description: 'Set permissions (scopes) for API keys', keywords: 'api scope permission', tab: 'api', adminOnly: false },
    { id: 'api-rate-limits', label: 'API rate limits', description: 'Configure API rate limits by tier', keywords: 'rate limit requests per minute', tab: 'api', adminOnly: true },
    { id: 'api-webhooks', label: 'Webhook subscriptions', description: 'Create and manage webhooks for event notifications', keywords: 'webhook events notifications', tab: 'api', adminOnly: false },
    { id: 'api-analytics', label: 'API usage analytics', description: 'Monitor API traffic, response times, and errors', keywords: 'api analytics traffic usage endpoints', tab: 'api', adminOnly: true },

    // Inbound webhooks (the receive/verify/forward console, moved here from the
    // retired top-level /webhooks page). Distinct from `api-webhooks` above,
    // which is the OUTBOUND event-subscription surface.
    { id: 'webhooks-endpoints', label: 'Webhook endpoints', description: 'Create inbound webhook endpoints with a slug, signing secret, and optional forward URL', keywords: 'webhook inbound endpoint receive slug secret forward', tab: 'webhooks', adminOnly: true },
    { id: 'webhooks-deliveries', label: 'Webhook deliveries', description: 'Inspect received webhook deliveries, signature validity, and replay them', keywords: 'webhook delivery replay signature payload history', tab: 'webhooks', adminOnly: true },
    { id: 'webhooks-secret', label: 'Regenerate webhook secret', description: 'Rotate the signing secret used to verify an inbound webhook endpoint', keywords: 'webhook secret rotate regenerate signature hmac', tab: 'webhooks', adminOnly: true },

    { id: 'ai-enable', label: 'Enable AI assistant', description: 'Toggle the in-panel AI assistant on or off', keywords: 'ai assistant enable disable', tab: 'ai', adminOnly: true },
    { id: 'ai-provider', label: 'AI provider', description: 'Select the AI service provider (OpenAI, Anthropic, Ollama, etc.)', keywords: 'ai provider openai anthropic ollama', tab: 'ai', adminOnly: true },
    { id: 'ai-model', label: 'AI model', description: 'Choose the language model to use', keywords: 'model gpt claude ollama', tab: 'ai', adminOnly: true },
    { id: 'ai-api-key', label: 'AI API key', description: 'Configure the API key for the selected AI provider', keywords: 'api key authentication', tab: 'ai', adminOnly: true },
    { id: 'ai-endpoint', label: 'AI endpoint', description: 'Set a custom endpoint for self-hosted AI models', keywords: 'endpoint url self-hosted ollama', tab: 'ai', adminOnly: true },
    { id: 'ai-cost-limit', label: 'AI cost ceiling', description: 'Set the maximum spending per conversation', keywords: 'cost limit spending budget', tab: 'ai', adminOnly: true },
    { id: 'ai-pii-redaction', label: 'PII redaction', description: 'Automatically redact personally identifiable information', keywords: 'pii redaction privacy sensitive', tab: 'ai', adminOnly: true },
    { id: 'ai-injection-detection', label: 'Prompt injection detection', description: 'Block prompt injection attack attempts', keywords: 'injection prompt attack security', tab: 'ai', adminOnly: true },

    { id: 'modules-toggle', label: 'Feature modules', description: 'Enable or disable optional feature areas (Email, WordPress, etc.)', keywords: 'modules features email wordpress toggle', tab: 'modules', adminOnly: true },

    { id: 'migrations-apply', label: 'Apply database migrations', description: 'Apply pending schema updates to the database', keywords: 'migration database schema update', tab: 'migrations', adminOnly: true },
    { id: 'migrations-history', label: 'Migration history', description: 'Review previously applied database migrations', keywords: 'migration history database schema', tab: 'migrations', adminOnly: true },

    { id: 'system-cpu', label: 'CPU metrics', description: 'View CPU usage, cores, and load average', keywords: 'cpu usage cores load', tab: 'system', adminOnly: true },
    { id: 'system-memory', label: 'Memory metrics', description: 'View memory usage and available RAM', keywords: 'memory ram usage', tab: 'system', adminOnly: true },
    { id: 'system-disk', label: 'Disk metrics', description: 'View disk usage and storage capacity', keywords: 'disk storage usage', tab: 'system', adminOnly: true },
    { id: 'system-network', label: 'Network metrics', description: 'View network traffic (bytes sent and received)', keywords: 'network bandwidth traffic', tab: 'system', adminOnly: true },
    { id: 'system-timezone', label: 'Server timezone', description: 'Change the server timezone', keywords: 'timezone time region', tab: 'system', adminOnly: true },
    { id: 'system-canonical-domain', label: 'Panel domain', description: 'Set the canonical domain for the ServerKit panel', keywords: 'canonical domain cors agents', tab: 'system', adminOnly: true },
    { id: 'system-encryption-key', label: 'Encryption key', description: 'Verify the encryption key is configured for credential security', keywords: 'encryption key credentials secret', tab: 'system', adminOnly: true },
];

export default SETTINGS_INDEX;
