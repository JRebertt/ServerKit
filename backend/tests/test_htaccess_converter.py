"""Tests for the .htaccess -> nginx converter (service + API endpoint)."""
import re

import pytest

from app.services.htaccess_converter import MAX_INPUT_BYTES, convert

# Registers blueprints / url rules on the app fixture. Flask cannot unregister
# those, so these tests need a private app rather than the session-wide one
# (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app


def _nginx(text):
    return convert(text)['nginx']


def _unsupported(text):
    return convert(text)['unsupported']


# ---------------------------------------------------------------------------
# Redirect family
# ---------------------------------------------------------------------------
class TestRedirects:
    def test_redirect_301(self):
        out = _nginx('Redirect 301 /old https://example.com/new')
        assert 'rewrite ^/old(/.*)?$ https://example.com/new$1 permanent;' in out

    def test_redirect_default_status_is_302(self):
        out = _nginx('Redirect /old https://example.com/new')
        assert 'redirect;' in out
        assert 'permanent;' not in out

    def test_redirect_permanent_keyword(self):
        out = _nginx('Redirect permanent /a https://x.test/b')
        assert 'permanent;' in out

    def test_redirect_permanent_directive(self):
        out = _nginx('RedirectPermanent /a https://x.test/b')
        assert 'permanent;' in out

    def test_redirect_temp_directive(self):
        out = _nginx('RedirectTemp /a https://x.test/b')
        assert 'redirect;' in out

    def test_redirect_gone(self):
        out = _nginx('Redirect gone /dead')
        assert 'location /dead {' in out
        assert 'return 410;' in out

    def test_redirect_odd_status_uses_location(self):
        out = _nginx('Redirect 303 /a https://x.test/b')
        assert 'location = /a {' in out
        assert 'return 303 https://x.test/b;' in out

    def test_redirect_match(self):
        out = _nginx(r'RedirectMatch 301 ^/blog/(\d+)$ https://x.test/posts/$1')
        assert r'location ~ ^/blog/(\d+)$ {' in out
        assert 'return 301 https://x.test/posts/$1;' in out

    def test_redirect_match_default_302(self):
        out = _nginx('RedirectMatch ^/tmp/(.*)$ /elsewhere/$1')
        assert 'return 302 /elsewhere/$1;' in out

    def test_malformed_redirect_flagged(self):
        unsup = _unsupported('Redirect 301 /only-path')
        assert len(unsup) == 1
        assert unsup[0]['line'] == 1


# ---------------------------------------------------------------------------
# RewriteRule
# ---------------------------------------------------------------------------
class TestRewriteRule:
    def test_internal_rewrite(self):
        out = _nginx('RewriteRule ^shop/(.*)$ /store/$1')
        assert 'rewrite ^/shop/(.*)$ /store/$1;' in out

    def test_leading_slash_normalized(self):
        out = _nginx('RewriteRule ^foo$ /bar')
        assert '^/foo$' in out

    def test_l_flag_becomes_last(self):
        res = convert('RewriteRule ^a$ /b [L]')
        assert 'rewrite ^/a$ /b last;' in res['nginx']
        assert any('[L]' in n for n in res['notes'])

    def test_nc_flag_becomes_case_insensitive_prefix(self):
        res = convert('RewriteRule ^Docs/(.*)$ /documents/$1 [NC]')
        assert 'rewrite (?i)^/Docs/(.*)$ /documents/$1;' in res['nginx']
        assert any('(?i)' in n for n in res['notes'])

    def test_r301_becomes_location_return(self):
        out = _nginx('RewriteRule ^old-page$ /new-page [R=301,L]')
        assert 'location ~ ^/old-page$ {' in out
        assert 'return 301 /new-page;' in out

    def test_r_flag_alone_is_302(self):
        out = _nginx('RewriteRule ^x$ /y [R]')
        assert 'return 302 /y;' in out

    def test_backrefs_preserved_in_redirect(self):
        out = _nginx('RewriteRule ^cat/(.*)$ https://x.test/category/$1 [R=301]')
        assert 'return 301 https://x.test/category/$1;' in out

    def test_qsa_noted(self):
        res = convert('RewriteRule ^p/(.*)$ /page.php?id=$1 [QSA,L]')
        assert any('QSA' in n for n in res['notes'])

    def test_qsa_without_query_noted_as_default(self):
        res = convert('RewriteRule ^a/(.*)$ /b/$1 [QSA]')
        assert any('nginx default' in n for n in res['notes'])

    def test_relative_substitution_gets_slash(self):
        out = _nginx('RewriteRule ^a$ b.html')
        assert 'rewrite ^/a$ /b.html;' in out

    def test_forbidden_flag(self):
        out = _nginx('RewriteRule ^secret - [F]')
        assert 'return 403;' in out

    def test_gone_flag(self):
        out = _nginx('RewriteRule ^dead$ - [G]')
        assert 'return 410;' in out

    def test_passthrough_dash_flagged(self):
        unsup = _unsupported('RewriteRule ^keep$ - [L]')
        assert len(unsup) == 1
        assert 'passthrough' in unsup[0]['reason']

    def test_rewrite_engine_dropped_with_note(self):
        res = convert('RewriteEngine On\nRewriteRule ^a$ /b')
        assert 'RewriteEngine' not in res['nginx']
        assert res['unsupported'] == []
        assert any('RewriteEngine' in n for n in res['notes'])

    def test_rewrite_base_noted(self):
        res = convert('RewriteBase /subdir/')
        assert any('RewriteBase /subdir/' in n for n in res['notes'])

    def test_from_comment_present(self):
        out = _nginx('RewriteRule ^a$ /b [L]')
        assert '# from: RewriteRule ^a$ /b [L] (line 1)' in out


# ---------------------------------------------------------------------------
# Front controller (WP / Laravel) detection
# ---------------------------------------------------------------------------
class TestFrontController:
    WP = (
        '<IfModule mod_rewrite.c>\n'
        'RewriteEngine On\n'
        'RewriteBase /\n'
        'RewriteRule ^index\\.php$ - [L]\n'
        'RewriteCond %{REQUEST_FILENAME} !-f\n'
        'RewriteCond %{REQUEST_FILENAME} !-d\n'
        'RewriteRule . /index.php [L]\n'
        '</IfModule>\n'
    )

    def test_wordpress_block_becomes_try_files(self):
        res = convert(self.WP)
        assert 'try_files $uri $uri/ /index.php?$args;' in res['nginx']
        assert any('front-controller' in n for n in res['notes'])

    def test_laravel_block(self):
        text = (
            'RewriteCond %{REQUEST_FILENAME} !-d\n'
            'RewriteCond %{REQUEST_FILENAME} !-f\n'
            'RewriteRule ^ index.php [L]\n'
        )
        assert 'try_files $uri $uri/ /index.php?$args;' in _nginx(text)

    def test_html_front_controller_no_args(self):
        text = (
            'RewriteCond %{REQUEST_FILENAME} !-f\n'
            'RewriteCond %{REQUEST_FILENAME} !-d\n'
            'RewriteRule . /index.html [L]\n'
        )
        assert 'try_files $uri $uri/ /index.html;' in _nginx(text)

    def test_extra_symlink_cond_still_detected(self):
        text = (
            'RewriteCond %{REQUEST_FILENAME} !-f\n'
            'RewriteCond %{REQUEST_FILENAME} !-d\n'
            'RewriteCond %{REQUEST_FILENAME} !-l\n'
            'RewriteRule ^(.*)$ index.php [L]\n'
        )
        assert 'try_files' in _nginx(text)

    def test_only_f_cond_not_detected_as_front_controller(self):
        text = (
            'RewriteCond %{REQUEST_FILENAME} !-f\n'
            'RewriteRule . /index.php [L]\n'
        )
        res = convert(text)
        assert 'try_files' not in res['nginx']
        # Both cond and rule flagged, nothing silently dropped.
        assert len(res['unsupported']) == 2


# ---------------------------------------------------------------------------
# RewriteCond host / https handling
# ---------------------------------------------------------------------------
class TestCondRedirects:
    def test_host_redirect_literal(self):
        text = (
            'RewriteCond %{HTTP_HOST} ^example\\.com$\n'
            'RewriteRule ^(.*)$ https://www.example.com/$1 [R=301,L]\n'
        )
        res = convert(text)
        assert 'if ($host = example.com) {' in res['nginx']
        assert 'return 301 https://www.example.com$request_uri;' in res['nginx']
        assert any('dedicated server block' in n for n in res['notes'])

    def test_host_redirect_negated_regex(self):
        text = (
            'RewriteCond %{HTTP_HOST} !^www\\.\n'
            'RewriteRule ^(.*)$ https://www.example.com/$1 [R=301]\n'
        )
        out = _nginx(text)
        assert 'if ($host !~* ^www\\.) {' in out

    def test_https_off_redirect_is_commented(self):
        text = (
            'RewriteCond %{HTTPS} off\n'
            'RewriteRule ^(.*)$ https://%{HTTP_HOST}/$1 [R=301,L]\n'
        )
        res = convert(text)
        # Emitted, but only as comments — HTTPS is optional in ServerKit.
        assert '# if ($scheme = http) {' in res['nginx']
        for line in res['nginx'].splitlines():
            if 'return 301 https://$host$request_uri' in line:
                assert line.lstrip().startswith('#')
        assert any('HTTPS is optional' in n or 'HTTP->HTTPS' in n
                   for n in res['notes'])

    def test_untranslatable_cond_flags_cond_and_rule(self):
        text = (
            'RewriteCond %{REQUEST_URI} !^/admin\n'
            'RewriteRule ^(.*)$ /public/$1 [L]\n'
        )
        unsup = _unsupported(text)
        assert len(unsup) == 2
        assert unsup[0]['line'] == 1
        assert unsup[1]['line'] == 2

    def test_dangling_cond_flagged(self):
        unsup = _unsupported('RewriteCond %{HTTP_HOST} ^x$')
        assert len(unsup) == 1
        assert 'without a following RewriteRule' in unsup[0]['reason']


# ---------------------------------------------------------------------------
# Simple directives
# ---------------------------------------------------------------------------
class TestSimpleDirectives:
    def test_error_document(self):
        out = _nginx('ErrorDocument 404 /errors/404.html')
        assert 'error_page 404 /errors/404.html;' in out

    def test_error_document_url_noted(self):
        res = convert('ErrorDocument 500 https://x.test/oops')
        assert 'error_page 500 https://x.test/oops;' in res['nginx']
        assert any('302' in n for n in res['notes'])

    def test_error_document_text_message_flagged(self):
        unsup = _unsupported('ErrorDocument 403 "Access denied"')
        assert len(unsup) == 1
        assert 'text message' in unsup[0]['reason']

    def test_options_minus_indexes(self):
        assert 'autoindex off;' in _nginx('Options -Indexes')

    def test_options_plus_indexes(self):
        assert 'autoindex on;' in _nginx('Options +Indexes')

    def test_options_followsymlinks_noted_not_flagged(self):
        res = convert('Options +FollowSymLinks')
        assert res['unsupported'] == []
        assert any('FollowSymLinks' in n for n in res['notes'])

    def test_options_unknown_token_flagged(self):
        unsup = _unsupported('Options +ExecCGI')
        assert len(unsup) == 1
        assert 'ExecCGI' in unsup[0]['reason']

    def test_directory_index(self):
        out = _nginx('DirectoryIndex index.php index.html')
        assert 'index index.php index.html;' in out

    def test_add_default_charset(self):
        assert 'charset UTF-8;' in _nginx('AddDefaultCharset UTF-8')

    def test_header_set(self):
        res = convert('Header set X-Frame-Options "SAMEORIGIN"')
        assert 'add_header X-Frame-Options "SAMEORIGIN" always;' in res['nginx']
        assert any('add_header' in n for n in res['notes'])

    def test_header_always_set(self):
        out = _nginx('Header always set X-Content-Type-Options "nosniff"')
        assert 'add_header X-Content-Type-Options "nosniff" always;' in out

    def test_header_unset_flagged(self):
        unsup = _unsupported('Header unset X-Powered-By')
        assert len(unsup) == 1

    def test_header_env_conditional_flagged(self):
        unsup = _unsupported('Header set X-Foo "bar" env=HTTPS')
        assert len(unsup) == 1
        assert 'env=' in unsup[0]['reason'] or 'conditional' in unsup[0]['reason']


# ---------------------------------------------------------------------------
# Access control + basic auth
# ---------------------------------------------------------------------------
class TestAccessAndAuth:
    def test_deny_from_all(self):
        assert 'deny all;' in _nginx('Deny from all')

    def test_require_all_denied(self):
        assert 'deny all;' in _nginx('Require all denied')

    def test_require_all_granted(self):
        assert 'allow all;' in _nginx('Require all granted')

    def test_allow_from_ip_gets_deny_all(self):
        out = _nginx('Order deny,allow\nDeny from all\nAllow from 10.0.0.1')
        allow_idx = out.index('allow 10.0.0.1;')
        deny_idx = out.index('deny all;')
        assert allow_idx < deny_idx

    def test_require_ip(self):
        out = _nginx('Require ip 192.168.1.0/24')
        assert 'allow 192.168.1.0/24;' in out
        assert 'deny all;' in out

    def test_deny_specific_ip(self):
        out = _nginx('Deny from 1.2.3.4')
        assert 'deny 1.2.3.4;' in out
        assert 'deny all;' not in out

    def test_basic_auth_block(self):
        text = (
            'AuthType Basic\n'
            'AuthName "Members Only"\n'
            'AuthUserFile /home/site/.htpasswd\n'
            'Require valid-user\n'
        )
        res = convert(text)
        assert 'auth_basic "Members Only";' in res['nginx']
        assert 'auth_basic_user_file /home/site/.htpasswd;' in res['nginx']
        assert any('htpasswd' in n for n in res['notes'])

    def test_basic_auth_without_userfile_uses_placeholder(self):
        res = convert('AuthType Basic\nRequire valid-user\n')
        assert 'auth_basic_user_file /etc/nginx/.htpasswd;' in res['nginx']
        assert any('placeholder' in n for n in res['notes'])

    def test_digest_auth_flagged(self):
        unsup = _unsupported('AuthType Digest')
        assert len(unsup) == 1

    def test_require_valid_user_alone_noted(self):
        res = convert('Require valid-user')
        assert 'auth_basic' not in res['nginx']
        assert any('without a usable AuthType' in n for n in res['notes'])


# ---------------------------------------------------------------------------
# <Files> / <FilesMatch> / <IfModule> wrappers
# ---------------------------------------------------------------------------
class TestWrappers:
    def test_files_block_becomes_location(self):
        text = '<Files "wp-config.php">\nRequire all denied\n</Files>'
        out = _nginx(text)
        assert re.search(r'location ~ /wp\\?-config\\\.php\$ \{', out)
        assert 'deny all;' in out

    def test_filesmatch_block(self):
        text = '<FilesMatch "\\.(env|log)$">\nDeny from all\n</FilesMatch>'
        out = _nginx(text)
        assert 'location ~ \\.(env|log)$ {' in out
        assert 'deny all;' in out

    def test_files_wildcard(self):
        text = '<Files "*.bak">\nRequire all denied\n</Files>'
        out = _nginx(text)
        assert 'location ~ /.*\\.bak$ {' in out

    def test_unsupported_directive_inside_files_flagged(self):
        text = '<Files "x.php">\nphp_value memory_limit 256M\n</Files>'
        res = convert(text)
        assert len(res['unsupported']) == 1
        assert res['unsupported'][0]['line'] == 2

    def test_unclosed_files_block_flagged_but_flushed(self):
        text = '<Files "secret.txt">\nDeny from all\n'
        res = convert(text)
        assert 'deny all;' in res['nginx']
        assert any('never closed' in u['reason'] for u in res['unsupported'])

    def test_ifmodule_unwrapped_with_note(self):
        text = '<IfModule mod_rewrite.c>\nRewriteRule ^a$ /b\n</IfModule>'
        res = convert(text)
        assert 'rewrite ^/a$ /b;' in res['nginx']
        assert res['unsupported'] == []
        assert any('IfModule' in n and 'removed' in n for n in res['notes'])

    def test_nested_ifmodule_in_files(self):
        text = (
            '<Files "a.txt">\n'
            '<IfModule mod_authz_core.c>\n'
            'Require all denied\n'
            '</IfModule>\n'
            '</Files>\n'
        )
        out = _nginx(text)
        assert 'deny all;' in out

    def test_unknown_block_flagged_contents_scanned(self):
        text = '<Limit GET POST>\nDeny from all\n</Limit>'
        res = convert(text)
        assert any('<Limit' in u['directive'] for u in res['unsupported'])
        # Contents still scanned, not silently dropped.
        assert 'deny all;' in res['nginx']


# ---------------------------------------------------------------------------
# Unsupported directives (never silently dropped)
# ---------------------------------------------------------------------------
class TestUnsupported:
    def test_mod_deflate_flagged_with_reason(self):
        unsup = _unsupported('AddOutputFilterByType DEFLATE text/html')
        assert len(unsup) == 1
        assert 'gzip' in unsup[0]['reason']

    def test_mod_expires_flagged(self):
        unsup = _unsupported('ExpiresByType image/png "access plus 1 month"')
        assert 'expires' in unsup[0]['reason']

    def test_php_value_flagged(self):
        unsup = _unsupported('php_value upload_max_filesize 64M')
        assert 'PHP-FPM' in unsup[0]['reason']

    def test_setenv_flagged(self):
        unsup = _unsupported('SetEnv APP_ENV production')
        assert len(unsup) == 1

    def test_unknown_directive_flagged(self):
        unsup = _unsupported('FancyIndexing on')
        assert len(unsup) == 1
        assert 'unrecognized' in unsup[0]['reason']

    def test_line_numbers_accurate(self):
        text = 'Options -Indexes\n\n# comment\nphp_flag display_errors off\nSetEnv X 1\n'
        unsup = _unsupported(text)
        assert [u['line'] for u in unsup] == [4, 5]

    def test_directive_text_included(self):
        unsup = _unsupported('SetEnv FOO bar')
        assert unsup[0]['directive'] == 'SetEnv FOO bar'


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------
class TestRobustness:
    def test_empty_input(self):
        res = convert('')
        assert res == {'nginx': '', 'notes': [], 'unsupported': []}

    def test_none_input(self):
        res = convert(None)
        assert res['nginx'] == ''

    def test_whitespace_and_comments_only(self):
        res = convert('# just a comment\n\n   \n# another\n')
        assert res['nginx'] == ''
        assert res['unsupported'] == []

    def test_garbage_input_safe(self):
        res = convert('!!! not apache at all ~~~\x00\nRewriteRule ^a$ /b\n')
        assert 'rewrite ^/a$ /b;' in res['nginx']
        assert len(res['unsupported']) == 1

    def test_line_continuations_merged(self):
        text = 'Header set X-Long \\\n"value"\n'
        assert 'add_header X-Long "value" always;' in _nginx(text)

    def test_no_server_wrapper_ever_emitted(self):
        text = (
            'RewriteEngine On\n'
            'Redirect 301 /a https://x.test/b\n'
            'ErrorDocument 404 /404.html\n'
            'Options -Indexes\n'
        )
        out = _nginx(text)
        assert 'server {' not in out
        assert 'http {' not in out

    def test_over_256kb_raises(self):
        big = 'Options -Indexes\n' * (MAX_INPUT_BYTES // 10)
        assert len(big.encode()) > MAX_INPUT_BYTES
        with pytest.raises(ValueError):
            convert(big)

    def test_exactly_at_cap_ok(self):
        pad = '#' + 'x' * (MAX_INPUT_BYTES - 2) + '\n'
        assert len(pad.encode()) == MAX_INPUT_BYTES
        res = convert(pad)
        assert res['nginx'] == ''

    def test_non_string_raises(self):
        with pytest.raises(ValueError):
            convert(12345)

    def test_kitchen_sink_ordering_stable(self):
        text = (
            'Options -Indexes\n'
            'DirectoryIndex index.php\n'
            'ErrorDocument 404 /404.html\n'
            '<Files ".htpasswd">\n'
            'Require all denied\n'
            '</Files>\n'
        )
        out = _nginx(text)
        assert out.index('autoindex off;') < out.index('index index.php;')
        assert out.index('index index.php;') < out.index('error_page 404 /404.html;')
        assert 'location ~' in out


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------
def _ensure_bp(app):
    """Register the blueprint name-guarded (wiring into app/__init__.py is
    owned by another change; the endpoint contract is tested here)."""
    if 'htaccess_tools' not in app.blueprints:
        from app.api.htaccess_tools import htaccess_tools_bp
        app.register_blueprint(htaccess_tools_bp, url_prefix='/api/v1/apps')


class TestApi:
    def test_requires_auth(self, app, client):
        _ensure_bp(app)
        resp = client.post('/api/v1/apps/htaccess-convert',
                           json={'htaccess': 'Options -Indexes'})
        assert resp.status_code == 401

    def test_happy_path(self, app, client, auth_headers):
        _ensure_bp(app)
        resp = client.post(
            '/api/v1/apps/htaccess-convert',
            json={'htaccess': 'Options -Indexes\nSetEnv FOO bar\n'},
            headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'autoindex off;' in data['nginx']
        assert isinstance(data['notes'], list)
        assert len(data['unsupported']) == 1
        assert data['unsupported'][0]['line'] == 2

    def test_missing_body_400(self, app, client, auth_headers):
        _ensure_bp(app)
        resp = client.post('/api/v1/apps/htaccess-convert', json={},
                           headers=auth_headers)
        assert resp.status_code == 400
        assert 'error' in resp.get_json()

    def test_blank_text_400(self, app, client, auth_headers):
        _ensure_bp(app)
        resp = client.post('/api/v1/apps/htaccess-convert',
                           json={'htaccess': '   '}, headers=auth_headers)
        assert resp.status_code == 400

    def test_non_string_400(self, app, client, auth_headers):
        _ensure_bp(app)
        resp = client.post('/api/v1/apps/htaccess-convert',
                           json={'htaccess': 42}, headers=auth_headers)
        assert resp.status_code == 400

    def test_oversize_413(self, app, client, auth_headers):
        _ensure_bp(app)
        big = 'Options -Indexes\n' * (MAX_INPUT_BYTES // 10)
        resp = client.post('/api/v1/apps/htaccess-convert',
                           json={'htaccess': big}, headers=auth_headers)
        assert resp.status_code == 413
        assert 'error' in resp.get_json()
