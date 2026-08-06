"""Phase 2 proving tests — the WordPress URL-swap tool.

Changing a site's URL is a serialization-safe DB rewrite (WP-CLI search-replace),
backed up first and rolled back on failure, then a Domain/nginx re-point.
"""
from app.services import wordpress_bridge


def _mk_user(db, username='owner'):
    from app.models import User
    from werkzeug.security import generate_password_hash
    u = User(email=f'{username}@test.local', username=username,
             password_hash=generate_password_hash('x'),
             role=User.ROLE_ADMIN, is_active=True)
    db.session.add(u)
    db.session.commit()
    return u


def _mk_site_app(db, user_id, name='blog', port=8300, host='blog.lvh.me'):
    from app.models import Application
    from app.models.domain import Domain
    a = Application(name=name, app_type='docker', user_id=user_id,
                    root_path=f'/srv/{name}', port=port)
    db.session.add(a)
    db.session.commit()
    db.session.add(Domain(name=host, is_primary=True, application_id=a.id))
    db.session.commit()
    return a


# ── pure helpers ────────────────────────────────────────────────────────────

def test_normalize_url(wp_extension_package):
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')
    assert WordPressService._normalize_url('example.com') == 'http://example.com'
    assert WordPressService._normalize_url('https://example.com/') == 'https://example.com'
    assert WordPressService._normalize_url('  https://a.com/blog/  ') == 'https://a.com/blog'
    assert WordPressService._normalize_url('not a url') is None
    assert WordPressService._normalize_url('') is None


def test_url_swap_pairs(wp_extension_package):
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')
    # Host change -> full-URL pair (covers scheme) + host-only pair.
    assert WordPressService._url_swap_pairs('http://old.com', 'https://new.com') == [
        ('http://old.com', 'https://new.com'), ('old.com', 'new.com')]
    # Scheme-only change -> single full-URL pair (same host).
    assert WordPressService._url_swap_pairs('http://a.com', 'https://a.com') == [
        ('http://a.com', 'https://a.com')]


def test_parse_sr_count(wp_extension_package):
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')
    assert WordPressService._parse_sr_count('Success: 12 replacements to be made.') == 12
    assert WordPressService._parse_sr_count('Table\tx\nSuccess: Made 1,234 replacements.') == 1234
    assert WordPressService._parse_sr_count('') == 0
    assert WordPressService._parse_sr_count('nothing here') == 0


# ── preview ─────────────────────────────────────────────────────────────────

def test_preview_counts_per_pair(app, monkeypatch, wp_extension_package):
    from app import db
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')

    user = _mk_user(db)
    app_row = _mk_site_app(db, user.id, host='old.lvh.me')

    def fake_wp_cli(cls, path, command, *a, **k):
        if command[:2] == ['option', 'get']:
            return {'success': True, 'output': 'http://old.lvh.me\n'}
        if command[0] == 'search-replace':
            return {'success': True, 'output': 'Success: 5 replacements to be made.'}
        return {'success': True, 'output': ''}

    monkeypatch.setattr(WordPressService, 'wp_cli', classmethod(fake_wp_cli))

    res = WordPressService.preview_url_change(app_row, 'http://new.lvh.me')
    assert res['success'] is True
    assert res['current_url'] == 'http://old.lvh.me'
    assert res['new_url'] == 'http://new.lvh.me'
    assert len(res['pairs']) == 2     # full URL + host-only
    assert res['total'] == 10         # 5 per pair


def test_preview_rejects_same_url(app, monkeypatch, wp_extension_package):
    from app import db
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')
    user = _mk_user(db, 'o2')
    app_row = _mk_site_app(db, user.id, host='same.lvh.me')
    monkeypatch.setattr(WordPressService, 'wp_cli',
                        classmethod(lambda cls, path, command, *a, **k: {'success': True, 'output': 'http://same.lvh.me'}))
    res = WordPressService.preview_url_change(app_row, 'http://same.lvh.me')
    assert res['success'] is False
    assert 'same' in res['error'].lower()


# ── apply ───────────────────────────────────────────────────────────────────

def test_change_url_happy_path_repoints_domain(app, monkeypatch, wp_extension_package):
    from app import db
    from app.models.domain import Domain
    from app.services import nginx_service
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')

    user = _mk_user(db, 'o3')
    app_row = _mk_site_app(db, user.id, name='shop', host='old.lvh.me')

    def fake_wp_cli(cls, path, command, *a, **k):
        if command[:2] == ['option', 'get']:
            return {'success': True, 'output': 'http://old.lvh.me'}
        if command[0] == 'search-replace':
            return {'success': True, 'output': 'Success: Made 6 replacements.'}
        return {'success': True, 'output': ''}

    monkeypatch.setattr(WordPressService, 'wp_cli', classmethod(fake_wp_cli))
    monkeypatch.setattr(WordPressService, 'backup_wordpress',
                        classmethod(lambda cls, path, include_db=True: {'success': True, 'backup_name': 'bk1'}))
    monkeypatch.setattr(nginx_service.NginxService, 'create_site',
                        classmethod(lambda cls, **kw: {'success': True}))
    monkeypatch.setattr(nginx_service.NginxService, 'enable_site',
                        classmethod(lambda cls, name: {'success': True}))

    res = WordPressService.change_site_url(app_row, 'https://new.example.com', keep_old_redirect=False)
    assert res['success'] is True
    assert res['old_url'] == 'http://old.lvh.me'
    assert res['new_url'] == 'https://new.example.com'
    assert res['replacements'] == 12   # 6 per pair * 2 pairs (host changed)
    assert res['backup'] == 'bk1'

    # Domain re-pointed: new host primary, old removed (keep_old_redirect=False).
    names = {d.name: d.is_primary for d in Domain.query.filter_by(application_id=app_row.id).all()}
    assert names == {'new.example.com': True}


def test_change_url_rolls_back_on_failure(app, monkeypatch, wp_extension_package):
    from app import db
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')

    user = _mk_user(db, 'o4')
    app_row = _mk_site_app(db, user.id, name='blogx', host='old.lvh.me')

    restored = {'called': False}

    def fake_wp_cli(cls, path, command, *a, **k):
        if command[:2] == ['option', 'get']:
            return {'success': True, 'output': 'http://old.lvh.me'}
        if command[0] == 'search-replace':
            return {'success': False, 'error': 'boom'}
        return {'success': True, 'output': ''}

    def fake_restore(cls, name, target):
        restored['called'] = True
        return {'success': True}

    monkeypatch.setattr(WordPressService, 'wp_cli', classmethod(fake_wp_cli))
    monkeypatch.setattr(WordPressService, 'backup_wordpress',
                        classmethod(lambda cls, path, include_db=True: {'success': True, 'backup_name': 'bk2'}))
    monkeypatch.setattr(WordPressService, 'restore_backup', classmethod(fake_restore))

    res = WordPressService.change_site_url(app_row, 'https://new.example.com')
    assert res['success'] is False
    assert restored['called'] is True
    assert res['rolled_back'] is True
    assert 'boom' in res['error']


def test_change_url_aborts_if_backup_fails(app, monkeypatch, wp_extension_package):
    from app import db
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')

    user = _mk_user(db, 'o5')
    app_row = _mk_site_app(db, user.id, name='blogy', host='old.lvh.me')

    monkeypatch.setattr(WordPressService, 'wp_cli',
                        classmethod(lambda cls, path, command, *a, **k: {'success': True, 'output': 'http://old.lvh.me'}))
    monkeypatch.setattr(WordPressService, 'backup_wordpress',
                        classmethod(lambda cls, path, include_db=True: {'success': False, 'error': 'disk full'}))

    res = WordPressService.change_site_url(app_row, 'https://new.example.com')
    assert res['success'] is False
    assert 'backup failed' in res['error'].lower()


def test_repoint_keep_old_demotes_but_keeps(app, wp_extension_package):
    from app import db
    from app.models.domain import Domain
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')

    user = _mk_user(db, 'o6')
    app_row = _mk_site_app(db, user.id, name='keepblog', host='old.lvh.me')

    warn = WordPressService._repoint_primary_domain(app_row, 'new.lvh.me', keep_old=True)
    assert warn is None
    rows = {d.name: d.is_primary for d in Domain.query.filter_by(application_id=app_row.id).all()}
    assert rows == {'old.lvh.me': False, 'new.lvh.me': True}


# ── API wiring ──────────────────────────────────────────────────────────────

def test_url_preview_api_smoke(app, client, auth_headers, monkeypatch, wp_extension):
    from app import db
    from app.models import User
    WordPressService = wordpress_bridge.get('wordpress_service', 'WordPressService')

    admin = User.query.filter_by(username='testadmin').first()
    app_row = _mk_site_app(db, admin.id, name='apisite', host='api.lvh.me')
    monkeypatch.setattr(WordPressService, 'preview_url_change',
                        classmethod(lambda cls, a, new_url: {'success': True, 'total': 3, 'pairs': [],
                                                             'current_url': 'http://api.lvh.me', 'new_url': new_url}))
    r = client.post(f'/api/v1/wordpress/sites/{app_row.id}/url/preview',
                    json={'new_url': 'http://x.com'}, headers=auth_headers)
    assert r.status_code == 200
    body = r.get_json()
    assert body['total'] == 3
    assert body['new_url'] == 'http://x.com'
