"""Architecture ratchet for thin Flask API controllers."""

import json
from collections import Counter

from api_controller_boundary_scan import (
    BASELINE_PATH,
    scan_api_controllers,
    scan_source,
)


def test_controller_boundary_inventory_is_exact_and_owned():
    baseline = json.loads(BASELINE_PATH.read_text(encoding='utf-8'))
    discovered = scan_api_controllers()
    actual = {call.fingerprint for call in discovered}
    expected = set(baseline['violations'])

    added = sorted(actual - expected)
    stale = sorted(expected - actual)
    assert not added and not stale, (
        'API controller boundary inventory changed. Move new crossings behind '
        'a service. After an intentional debt reduction, run '
        '`python backend/tests/api_controller_boundary_scan.py '
        '--write-baseline` and review the baseline diff.\n'
        f'new={added[:20]}\nstale={stale[:20]}'
    )

    counts = dict(sorted(Counter(call.category for call in discovered).items()))
    assert counts == baseline['counts']
    assert baseline['schema_version'] == 1
    assert baseline['policy'].strip()

    files = {call.file for call in discovered}
    assert set(baseline['owners']) == files
    for file, decision in baseline['owners'].items():
        assert decision['owner'].strip(), file
        assert decision['rationale'].strip(), file


def test_boundary_detector_covers_supported_crossings():
    source = '''
import os
import shutil
import subprocess
from app import db as database
from flask import Blueprint
from os import unlink as remove_alias
from pathlib import Path
from subprocess import run as run_alias

bp = Blueprint("sample", __name__)

@bp.route("/sample")
def sample():
    User.query.filter_by(active=True).first()
    Application.query_active().first()
    database.session.commit()
    subprocess.run(["true"])
    run_alias(["true"])
    os.remove("one")
    remove_alias("alias")
    shutil.rmtree("two")
    Path("three").write_text("value")
    open("four", "wb")
    open("read-only", "rb")
'''
    calls = scan_source(source)
    categories = Counter(call.category for call in calls)

    assert categories == {
        'persistence': 3,
        'subprocess': 2,
        'filesystem': 5,
    }
    assert not any('read-only' in call.expression for call in calls)


def test_non_controller_modules_are_outside_the_controller_ratchet():
    assert scan_source('db.session.commit()') == []


def test_invitations_controller_has_converged_on_its_service_boundary():
    calls = [
        call for call in scan_api_controllers()
        if call.file == 'api/invitations.py'
    ]
    assert calls == []
