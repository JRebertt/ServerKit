"""The committed migration inventory must match the measured state (plan 76, H).

``docs/MIGRATION_INVENTORY.md`` is generated from the same censuses and checks
that enforce each ratchet, so the plan cannot claim a migration is further
along (or a door more adopted) than the code measures. This test is the
freshness half of that closure: whenever a migration commit moves a number,
regenerating the document is part of the commit::

    python scripts/generate-migration-inventory.py

Skipped when node is unavailable — the generator shells out to the frontend
boundary checker for its half of the rows.
"""

import importlib.util
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
GENERATOR = os.path.join(REPO, 'scripts', 'generate-migration-inventory.py')
DOC = os.path.join(REPO, 'docs', 'MIGRATION_INVENTORY.md')


def test_the_committed_inventory_matches_the_measured_state():
    if shutil.which('node') is None:
        pytest.skip('node is not available to run the frontend half')
    assert os.path.exists(DOC), (
        'docs/MIGRATION_INVENTORY.md is missing; run '
        'python scripts/generate-migration-inventory.py')

    spec = importlib.util.spec_from_file_location('_mig_inventory', GENERATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    expected = mod.render()
    with open(DOC, encoding='utf-8') as f:
        committed = f.read()
    assert committed == expected, (
        'docs/MIGRATION_INVENTORY.md is stale — a ratchet number moved without '
        'regenerating it. Run: python scripts/generate-migration-inventory.py'
    )
