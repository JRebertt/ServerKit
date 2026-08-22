"""Disk reclamation: the scan must measure honestly and the reclaimers must
only ever touch what they claim to.

The guards that matter here are the ones that were learned the hard way when a
25 GB panel host filled to 100% purely from `serverkit update` runs:

* filesystem reclaimers run BEFORE the database VACUUM (VACUUM needs free space
  equal to the database it rewrites, so it cannot go first on a full disk);
* the newest upgrade snapshot is never deleted;
* /tmp entries that aren't ours are never deleted;
* a queue message still referenced by a surviving job is never deleted.
"""
import os
import time

import pytest

from app.services import disk_reclaim_service as svc


# ── upgrade snapshots ───────────────────────────────────────────────────────

def _make_snapshots(root):
    """Three upgrade snapshot sets, oldest to newest."""
    for stamp in ('20260817-025332', '20260819-212804', '20260821-045737'):
        tree = root / f'serverkit-tree-{stamp}'
        (tree / 'backend').mkdir(parents=True)
        (tree / 'backend' / 'serverkit.db').write_bytes(b'x' * 1000)
        (root / f'serverkit-pre-upgrade-{stamp}.db').write_bytes(b'y' * 1000)
    return root


def test_snapshot_scan_keeps_the_newest_set(tmp_path):
    _make_snapshots(tmp_path)
    paths, size = svc._scan_upgrade_snapshots(str(tmp_path), keep=1)

    names = {os.path.basename(p) for p in paths}
    assert names == {
        'serverkit-tree-20260817-025332', 'serverkit-pre-upgrade-20260817-025332.db',
        'serverkit-tree-20260819-212804', 'serverkit-pre-upgrade-20260819-212804.db',
    }
    # The newest stamp survives in both forms.
    assert not any('20260821-045737' in n for n in names)
    assert size > 0


def test_snapshot_scan_keep_zero_takes_everything(tmp_path):
    _make_snapshots(tmp_path)
    paths, _ = svc._scan_upgrade_snapshots(str(tmp_path), keep=0)
    assert len(paths) == 6


def test_snapshot_scan_ignores_unrelated_files(tmp_path):
    _make_snapshots(tmp_path)
    (tmp_path / 'important-customer-backup.db').write_bytes(b'z' * 100)
    (tmp_path / 'scheduled').mkdir()
    paths, _ = svc._scan_upgrade_snapshots(str(tmp_path), keep=0)
    assert all('serverkit-' in os.path.basename(p) for p in paths)
    assert (tmp_path / 'important-customer-backup.db').exists()


def test_snapshot_reclaim_deletes_only_the_selected(tmp_path):
    _make_snapshots(tmp_path)
    result = svc.reclaim(['upgrade-snapshots'], backup_dir=str(tmp_path), keep=1)

    assert result['freed_bytes'] > 0
    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == [
        'serverkit-pre-upgrade-20260821-045737.db',
        'serverkit-tree-20260821-045737',
    ]


def test_snapshots_are_grouped_by_stamp_with_ages(tmp_path):
    """One update writes several files under one stamp; they are offered as a
    unit, because half a snapshot is not a restore point."""
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    stamps = [(now - timedelta(days=n)).strftime('%Y%m%d-%H%M%S') for n in (10, 3, 0)]
    for stamp in stamps:
        tree = tmp_path / f'serverkit-tree-{stamp}'
        tree.mkdir()
        (tree / 'db').write_bytes(b'x' * 100)
        (tmp_path / f'serverkit-pre-upgrade-{stamp}.db').write_bytes(b'y' * 100)

    snaps = svc.list_snapshots(str(tmp_path))
    assert [s['stamp'] for s in snaps] == list(reversed(stamps)), 'newest first'
    assert [s['age_days'] for s in snaps] == [0, 3, 10]
    assert all(len(s['paths']) == 2 for s in snaps), 'tree + db grouped together'
    assert all(s['bytes'] > 0 for s in snaps)


def test_postgres_dump_snapshots_are_seen(tmp_path):
    """PostgreSQL installs snapshot with pg_dump, not a file copy."""
    (tmp_path / 'serverkit-pre-upgrade-20260101-000000.dump').write_bytes(b'x' * 500)
    (tmp_path / 'serverkit-pre-upgrade-20260102-000000.dump').write_bytes(b'x' * 500)
    snaps = svc.list_snapshots(str(tmp_path))
    assert len(snaps) == 2
    paths, size = svc._scan_upgrade_snapshots(str(tmp_path), keep=1)
    assert [os.path.basename(p) for p in paths] == \
        ['serverkit-pre-upgrade-20260101-000000.dump']
    assert size == 500


def test_select_snapshots_by_age_never_beats_keep(tmp_path):
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    snaps = [{'stamp': f's{n}', 'age_days': n, 'paths': [], 'bytes': 1}
             for n in (0, 5, 20, 40)]

    # Age filter applies only to what `keep` already released.
    assert [s['stamp'] for s in svc.select_snapshots(snaps, keep=1, older_than_days=10)] == \
        ['s20', 's40']
    # Even a 0-day filter cannot take the newest when keep=1.
    assert 's0' not in [s['stamp'] for s in svc.select_snapshots(snaps, keep=1,
                                                                 older_than_days=0)]
    # No age filter: everything past keep.
    assert len(svc.select_snapshots(snaps, keep=2)) == 2


def test_reclaim_honours_hand_picked_snapshot_stamps(tmp_path):
    _make_snapshots(tmp_path)
    # Deliberately pick the OLDEST and NEWEST, skipping the middle one.
    result = svc.reclaim(['upgrade-snapshots'], backup_dir=str(tmp_path),
                         snapshot_stamps=['20260817-025332', '20260821-045737'])
    assert result['freed_bytes'] > 0
    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == [
        'serverkit-pre-upgrade-20260819-212804.db',
        'serverkit-tree-20260819-212804',
    ]


# ── /tmp staging ────────────────────────────────────────────────────────────

def _age(path, hours):
    old = time.time() - hours * 3600
    os.utime(path, (old, old))


@pytest.mark.skipif(os.name == 'nt', reason='uid ownership check is POSIX-only')
def test_tmp_staging_only_matches_serverkit_update_dirs(tmp_path):
    ours = tmp_path / 'tmp.AbCdEf1234'
    (ours / 'opt' / 'serverkit').mkdir(parents=True)
    _age(ours, 48)

    # Right name shape, but nothing of ours inside.
    theirs = tmp_path / 'tmp.ZzZzZz9999'
    (theirs / 'postgres-data').mkdir(parents=True)
    _age(theirs, 48)

    # Our shape and content, but still fresh — an update may be running now.
    fresh = tmp_path / 'tmp.FrEsH12345'
    (fresh / 'opt' / 'serverkit').mkdir(parents=True)

    # Not a mktemp name at all.
    other = tmp_path / 'tmp.short'
    other.mkdir()
    _age(other, 48)

    paths, _ = svc._scan_tmp_staging(str(tmp_path))
    assert [os.path.basename(p) for p in paths] == ['tmp.AbCdEf1234']


def test_tmp_staging_name_pattern_is_exact():
    assert svc._MKTEMP_RE.match('tmp.AbCdEf1234')
    assert not svc._MKTEMP_RE.match('tmp.short')
    assert not svc._MKTEMP_RE.match('tmp.WayTooLongName99')
    assert not svc._MKTEMP_RE.match('systemd-private-abc')


# ── oversized login logs ────────────────────────────────────────────────────

def test_login_logs_are_truncated_not_deleted(tmp_path):
    log = tmp_path / 'btmp'
    log.write_bytes(b'\0' * 2048)
    freed = svc._reclaim_paths([str(log)], truncate=True)
    assert freed == 2048
    assert log.exists(), 'btmp must survive so it keeps its ownership and mode'
    assert log.stat().st_size == 0


# ── ordering: filesystem before VACUUM ──────────────────────────────────────

def test_reclaim_runs_filesystem_before_the_database(tmp_path, monkeypatch):
    """VACUUM needs headroom the filesystem steps free, so it must go last."""
    order = []

    monkeypatch.setattr(svc, '_scan_upgrade_snapshots', lambda *a, **k: ([], 0))
    monkeypatch.setattr(svc, '_scan_tmp_staging', lambda *a, **k: ([], 0))
    monkeypatch.setattr(svc, '_scan_journal', lambda *a, **k: (order.append('journal'), 0)[1])
    monkeypatch.setattr(svc, '_scan_docker', lambda *a, **k: (order.append('docker'), 0)[1])
    monkeypatch.setattr(svc, '_scan_package_caches',
                        lambda *a, **k: (order.append('caches'), ([], 0))[1])
    monkeypatch.setattr(svc, '_scan_oversized_logs',
                        lambda *a, **k: (order.append('logs'), ([], 0))[1])
    monkeypatch.setattr(svc, 'prune_telemetry',
                        lambda **k: (order.append('telemetry'),
                                     {'bytes': 0, 'deletable_rows': 0, 'deleted_rows': 0})[1])
    monkeypatch.setattr(svc, 'disk_usage', lambda *a, **k: None)

    keys = ['telemetry', 'journal', 'docker-build-cache', 'package-caches', 'login-logs']
    svc.reclaim(keys, dry_run=True)

    assert order[-1] == 'telemetry', f'telemetry must run last, got {order}'


def test_reclaim_ignores_keys_that_were_not_selected(tmp_path, monkeypatch):
    called = []

    def fake_list(*args, **kwargs):
        called.append('snap')
        return []

    def fake_prune(**kwargs):
        called.append('telemetry')
        return {'bytes': 0, 'deletable_rows': 0, 'deleted_rows': 0}

    monkeypatch.setattr(svc, 'list_snapshots', fake_list)
    monkeypatch.setattr(svc, 'prune_telemetry', fake_prune)
    monkeypatch.setattr(svc, 'disk_usage', lambda *a, **k: None)

    svc.reclaim(['upgrade-snapshots'], dry_run=True)
    assert called == ['snap'], 'only the selected reclaimer may run'


# ── VACUUM preconditions ────────────────────────────────────────────────────

def test_vacuum_refuses_when_the_disk_cannot_hold_the_rewrite(tmp_path, monkeypatch):
    db_file = tmp_path / 'serverkit.db'
    db_file.write_bytes(b'x' * 4096)
    monkeypatch.setattr(svc, 'disk_usage',
                        lambda *a, **k: {'free': 100, 'total': 1, 'used': 1,
                                         'percent_used': 100.0, 'path': '/'})

    result = svc._vacuum(str(db_file))
    assert result['ok'] is False
    assert 'reclaim filesystem space first' in result['error']


def test_vacuum_skips_cleanly_on_a_non_sqlite_database():
    result = svc._vacuum(None)
    assert result['ok'] is False
    assert 'not a SQLite database' in result['error']


# ── telemetry pruning against a real database ───────────────────────────────

def test_prune_keeps_fresh_rows_running_work_and_referenced_messages(app):
    """The three things the prune must never take."""
    from datetime import datetime, timedelta
    from sqlalchemy import text
    from app import db

    old = datetime.utcnow() - timedelta(days=30)
    fresh = datetime.utcnow()

    def seed_queue(msg_id, status, created):
        db.session.execute(text(
            'INSERT INTO queue_messages (id, queue_id, group_id, status, priority, '
            'payload_json, attempts, max_attempts, visible_after, created_at, updated_at) '
            'VALUES (:id, :q, :g, :s, 0, :p, 0, 3, :c, :c, :c)'),
            {'id': msg_id, 'q': 'q1', 'g': 'g1', 's': status, 'p': '{}', 'c': created})

    def seed_job(job_id, status, created, queue_message_id=None):
        db.session.execute(text(
            'INSERT INTO jobs (id, kind, status, attempts, max_attempts, priority, '
            'created_at, updated_at, queue_message_id) '
            'VALUES (:id, :k, :s, 0, 1, 0, :c, :c, :qm)'),
            {'id': job_id, 'k': 'builtin.test', 's': status, 'c': created,
             'qm': queue_message_id})

    seed_queue('m-old-orphan', 'completed', old)      # goes
    seed_queue('m-old-referenced', 'completed', old)  # stays: a job points at it
    seed_queue('m-old-inflight', 'in_flight', old)    # stays: still running
    seed_queue('m-fresh', 'completed', fresh)         # stays: inside the window

    seed_job('j-old-succeeded', 'succeeded', old)          # goes
    seed_job('j-old-pending', 'pending', old)              # stays: not terminal
    seed_job('j-old-failed', 'failed', old)                # stays: kept for diagnosis
    seed_job('j-fresh', 'succeeded', fresh, 'm-old-referenced')
    db.session.commit()

    svc.prune_telemetry(days=7, vacuum=False)

    surviving_msgs = {
        row[0] for row in db.session.execute(text('SELECT id FROM queue_messages'))}
    surviving_jobs = {
        row[0] for row in db.session.execute(text('SELECT id FROM jobs'))}

    assert 'm-old-orphan' not in surviving_msgs
    assert {'m-old-referenced', 'm-old-inflight', 'm-fresh'} <= surviving_msgs
    assert 'j-old-succeeded' not in surviving_jobs
    assert {'j-old-pending', 'j-old-failed', 'j-fresh'} <= surviving_jobs

    # No job may point at a message that is gone.
    dangling = db.session.execute(text(
        'SELECT COUNT(*) FROM jobs j WHERE j.queue_message_id IS NOT NULL '
        'AND NOT EXISTS (SELECT 1 FROM queue_messages m WHERE m.id = j.queue_message_id)'
    )).scalar()
    assert dangling == 0


def test_scan_telemetry_reports_counts_without_deleting(app):
    from datetime import datetime, timedelta
    from sqlalchemy import text
    from app import db

    old = datetime.utcnow() - timedelta(days=30)
    for i in range(5):
        db.session.execute(text(
            'INSERT INTO api_usage_logs (method, endpoint, status_code, created_at) '
            'VALUES (:m, :e, 200, :c)'),
            {'m': 'GET', 'e': f'/api/v1/thing/{i}', 'c': old})
    db.session.commit()

    report = svc.scan_telemetry(days=7)
    usage = next(t for t in report['tables'] if t['table'] == 'api_usage_logs')
    assert usage['deletable'] == 5

    still_there = db.session.execute(
        text('SELECT COUNT(*) FROM api_usage_logs')).scalar()
    assert still_there == 5, 'scan must not delete anything'


# ── the scheduled handler that keeps this from recurring ────────────────────

def test_telemetry_retention_handler_is_scheduled():
    """Without a registered schedule the tables grow forever — which is the
    whole reason a 25 GB host filled from nothing but updates."""
    from app.jobs.builtin_handlers import _BUILTINS

    entry = next((b for b in _BUILTINS if b[0] == 'builtin.telemetry_retention'), None)
    assert entry is not None, 'telemetry retention must be a registered builtin'
    kind, handler, name, interval, delay = entry
    assert name == 'telemetry-retention'
    assert 0 < interval <= 86400, 'must run at least daily'


def test_telemetry_retention_handler_prunes(app):
    from datetime import datetime, timedelta
    from sqlalchemy import text
    from app import db
    from app.jobs.builtin_handlers import run_telemetry_retention
    from app.services.settings_service import SettingsService

    old = datetime.utcnow() - timedelta(days=90)
    for i in range(3):
        db.session.execute(text(
            'INSERT INTO api_usage_logs (method, endpoint, status_code, created_at) '
            'VALUES (:m, :e, 200, :c)'), {'m': 'GET', 'e': f'/x/{i}', 'c': old})
    db.session.commit()

    result = run_telemetry_retention()
    assert result and result['deleted'] == 3
    assert db.session.execute(text('SELECT COUNT(*) FROM api_usage_logs')).scalar() == 0


def test_telemetry_retention_zero_disables(app):
    from datetime import datetime, timedelta
    from sqlalchemy import text
    from app import db
    from app.jobs.builtin_handlers import run_telemetry_retention
    from app.services.settings_service import SettingsService

    old = datetime.utcnow() - timedelta(days=90)
    db.session.execute(text(
        'INSERT INTO api_usage_logs (method, endpoint, status_code, created_at) '
        'VALUES (:m, :e, 200, :c)'), {'m': 'GET', 'e': '/x', 'c': old})
    db.session.commit()

    SettingsService.set('telemetry.retention_days', 0)
    assert run_telemetry_retention() is None
    assert db.session.execute(text('SELECT COUNT(*) FROM api_usage_logs')).scalar() == 1


def test_telemetry_retention_never_vacuums_inline(app, monkeypatch):
    """VACUUM takes an exclusive lock and needs free space equal to the whole
    database — never acceptable on a background tick."""
    from app.jobs.builtin_handlers import run_telemetry_retention

    monkeypatch.setattr(svc, '_vacuum', lambda *a, **k: pytest.fail(
        'the scheduled handler must not VACUUM'))
    run_telemetry_retention()


# ── formatting ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('value,expected', [
    (0, '0 B'), (512, '512 B'), (1024, '1.0 KB'),
    (1536, '1.5 KB'), (1024 ** 3, '1.0 GB'), (None, '-'),
])
def test_human_bytes(value, expected):
    assert svc.human_bytes(value) == expected


# ── the menu's numbers must mean what they show ─────────────────────────────

def _fake_scan_with_empties():
    """Two candidates that can free nothing, then two that can."""
    return {
        'disk': {'path': '/', 'total': 100, 'used': 90, 'free': 10, 'percent_used': 90.0},
        'total_bytes': 3000,
        'candidates': [
            {'key': 'upgrade-snapshots', 'safety': 'safe', 'title': 'Snapshots',
             'detail': 'none', 'bytes': 0, 'paths': []},
            {'key': 'tmp-staging', 'safety': 'safe', 'title': 'Staging',
             'detail': 'none', 'bytes': 0, 'paths': []},
            {'key': 'journal', 'safety': 'safe', 'title': 'Journal',
             'detail': 'over cap', 'bytes': 1000, 'paths': []},
            {'key': 'telemetry', 'safety': 'review', 'title': 'Telemetry',
             'detail': 'old rows', 'bytes': 2000, 'paths': []},
        ],
    }


def test_menu_number_selects_the_item_it_is_printed_next_to(monkeypatch):
    """Regression: numbering the full list while reading numbers back off the
    non-empty list silently selects a different item than the one shown."""
    from click.testing import CliRunner
    import cli as serverkit_cli

    monkeypatch.setattr(svc, 'scan', lambda **k: _fake_scan_with_empties())
    monkeypatch.setattr(serverkit_cli, 'create_app', lambda: _NullApp())
    captured = {}

    def fake_reclaim(keys, **kwargs):
        captured['keys'] = list(keys)
        return {'dry_run': True, 'results': [], 'freed_bytes': 0,
                'disk_before': None, 'disk_after': None}

    monkeypatch.setattr(svc, 'reclaim', fake_reclaim)

    result = CliRunner().invoke(serverkit_cli.disk, ['--dry-run'], input='2\n')
    assert result.exit_code == 0, result.output

    # 'Telemetry' is printed against a number; typing it must select telemetry.
    line = next(ln for ln in result.output.splitlines() if 'Telemetry' in ln and 'old rows' in ln)
    shown = line.split()[0]
    assert shown == '2', f'expected Telemetry to be listed as #2, got {shown!r}'
    assert captured['keys'] == ['telemetry']


def test_menu_hides_numbers_for_items_that_free_nothing(monkeypatch):
    from click.testing import CliRunner
    import cli as serverkit_cli

    monkeypatch.setattr(svc, 'scan', lambda **k: _fake_scan_with_empties())
    monkeypatch.setattr(serverkit_cli, 'create_app', lambda: _NullApp())
    monkeypatch.setattr(svc, 'reclaim', lambda keys, **k: {
        'dry_run': True, 'results': [], 'freed_bytes': 0,
        'disk_before': None, 'disk_after': None})

    result = CliRunner().invoke(serverkit_cli.disk, ['--dry-run'], input='q\n')
    snapshots = next(ln for ln in result.output.splitlines() if 'Snapshots' in ln)
    assert snapshots.split()[0] == '-'


class _NullApp:
    """Stand-in for create_app() — the disk command only needs a context."""

    def app_context(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_parse_docker_reclaimed():
    assert svc._parse_reclaimed('deleted: sha256:abc\nTotal reclaimed space: 1.234GB\n') == \
        int(1.234 * 1024 ** 3)
    assert svc._parse_reclaimed('Total reclaimed space: 0B') == 0
    assert svc._parse_reclaimed('') == 0
    assert svc._parse_reclaimed('nothing useful here') == 0


def test_journal_scan_subtracts_the_cap(monkeypatch):
    monkeypatch.setattr(svc, '_run',
                        lambda *a, **k: (True, 'Archived and active journals take up 260.0M '
                                               'in the file system.', ''))
    # 260M held, 100M cap -> 160M over.
    assert svc._scan_journal('100M') == int(160.0 * 1024 ** 2)
    # A journal already under the cap is not a candidate.
    assert svc._scan_journal('1G') == 0


def test_journal_scan_is_zero_without_journalctl(monkeypatch):
    monkeypatch.setattr(svc, '_run', lambda *a, **k: (False, '', 'not found'))
    assert svc._scan_journal() == 0
    assert svc._journal_bytes() == 0


def test_package_cache_reclaim_reports_the_delta_not_zero(tmp_path, monkeypatch):
    """apt-get clean empties the archives itself; a naive count afterwards
    reports 0 freed even though the space came back."""
    cache = tmp_path / 'archives'
    cache.mkdir()
    (cache / 'a.deb').write_bytes(b'x' * 5000)

    def fake_run(cmd, timeout=300):
        if cmd[:2] == ['apt-get', 'clean']:
            for child in cache.iterdir():
                child.unlink()
            return True, '', ''
        return False, '', 'n/a'

    monkeypatch.setattr(svc, '_run', fake_run)
    monkeypatch.setattr(svc, '_scan_package_caches', lambda: ([str(cache)], 5000))
    monkeypatch.setattr(svc, 'disk_usage', lambda *a, **k: None)

    result = svc.reclaim(['package-caches'])
    assert result['results'][0]['bytes'] == 5000


def test_docker_reclaim_reports_dockers_own_tally(monkeypatch):
    monkeypatch.setattr(svc, '_scan_docker', lambda: 1024)
    monkeypatch.setattr(svc, 'disk_usage', lambda *a, **k: None)

    def fake_run(cmd, timeout=300):
        if cmd[:3] == ['docker', 'image', 'prune']:
            return True, 'Total reclaimed space: 2GB', ''
        if cmd[:3] == ['docker', 'builder', 'prune']:
            return True, 'Total reclaimed space: 1GB', ''
        return False, '', ''

    monkeypatch.setattr(svc, '_run', fake_run)
    result = svc.reclaim(['docker-build-cache'])
    # 3 GB actually freed, not the 1 KB the scan could estimate up front.
    assert result['results'][0]['bytes'] == 3 * 1024 ** 3
