// Brand-authentic Git provider identities — the single source of truth for how a
// repository host is recognized and presented across ServerKit's "connect a
// repository" surfaces (New Service page, the service connect modal, and the
// WordPress Git tab). Mirrors components/icons/DatabaseBrands.jsx: we wrap Simple
// Icons (via react-icons) so GitHub / GitLab / Bitbucket / Gitea are instantly
// recognizable instead of sharing one generic git glyph.
//
// Simple Icons render with `fill="currentColor"`, so the surrounding SCSS controls
// the color with no inline styles.
import { SiGithub, SiGitlab, SiBitbucket, SiGitea } from 'react-icons/si';
import { GitBranch } from 'lucide-react';
import { useTranslation } from 'react-i18next';

// Ordered list rendered in the provider strip. `match` recognizes a clone URL's
// host; the trailing "other" entry is the catch-all (self-hosted, SSH, anything
// unrecognized).
// `oauth` marks hosts that support a one-click connection (a backend OAuth app);
// `placeholder` is the URL hint shown when that provider is chosen.
export const GIT_PROVIDERS = [
    { key: 'github', labelKey: 'app.gitProviders.github', label: 'GitHub', Icon: SiGithub, hintKey: 'app.gitProviders.oneClickOrUrl', hint: 'One-click or URL', match: /github\.com/i, oauth: true, placeholder: 'https://github.com/user/repo.git' },
    { key: 'gitlab', labelKey: 'app.gitProviders.gitlab', label: 'GitLab', Icon: SiGitlab, hintKey: 'app.gitProviders.cloudOrSelfManaged', hint: 'Cloud or self-managed', match: /gitlab\./i, oauth: true, placeholder: 'https://gitlab.com/group/project.git' },
    { key: 'bitbucket', labelKey: 'app.gitProviders.bitbucket', label: 'Bitbucket', Icon: SiBitbucket, hintKey: 'app.gitProviders.oneClickOrUrl', hint: 'One-click or URL', match: /bitbucket\.org/i, oauth: true, placeholder: 'https://bitbucket.org/user/repo.git' },
    { key: 'gitea', labelKey: 'app.gitProviders.gitea', label: 'Gitea', Icon: SiGitea, hintKey: 'app.gitProviders.selfHosted', hint: 'Self-hosted', match: /gitea/i, local: true, placeholder: 'https://gitea.example.com/user/repo.git' },
    { key: 'other', labelKey: 'app.gitProviders.sshOther', label: 'SSH / Other', Icon: GitBranch, hintKey: 'app.gitProviders.anyGitRemote', hint: 'Any Git remote', match: null, placeholder: 'git@host:user/repo.git' },
];

const OTHER_PROVIDER = GIT_PROVIDERS[GIT_PROVIDERS.length - 1];

// Resolve a clone URL to a provider. Returns null for an empty field (so callers
// can render a neutral, nothing-detected state) and the "other" catch-all when a
// non-empty URL matches no known host.
export function detectProvider(url) {
    const trimmed = (url || '').trim();
    if (!trimmed) return null;
    return GIT_PROVIDERS.find((p) => p.match && p.match.test(trimmed)) || OTHER_PROVIDER;
}

// The provider strip: every supported host as a chip with its brand mark, label,
// and one-liner. Static by default (just "explains the others"); pass `onSelect`
// to make the chips REAL radio buttons that pick the connection method.
export function RepoProviderStrip({ detected, selected, onSelect, giteaStatus }) {
    const { t } = useTranslation();
    const interactive = typeof onSelect === 'function';
    const activeKey = selected ?? detected;
    const giteaRunning = giteaStatus?.installed && giteaStatus?.running;
    return (
        <div
            className="git-connect__providers"
            role={interactive ? 'radiogroup' : 'list'}
            aria-label={t('app.gitProviders.gitProviders', 'Git providers')}
        >
            {GIT_PROVIDERS.map(({ key, label, Icon, hint, local }) => {
                const active = activeKey === key;
                const className = `git-connect__provider${active ? ' git-connect__provider--active' : ''}${interactive ? ' git-connect__provider--btn' : ''}${local && giteaRunning ? ' git-connect__provider--live' : ''}`;
                const displayHint = key === 'gitea' && giteaRunning
                    ? 'Local server running'
                    : hint;
                const inner = (
                    <>
                        <span className="git-connect__provider-icon">
                            <Icon size={18} aria-hidden="true" />
                        </span>
                        <span className="git-connect__provider-label">{label}</span>
                        <span className="git-connect__provider-hint">{displayHint}</span>
                    </>
                );
                return interactive ? (
                    <button
                        type="button"
                        key={key}
                        className={className}
                        role="radio"
                        aria-checked={active}
                        onClick={() => onSelect(key)}
                    >
                        {inner}
                    </button>
                ) : (
                    <div key={key} role="listitem" className={className}>
                        {inner}
                    </div>
                );
            })}
        </div>
    );
}

// Inline brand mark + name — the live "detected provider" indicator beside a URL
// field. Renders nothing until a provider is resolved.
export function ProviderBadge({ provider }) {
    const { t } = useTranslation();
    if (!provider) return null;
    const { Icon, label } = provider;
    return (
        <span className="git-connect__detected">
            <Icon size={13} aria-hidden="true" />
            {t('app.gitProviders.detected', 'Detected:')} {label}
        </span>
    );
}
