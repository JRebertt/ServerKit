"""Plan 77 F4 — utils/env.py is the one env parser.

The bug class: truthiness parsed in incompatible variants —
SERVERKIT_ALLOW_PRIVATE_DOWNLOADS=on silently read false in plugin_service
because its private tuple lacked 'on'. env_bool is the single parser
(config.py imports it back); the ratchet stops new hand-rolled env
truthiness tuples.
"""
import re
from pathlib import Path

import pytest

from app.utils.env import env_bool, env_int, env_str

APP = Path(__file__).resolve().parents[1] / 'app'


@pytest.mark.parametrize('raw,expected', [
    ('1', True), ('true', True), ('YES', True), ('on', True), (' On ', True),
    ('0', False), ('false', False), ('off', False), ('garbage', False), ('', False),
])
def test_env_bool_spellings(monkeypatch, raw, expected):
    monkeypatch.setenv('X_FLAG', raw)
    assert env_bool('X_FLAG') is expected


def test_env_bool_default(monkeypatch):
    monkeypatch.delenv('X_FLAG', raising=False)
    assert env_bool('X_FLAG') is False
    assert env_bool('X_FLAG', True) is True


def test_env_int_garbage_falls_back(monkeypatch):
    monkeypatch.setenv('X_NUM', 'not-a-number')
    assert env_int('X_NUM', 7) == 7
    monkeypatch.setenv('X_NUM', '42')
    assert env_int('X_NUM', 7) == 42


def test_env_str(monkeypatch):
    monkeypatch.delenv('X_S', raising=False)
    assert env_str('X_S') is None
    assert env_str('X_S', 'd') == 'd'
    monkeypatch.setenv('X_S', 'v')
    assert env_str('X_S', 'd') == 'v'


def test_private_downloads_accepts_on(monkeypatch):
    """The measured bug: '=on' must read true on the plugin download gate."""
    monkeypatch.setenv('SERVERKIT_ALLOW_PRIVATE_DOWNLOADS', 'on')
    assert env_bool('SERVERKIT_ALLOW_PRIVATE_DOWNLOADS') is True


def test_config_imports_the_shared_parser():
    import config as config_mod
    from app.utils import env as env_mod
    assert config_mod._env_bool is env_mod.env_bool
    assert config_mod._env_int is env_mod.env_int


def test_no_new_env_truthiness_tuples():
    """Ratchet: no hand-rolled `os.environ… .lower() in (…)` truthiness
    outside utils/env.py (vendored plugin copies excluded)."""
    offenders = []
    for f in APP.rglob('*.py'):
        rel = f.relative_to(APP).as_posix()
        if rel == 'utils/env.py' or rel.startswith('plugins/') or '__pycache__' in rel:
            continue
        lines = f.read_text(encoding='utf-8', errors='replace').split('\n')
        for i, line in enumerate(lines):
            if 'os.environ' in line:
                window = line + (lines[i + 1] if i + 1 < len(lines) else '')
                if re.search(r"\.lower\(\)\s*in\s*\(", window):
                    offenders.append(f'{rel}:{i + 1}')
    assert not offenders, (
        f"Hand-rolled env truthiness at {offenders} — use "
        "app.utils.env.env_bool instead (plan 77 F4)."
    )
