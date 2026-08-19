"""The ONE status vocabulary for run-shaped models (plan 77 D1).

The same terminal state has historically been spelled four ways across run
models (``success`` in cron_run/backup_run, ``completed`` in db_snapshot and
environment_activity, ``done`` in sandbox runs, ``succeeded`` in deployment
jobs). New columns and API filters import these constants; existing domains
keep their stored spelling until their own per-domain data migration lands
(changing stored strings wholesale is explicitly out of scope — each domain
migrates deliberately, smallest tables first) and normalize at the read edge
via :func:`normalize`.

RunLifecycleMixin (models/mixins.py) writes these constants for adopters,
with per-model overrides for domains still on a legacy spelling.
"""

PENDING = 'pending'
QUEUED = 'queued'
RUNNING = 'running'
SUCCESS = 'success'
FAILED = 'failed'
CANCELLED = 'cancelled'

#: States a run can never leave.
TERMINAL = frozenset({SUCCESS, FAILED, CANCELLED})

#: States describing a run that has not finished.
ACTIVE = frozenset({PENDING, QUEUED, RUNNING})

ALL = frozenset({PENDING, QUEUED, RUNNING, SUCCESS, FAILED, CANCELLED})

#: Every legacy spelling measured in the 2026-08-18 audit, mapped to its
#: canonical constant. Domain-specific *phase* states (``analyzing``,
#: ``verifying``, ``rolled_back``, …) are not lifecycle spellings and pass
#: through :func:`normalize` unchanged.
LEGACY_ALIASES = {
    'succeeded': SUCCESS,
    'completed': SUCCESS,
    'done': SUCCESS,
    'failure': FAILED,
    'error': FAILED,
    'canceled': CANCELLED,
    'scheduled': QUEUED,
}


def normalize(value):
    """Map a stored status string to its canonical spelling.

    Canonical values and unknown domain-specific states return unchanged;
    only known legacy aliases are rewritten. ``None`` stays ``None``.
    """
    if not value:
        return value
    return LEGACY_ALIASES.get(value, value)


def is_terminal(value) -> bool:
    """True when the (possibly legacy-spelled) status is a terminal state."""
    return normalize(value) in TERMINAL
