"""Per-site brute-force jail layer (Fail2banJailService) — pure unit tests.

No real fail2ban or filesystem: privileged writes/reads and os.path.exists are
mocked, so these assert the *rendered* filter/jail configs, the ownership +
traversal guards, and graceful degradation — the same style as
test_nginx_remote_upstream (assert the generated config, not a live daemon).
"""
import os
import types
from unittest.mock import patch, MagicMock

import pytest

from app.services.fail2ban_jail_service import Fail2banJailService as F2B
from app.services.nginx_service import NginxService
from app.services import wordpress_bridge


def _app(name='myblog'):
    return types.SimpleNamespace(name=name, port=8300)


def _ok(stdout='', stderr=''):
    """CompletedProcess-like stub for run_privileged."""
    return types.SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr)


# ---------- rendered configs ----------

def test_filter_targets_wp_login_and_xmlrpc():
    c = F2B.FILTER_CONTENT
    assert '[Definition]' in c
    assert '<HOST>' in c                 # fail2ban IP capture present
    assert r'wp-login\.php' in c
    assert r'xmlrpc\.php' in c


def test_jail_render_uses_nginx_log_path_and_thresholds():
    logpath = NginxService.site_access_log_path('myblog')
    jail = F2B._render_jail(_app('myblog'), logpath, None, None, None)
    assert '[serverkit-myblog]' in jail
    assert 'enabled = true' in jail
    assert 'filter = serverkit-wp-login' in jail
    assert f'logpath = {logpath}' in jail
    assert f'maxretry = {F2B.MAXRETRY}' in jail
    assert f'findtime = {F2B.FINDTIME}' in jail
    assert f'bantime = {F2B.BANTIME}' in jail
    # the jail watches the exact file nginx writes for the site
    assert logpath == '/var/log/nginx/myblog.access.log'


def test_jail_render_honours_threshold_overrides():
    jail = F2B._render_jail(_app(), '/var/log/nginx/x.access.log', 3, 120, 900)
    assert 'maxretry = 3' in jail
    assert 'findtime = 120' in jail
    assert 'bantime = 900' in jail


# ---------- naming / ownership / traversal guards ----------

@pytest.mark.parametrize('raw,expected', [
    ('myblog', 'serverkit-myblog'),
    ('My Blog!', 'serverkit-My-Blog'),
    ('../../etc/passwd', 'serverkit-etc-passwd'),
    ('a.b.c', 'serverkit-a-b-c'),
    ('', 'serverkit-site'),
])
def test_jail_name_is_sanitized_and_prefixed(raw, expected):
    name = F2B.jail_name(_app(raw))
    assert name == expected
    # never contains a path separator or traversal sequence
    assert '/' not in name and '\\' not in name and '..' not in name


def test_jail_path_cannot_escape_jail_dir():
    # Even a traversal-style name resolves to a serverkit-owned file *inside*
    # JAIL_DIR — this is the structural ownership guard.
    p = F2B._jail_path(_app('../../evil'))
    assert os.path.dirname(p) == F2B.JAIL_DIR
    assert os.path.basename(p).startswith('serverkit-')
    assert os.path.basename(p).endswith('.conf')


# ---------- graceful degradation (Windows / no fail2ban) ----------

def test_enable_and_disable_skip_when_unavailable():
    with patch.object(F2B, 'available', return_value=False):
        en = F2B.enable_wp_jail(_app())
        dis = F2B.disable_jail(_app())
    for res in (en, dis):
        assert res['success'] is True
        assert res['skipped'] is True
        assert res['available'] is False


def test_enable_requires_app_name():
    with patch.object(F2B, 'available', return_value=True):
        res = F2B.enable_wp_jail(types.SimpleNamespace(name=''))
    assert res['success'] is False


# ---------- lifecycle (mocked privileged calls) ----------

def test_enable_writes_filter_and_jail_then_reloads(fake_subprocess):
    # Scripted through the shared seam (plan 75 §G7): the config write now goes
    # through write_privileged_file, so a stub pinned to this module's imported
    # `run_privileged` would quietly stop seeing it.
    for cmd in (['tee'], ['touch'], ['fail2ban-client']):
        fake_subprocess.script(cmd)

    with patch.object(F2B, 'available', return_value=True), \
            patch.object(F2B, '_read_text', return_value=None):
        res = F2B.enable_wp_jail(_app('myblog'))

    writes = fake_subprocess.writes()

    assert res['success'] is True and res['enabled'] is True
    assert res['jail'] == 'serverkit-myblog'

    filter_path = os.path.join(F2B.FILTER_DIR, 'serverkit-wp-login.conf')
    jail_path = os.path.join(F2B.JAIL_DIR, 'serverkit-myblog.conf')
    assert filter_path in writes and r'wp-login\.php' in writes[filter_path]
    assert jail_path in writes
    assert 'logpath = /var/log/nginx/myblog.access.log' in writes[jail_path]

    # the logpath was touched, and fail2ban was reloaded (not restarted)
    cmds = fake_subprocess.commands()
    assert ['touch', '/var/log/nginx/myblog.access.log'] in cmds
    assert ['fail2ban-client', 'reload'] in cmds


def test_disable_removes_only_serverkit_jail_file():
    removed = {}

    def fake_run(cmd, **kwargs):
        if cmd[:1] == ['rm']:
            removed['path'] = cmd[-1]
        return _ok()

    with patch.object(F2B, 'available', return_value=True), \
            patch('app.services.fail2ban_jail_service.os.path.exists', return_value=True), \
            patch('app.services.fail2ban_jail_service.run_privileged', side_effect=fake_run):
        res = F2B.disable_jail(_app('myblog'))

    assert res['success'] is True and res['removed'] is True
    assert removed['path'] == os.path.join(F2B.JAIL_DIR, 'serverkit-myblog.conf')
    assert os.path.basename(removed['path']).startswith('serverkit-')


def test_disable_is_noop_when_no_jail_file():
    with patch.object(F2B, 'available', return_value=True), \
            patch('app.services.fail2ban_jail_service.os.path.exists', return_value=False), \
            patch('app.services.fail2ban_jail_service.run_privileged') as rp:
        res = F2B.disable_jail(_app('myblog'))
    assert res['success'] is True and res['removed'] is False
    rp.assert_not_called()


def test_get_status_shape_when_jail_absent():
    sec = MagicMock()
    sec.get_fail2ban_status.return_value = {'installed': True, 'service_running': False}
    with patch.object(F2B, 'available', return_value=True), \
            patch('app.services.fail2ban_jail_service.os.path.exists', return_value=False), \
            patch('app.services.security_service.SecurityService', sec):
        st = F2B.get_status(_app('myblog'))
    assert st['available'] is True
    assert st['enabled'] is False
    assert st['jail'] == 'serverkit-myblog'
    assert st['thresholds']['maxretry'] == F2B.MAXRETRY
    assert st['fail2ban_running'] is False


# ---------- generic jail engine (plan 52 — reusable beyond WordPress) ----------

def test_enable_jail_generic_writes_custom_filter_jail_and_port(fake_subprocess):
    """The generic engine any vertical can use (e.g. a game-server login jail):
    an arbitrary serverkit-* filter, a custom logpath, and a non-web port."""
    for cmd in (['tee'], ['touch'], ['fail2ban-client']):
        fake_subprocess.script(cmd)

    custom_filter = ('# ServerKit game-server login filter.\n[Definition]\n'
                     'failregex = ^.*Failed login from <HOST>\nignoreregex =\n')
    with patch.object(F2B, 'available', return_value=True), \
            patch.object(F2B, '_read_text', return_value=None):
        res = F2B.enable_jail(
            'mc survival', filter_name='serverkit-mc-login',
            filter_content=custom_filter, logpath='/var/log/mc/console.log',
            maxretry=4, findtime=300, bantime=1800, port='25565', site_label='MC Survival')

    writes = fake_subprocess.writes()
    assert res['success'] is True and res['enabled'] is True
    # key is sanitized + prefixed like any jail
    assert res['jail'] == 'serverkit-mc-survival'

    filter_path = os.path.join(F2B.FILTER_DIR, 'serverkit-mc-login.conf')
    jail_path = os.path.join(F2B.JAIL_DIR, 'serverkit-mc-survival.conf')
    assert filter_path in writes and 'Failed login from <HOST>' in writes[filter_path]
    jail = writes[jail_path]
    assert '[serverkit-mc-survival]' in jail
    assert 'filter = serverkit-mc-login' in jail
    assert 'logpath = /var/log/mc/console.log' in jail
    assert 'port = 25565' in jail
    assert 'maxretry = 4' in jail and 'findtime = 300' in jail and 'bantime = 1800' in jail


def test_ensure_filter_rejects_non_serverkit_name():
    with patch.object(F2B, 'available', return_value=True):
        res = F2B.ensure_filter('evil-filter', '[Definition]\n')
    assert res['success'] is False
    assert 'serverkit-' in res['error']


def test_remove_jail_by_key_targets_serverkit_file():
    removed = {}

    def fake_run(cmd, **kwargs):
        if cmd[:1] == ['rm']:
            removed['path'] = cmd[-1]
        return _ok()

    with patch.object(F2B, 'available', return_value=True), \
            patch('app.services.fail2ban_jail_service.os.path.exists', return_value=True), \
            patch('app.services.fail2ban_jail_service.run_privileged', side_effect=fake_run):
        res = F2B.remove_jail('mc survival')

    assert res['success'] is True and res['removed'] is True
    assert removed['path'] == os.path.join(F2B.JAIL_DIR, 'serverkit-mc-survival.conf')


# ---------- WpSecurityService wrapper ----------

def test_wp_security_set_brute_force_delegates_to_jail_service(wp_extension_package):
    WpSecurityService = wordpress_bridge.get('wp_security_service', 'WpSecurityService')
    app = _app('myblog')
    site = types.SimpleNamespace(application=app)
    with patch.object(F2B, 'enable_wp_jail', return_value={'success': True}) as en, \
            patch.object(F2B, 'disable_jail', return_value={'success': True}) as dis:
        r_on = WpSecurityService.set_brute_force(site, True)
        r_off = WpSecurityService.set_brute_force(site, False)
    en.assert_called_once_with(app)
    dis.assert_called_once_with(app)
    assert r_on['success'] and r_off['success']


def test_wp_security_brute_force_handles_missing_application(wp_extension_package):
    WpSecurityService = wordpress_bridge.get('wp_security_service', 'WpSecurityService')
    site = types.SimpleNamespace(application=None)
    assert WpSecurityService.set_brute_force(site, True)['success'] is False
    assert WpSecurityService.get_brute_force(site)['no_application'] is True


# ---------- rename orphans: list_jails + cleanup_orphans (plan 82 §F.2) ----- #
# The jail filename derives from the site name at ENABLE time. Rename the
# site and disable_jail() derives a path that no longer exists — it honestly
# reports removed: False, but the stale jail keeps banning against a log
# nginx no longer writes. list_jails() (directory scan) + cleanup_orphans()
# are the recovery path these tests pin.

def _write_jail(jail_dir, key, site=None):
    jail = F2B.jail_name_for_key(key)
    content = F2B._render_jail_config(
        jail=jail, site=site or key, filter_name=F2B._sanitize(F2B.WP_FILTER),
        logpath=f'/var/log/nginx/{key}.access.log',
        maxretry=None, findtime=None, bantime=None)
    (jail_dir / f'{jail}.conf').write_text(content)
    return jail


def test_rename_orphans_jail_and_disable_reports_not_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(F2B, 'JAIL_DIR', str(tmp_path))
    _write_jail(tmp_path, 'myshop')

    with patch.object(F2B, 'available', return_value=True):
        res = F2B.disable_jail(_app('shop'))  # renamed since enable

    assert res['success'] is True and res['removed'] is False
    # ...and the stale jail is still on disk, visible only to the scan:
    assert [j['jail'] for j in F2B.list_jails()] == ['serverkit-myshop']


def test_list_jails_parses_site_and_logpath(tmp_path, monkeypatch):
    monkeypatch.setattr(F2B, 'JAIL_DIR', str(tmp_path))
    _write_jail(tmp_path, 'myshop', site='My Shop')
    (tmp_path / 'operator-own.conf').write_text('[sshd]\n')  # not ours: ignored

    jails = F2B.list_jails()
    assert len(jails) == 1
    assert jails[0]['site'] == 'My Shop'
    assert jails[0]['logpath'] == '/var/log/nginx/myshop.access.log'


def test_cleanup_orphans_removes_only_derelict_serverkit_jails(tmp_path, monkeypatch):
    monkeypatch.setattr(F2B, 'JAIL_DIR', str(tmp_path))
    _write_jail(tmp_path, 'live-site')
    _write_jail(tmp_path, 'renamed-away')
    (tmp_path / 'operator-own.conf').write_text('[sshd]\n')

    def fake_rm(cmd, **kwargs):
        assert cmd[:2] == ['rm', '-f']
        os.remove(cmd[2])
        return _ok()

    with patch.object(F2B, 'available', return_value=True), \
            patch.object(F2B, 'reload', return_value={'success': True}), \
            patch('app.services.fail2ban_jail_service.run_privileged', side_effect=fake_rm):
        res = F2B.cleanup_orphans(['live-site', 'other-live'])

    assert res['success'] is True
    assert res['removed'] == ['serverkit-renamed-away']
    assert (tmp_path / 'serverkit-live-site.conf').exists()
    assert (tmp_path / 'operator-own.conf').exists()  # never touched


def test_cleanup_orphans_no_orphans_no_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(F2B, 'JAIL_DIR', str(tmp_path))
    _write_jail(tmp_path, 'live-site')

    with patch.object(F2B, 'available', return_value=True), \
            patch.object(F2B, 'reload') as rel:
        res = F2B.cleanup_orphans(['live-site'])

    assert res['success'] is True and res['removed'] == []
    rel.assert_not_called()


def test_sanitize_collision_is_a_shared_jail_documented(tmp_path, monkeypatch):
    """'my.site' and 'my site' collapse to the same key, so two such sites
    SHARE one jail file — last enable wins its thresholds/logpath, and
    disabling either removes the other's protection. Pinned here as known
    behavior: changing the derivation would orphan every existing install's
    jail files, so the cure is worse than the disease. Renames/collisions
    are handled operationally via list_jails + cleanup_orphans."""
    assert F2B.jail_name_for_key('my.site') == F2B.jail_name_for_key('my site')
