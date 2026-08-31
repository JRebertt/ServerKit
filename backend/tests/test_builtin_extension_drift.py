"""Bundled extensions exist twice on disk. The copies must not diverge.

``builtin-extensions/<ext>/backend/`` is the source of truth;
``backend/app/plugins/<ext>/`` is the live copy the loader imports. A fix
applied to one and not the other ships a repo that looks correct and a panel
that behaves like the old code.

This is not hypothetical: the plan-74 round fixed `dovecot_service.get_status()`
and the identical edit had to be made twice. Nothing but discipline caught it,
which is exactly the kind of guarantee that fails on a busy day.

Written while drift is **zero** (21 file pairs). That is the point — this locks
in a clean invariant rather than repairing a dirty one, and it only stays cheap
while that is true.

Scope note: only pairs present on BOTH sides are compared. Some extensions
legitimately have one side only, and most live copies are gitignored, so a
fresh clone sees fewer pairs than a dev machine. serverkit-status is the one
live copy git tracks, so a fresh clone always has at least one comparable
pair; `test_drift_check_is_not_vacuous` stops that reducing to nothing.

That machine-dependence is also why the test-count ratchet runs collection with
`SERVERKIT_CLEAN_COLLECT=1` — see `CLEAN_COLLECT` below.
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
SOURCE_ROOT = REPO / 'builtin-extensions'
LIVE_ROOT = REPO / 'backend' / 'app' / 'plugins'

# Set by tests/check_test_count.py. This module is the one place where the
# collected-test COUNT depends on what a machine happens to have on disk: most
# live copies under app/plugins/ are gitignored, so a dev box parametrises over
# pairs no fresh clone can see. --update'ing the floor from such a box wrote a
# number CI could never reach -- twice (4431 -> 4417, then 4530 -> 4516). When
# this is set, only git-TRACKED live copies are paired, so the ratchet counts
# the same tests everywhere. Normal runs are unaffected and still check the
# gitignored copies on the machine that has them.
CLEAN_COLLECT = os.environ.get('SERVERKIT_CLEAN_COLLECT') == '1'


def _tracked_live_copies():
    """Directory names under app/plugins/ that git tracks at least one file in."""
    try:
        proc = subprocess.run(
            ['git', 'ls-files', '--', 'backend/app/plugins'],
            cwd=str(REPO), capture_output=True, text=True,
        )
    except OSError:  # no git on PATH
        return None
    if proc.returncode != 0:  # not a git checkout (release tarball, Docker build)
        return None
    names = set()
    for entry in proc.stdout.splitlines():
        parts = Path(entry).parts if entry else ()
        if len(parts) > 3:
            names.add(parts[3])
    return names


def _normalised_hash(path):
    """Content hash ignoring line endings — the repo has mixed CRLF/LF."""
    data = path.read_bytes().replace(b'\r\n', b'\n')
    return hashlib.sha256(data).hexdigest()


def _python_files(root):
    """{relative path: absolute path} for every .py under *root*."""
    if not root.is_dir():
        return {}
    return {
        p.relative_to(root).as_posix(): p
        for p in root.rglob('*.py')
        if '__pycache__' not in p.parts
    }


def _paired_extensions():
    """Extensions whose source and live copies BOTH exist on this machine."""
    if not SOURCE_ROOT.is_dir():
        return []
    tracked = _tracked_live_copies() if CLEAN_COLLECT else None
    paired = []
    for ext_dir in sorted(p for p in SOURCE_ROOT.iterdir() if p.is_dir()):
        source = ext_dir / 'backend'
        live = LIVE_ROOT / ext_dir.name
        if tracked is not None and ext_dir.name not in tracked:
            continue
        if source.is_dir() and live.is_dir():
            paired.append((ext_dir.name, source, live))
    return paired


def _pairs():
    """[(ext, relpath, source_file, live_file)] for every comparable file."""
    out = []
    for ext, source, live in _paired_extensions():
        source_files = _python_files(source)
        live_files = _python_files(live)
        for rel in sorted(set(source_files) & set(live_files)):
            out.append((ext, rel, source_files[rel], live_files[rel]))
    return out


PAIRS = _pairs()


@pytest.mark.skipif(not PAIRS, reason='no extension has both copies on disk')
@pytest.mark.parametrize(
    'ext,rel,source_file,live_file', PAIRS,
    ids=[f'{ext}/{rel}' for ext, rel, _, _ in PAIRS],
)
def test_live_copy_matches_source(ext, rel, source_file, live_file):
    """A file present in both trees must be byte-identical (modulo CRLF)."""
    assert _normalised_hash(source_file) == _normalised_hash(live_file), (
        f'{ext}/{rel} differs between the source and the live copy.\n'
        f'  source: {source_file.relative_to(REPO)}\n'
        f'  live:   {live_file.relative_to(REPO)}\n'
        'Edit BOTH — the loader imports the live copy, so a fix applied only to '
        'builtin-extensions/ ships a repo that reads correct and a panel that '
        'runs the old code.'
    )


def test_no_file_is_missing_from_one_side():
    """A file added to one tree and not the other is drift before it is edited."""
    missing = []
    for ext, source, live in _paired_extensions():
        source_files = set(_python_files(source))
        live_files = set(_python_files(live))
        for rel in sorted(source_files - live_files):
            missing.append(f'{ext}/{rel}: in builtin-extensions, not in app/plugins')
        for rel in sorted(live_files - source_files):
            missing.append(f'{ext}/{rel}: in app/plugins, not in builtin-extensions')

    assert not missing, (
        'Extension files exist on only one side:\n  ' + '\n  '.join(missing)
    )


def test_drift_check_is_not_vacuous():
    """Guard the guard.

    Most live copies are gitignored, so a fresh clone sees far fewer pairs than
    a dev machine. serverkit-status's live copy is deliberately tracked (see the
    note in .gitignore), so at least one extension must always be comparable.
    Without this, a reorganisation could silently reduce the parametrised test
    above to zero cases and it would still report green -- which is exactly what
    happened when serverkit-email, the previous anchor, left the tree in plan 52.
    """
    assert PAIRS, (
        'No extension had both a builtin-extensions/<ext>/backend and an '
        'app/plugins/<ext> copy, so the drift check compared nothing. Either '
        'the layout moved or the tracked serverkit-status copy is gone.'
    )


def test_clean_collect_drops_untracked_live_copies(monkeypatch):
    """The floor-inflation guard, proved.

    Under ``SERVERKIT_CLEAN_COLLECT=1`` a live copy git does not track must not
    produce a parametrised case, or ``check_test_count.py --update`` bakes a
    dev-only number into BASELINE_COUNT and the ratchet goes red on CI for a
    suite that lost nothing (it did, twice: 4431 -> 4417 and 4530 -> 4516).
    """
    module = sys.modules[__name__]
    # Force the unfiltered view first, so the test means the same thing whether
    # or not the suite itself was started with SERVERKIT_CLEAN_COLLECT set.
    monkeypatch.setattr(module, 'CLEAN_COLLECT', False)
    baseline = {ext for ext, _, _ in _paired_extensions()}
    assert baseline, 'nothing paired — see test_drift_check_is_not_vacuous'

    monkeypatch.setattr(module, 'CLEAN_COLLECT', True)
    monkeypatch.setattr(module, '_tracked_live_copies', lambda: set())
    assert _paired_extensions() == []

    monkeypatch.setattr(module, '_tracked_live_copies', lambda: baseline)
    assert {ext for ext, _, _ in _paired_extensions()} == baseline

    # A non-git checkout must not silently drop every pair.
    monkeypatch.setattr(module, '_tracked_live_copies', lambda: None)
    assert {ext for ext, _, _ in _paired_extensions()} == baseline


def test_ratchet_still_asks_for_a_clean_collect():
    """Deleting the env var in check_test_count.py re-opens the same hole."""
    ratchet = (Path(__file__).parent / 'check_test_count.py').read_text(encoding='utf-8')
    assert "SERVERKIT_CLEAN_COLLECT='1'" in ratchet, (
        'check_test_count.py no longer sets SERVERKIT_CLEAN_COLLECT, so its '
        'count is machine-dependent again.'
    )
