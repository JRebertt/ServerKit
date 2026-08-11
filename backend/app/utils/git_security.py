"""Shared validation and hardening helpers for git subprocess invocations.

All git calls that interpolate user-influenced values (repository URLs, branch
names, destination paths) must go through these helpers. They defend against
argument/option injection (CWE-88), which list-form ``subprocess.run`` does
NOT prevent: git interprets its own arguments, so an attacker-controlled value
such as ``ext::sh -c <cmd>``, ``file:///etc/repo`` or ``--upload-pack=<cmd>``
is otherwise executed by git itself.

Defences applied here (GHSA-8vx6-432p-h62q):

1. Scheme allowlist for repository URLs (https/http/git/ssh + scp-like SSH).
   Rejects the ``ext::`` transport, ``file://`` and bare local paths.
2. Rejection of values beginning with ``-`` (option injection).
3. ``-c protocol.ext.allow=never -c protocol.file.allow=never`` pinned on
   every network-touching git invocation, plus a restrictive
   ``GIT_ALLOW_PROTOCOL`` in the subprocess environment. This closes the
   transport-selection tiers regardless of the host's git version (the
   ``protocol.ext.allow=user`` default only changed in git 2.52).
4. ``--`` positional terminator before URL/path/refspec arguments. This is
   co-load-bearing with protocol pinning: pinning restricts transports only
   and does NOT stop option injection such as ``--upload-pack=<cmd>``; only
   the terminator does.
5. Branch/ref name validation (leading ``-``, whitespace, ref-format
   metacharacters) for values used as fetch refspecs or ``--branch``.
"""

import os
import re
from typing import List, Optional

# Schemes allowed for user-supplied repository URLs. Local paths, file:// and
# ext:: are deliberately excluded: the panel has no legitimate need to clone
# from the local filesystem, and ext:: executes arbitrary commands.
ALLOWED_REPO_SCHEMES = ('https', 'http', 'git', 'ssh')

# Config pinned on every git invocation that talks to a remote. Belt-and-
# braces alongside URL validation; also protects repositories whose stored
# origin URL was configured before validation existed.
GIT_PROTOCOL_PIN = [
    '-c', 'protocol.ext.allow=never',
    '-c', 'protocol.file.allow=never',
]

# scp-like SSH syntax: [user@]host:path (single colon, no "://" prefix).
_SCP_LIKE_RE = re.compile(r'^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:[^-\s].*$')

# Characters never legal in a git ref/branch component (see git-check-ref-format).
_REF_ILLEGAL_CHARS = (' ', '\t', '\n', '\r', '~', '^', ':', '?', '*', '[', '\\', '..', '@{')

_SCHEME_RE = re.compile(r'^([A-Za-z][A-Za-z0-9+.-]*)://')


def validate_repo_url(repo_url: str) -> Optional[str]:
    """Validate a user-supplied git repository URL.

    Returns None when valid, otherwise a human-readable error string.
    Accepts only http(s)://, git://, ssh:// URLs and scp-like SSH syntax
    (user@host:path). Rejects local paths, file://, ext:: and anything that
    could be parsed as a git option or transport specifier.
    """
    if not repo_url or not isinstance(repo_url, str):
        return 'Repository URL is required'

    url = repo_url.strip()
    if not url or len(url) > 2048:
        return 'Invalid repository URL'

    # Option injection guard: a leading '-' makes git parse the value as a flag.
    if url.startswith('-'):
        return 'Invalid repository URL'

    # Transport injection guard: 'ext::cmd' / '<proto>::<cmd>' syntax.
    if '::' in url:
        return 'Invalid repository URL'

    # No whitespace or control characters in any accepted form.
    if any(c.isspace() or ord(c) < 0x20 for c in url):
        return 'Invalid repository URL'

    scheme_match = _SCHEME_RE.match(url)
    if scheme_match:
        if scheme_match.group(1).lower() not in ALLOWED_REPO_SCHEMES:
            return (f'Repository URL scheme "{scheme_match.group(1)}" is not allowed '
                    f'(allowed: {", ".join(ALLOWED_REPO_SCHEMES)})')
        return None

    # No scheme: only scp-like SSH syntax (user@host:path) is acceptable.
    if _SCP_LIKE_RE.match(url):
        return None

    return ('Invalid repository URL: use an http(s)://, git:// or ssh:// URL, '
            'or SSH syntax (user@host:path)')


def validate_ref_name(ref: str, what: str = 'branch') -> Optional[str]:
    """Validate a branch/tag/ref name used in a git invocation.

    Returns None when valid, otherwise an error string. Guards both option
    injection (leading '-') and ref-format metacharacters.
    """
    if not ref or not isinstance(ref, str):
        return None  # Absent ref is fine; callers default it.

    name = ref.strip()
    if not name or len(name) > 255:
        return f'Invalid {what} name'

    if name.startswith('-'):
        return f'Invalid {what} name'

    if any(c in name for c in _REF_ILLEGAL_CHARS):
        return f'Invalid {what} name'

    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in name):
        return f'Invalid {what} name'

    if name.startswith('/') or name.endswith('/') or '//' in name:
        return f'Invalid {what} name'

    if name.endswith('.') or name.endswith('.lock') or '.lock/' in name:
        return f'Invalid {what} name'

    return None


def validate_clone_path(path: str) -> Optional[str]:
    """Validate a clone destination path used as a git positional argument.

    Returns None when valid, otherwise an error string. The path must be
    absolute, must not begin with '-', and must not be a URL/transport
    specifier. Callers that manage a dedicated apps root should additionally
    confine the path to that root (see the /deploy/clone route).
    """
    if not path or not isinstance(path, str):
        return 'Destination path is required'

    candidate = path.strip()
    if not candidate or candidate.startswith('-'):
        return 'Invalid destination path'

    if not os.path.isabs(candidate):
        return 'Destination path must be absolute'

    if '::' in candidate or any(ord(c) < 0x20 for c in candidate):
        return 'Invalid destination path'

    return None


def git_argv(*args: str) -> List[str]:
    """Build a git argv with protocol pinning pre-applied.

    Example: ``git_argv('ls-remote', '--heads', '--', url)`` ->
    ``['git', '-c', 'protocol.ext.allow=never', '-c',
    'protocol.file.allow=never', 'ls-remote', '--heads', '--', url]``
    """
    return ['git', *GIT_PROTOCOL_PIN, *args]


def git_env() -> dict:
    """Subprocess environment with a restrictive GIT_ALLOW_PROTOCOL.

    Complements the per-invocation config pinning: any transport helper git
    might spawn is additionally limited to the allowlisted protocols.
    """
    env = dict(os.environ)
    env['GIT_ALLOW_PROTOCOL'] = ':'.join(ALLOWED_REPO_SCHEMES)
    return env
