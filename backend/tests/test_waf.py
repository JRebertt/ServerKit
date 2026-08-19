"""Tests for the per-application WAF (ModSecurity v3 + OWASP CRS) feature."""
import json
import uuid

import pytest

from app import db
from app.models import Application
from app.models.waf_policy import WafPolicy
from app.services.waf_service import WafService
from factories import make_application


def _seed_app(name='web'):
    return make_application(db, name=name)


# ---------------------------------------------------------------------------
# Pure renderer: render_rules
# ---------------------------------------------------------------------------
class TestRenderRules:
    def test_block_mode_engine_on(self, app):
        a = _seed_app()
        policy = WafService.get_or_create_policy(a.id)
        policy.mode = 'block'
        rules = WafService.render_rules(policy)
        assert 'SecRuleEngine On' in rules
        assert 'DetectionOnly' not in rules

    def test_detect_mode_detection_only(self, app):
        a = _seed_app()
        policy = WafService.get_or_create_policy(a.id)
        policy.mode = 'detect'
        rules = WafService.render_rules(policy)
        assert 'SecRuleEngine DetectionOnly' in rules

    def test_off_mode_engine_off(self, app):
        a = _seed_app()
        policy = WafService.get_or_create_policy(a.id)
        policy.mode = 'off'
        rules = WafService.render_rules(policy)
        assert 'SecRuleEngine Off' in rules
        # 'off' must not pull in the CRS.
        assert 'Include' not in rules

    def test_disabled_rule_ids_produce_remove_lines(self, app):
        a = _seed_app()
        policy = WafService.get_or_create_policy(a.id)
        policy.mode = 'block'
        policy.disabled_rules = ['942100', '920350']
        rules = WafService.render_rules(policy)
        assert 'SecRuleRemoveById 942100' in rules
        assert 'SecRuleRemoveById 920350' in rules

    def test_paranoia_and_anomaly_appear(self, app):
        a = _seed_app()
        policy = WafService.get_or_create_policy(a.id)
        policy.mode = 'block'
        policy.paranoia_level = 3
        policy.anomaly_threshold = 10
        rules = WafService.render_rules(policy)
        assert 'tx.blocking_paranoia_level=3' in rules
        assert 'tx.inbound_anomaly_score_threshold=10' in rules

    def test_crs_included_when_enforcing(self, app):
        a = _seed_app()
        policy = WafService.get_or_create_policy(a.id)
        policy.mode = 'block'
        rules = WafService.render_rules(policy, crs_path='/custom/crs.load')
        assert 'Include /custom/crs.load' in rules

    def test_non_numeric_disabled_rules_are_dropped(self, app):
        a = _seed_app()
        policy = WafService.get_or_create_policy(a.id)
        policy.mode = 'block'
        policy.disabled_rules = ['942100', 'evil; rm -rf /']
        rules = WafService.render_rules(policy)
        assert 'SecRuleRemoveById 942100' in rules
        assert 'rm -rf' not in rules


# ---------------------------------------------------------------------------
# Pure renderer: nginx_snippet
# ---------------------------------------------------------------------------
class TestNginxSnippet:
    def test_snippet_on(self, app):
        a = _seed_app()
        policy = WafService.get_or_create_policy(a.id)
        policy.mode = 'block'
        snippet = WafService.nginx_snippet(policy, '/etc/nginx/serverkit-conf.d/waf/app-1.conf')
        assert 'modsecurity on;' in snippet
        assert 'modsecurity_rules_file /etc/nginx/serverkit-conf.d/waf/app-1.conf;' in snippet

    def test_snippet_off(self, app):
        a = _seed_app()
        policy = WafService.get_or_create_policy(a.id)
        policy.mode = 'off'
        snippet = WafService.nginx_snippet(policy, '/x.conf')
        assert 'modsecurity off;' in snippet
        assert 'modsecurity_rules_file' not in snippet

    def test_detect_mode_turns_modsecurity_on(self, app):
        a = _seed_app()
        policy = WafService.get_or_create_policy(a.id)
        policy.mode = 'detect'
        snippet = WafService.nginx_snippet(policy, '/x.conf')
        assert 'modsecurity on;' in snippet


# ---------------------------------------------------------------------------
# Policy validation: set_policy
# ---------------------------------------------------------------------------
class TestSetPolicy:
    def test_rejects_invalid_mode(self, app):
        a = _seed_app()
        with pytest.raises(ValueError):
            WafService.set_policy(a.id, mode='nonsense')

    def test_clamps_paranoia_high(self, app):
        a = _seed_app()
        policy = WafService.set_policy(a.id, paranoia_level=99)
        assert policy.paranoia_level == 4

    def test_clamps_paranoia_low(self, app):
        a = _seed_app()
        policy = WafService.set_policy(a.id, paranoia_level=0)
        assert policy.paranoia_level == 1

    def test_accepts_valid_mode_and_persists(self, app):
        a = _seed_app()
        WafService.set_policy(a.id, mode='block', anomaly_threshold=7)
        policy = WafPolicy.query.filter_by(application_id=a.id).first()
        assert policy.mode == 'block'
        assert policy.anomaly_threshold == 7

    def test_disabled_rule_ids_round_trip(self, app):
        a = _seed_app()
        policy = WafService.set_policy(a.id, disabled_rule_ids=['942100', '920350'])
        assert policy.disabled_rules == ['942100', '920350']
        # Survives a reload from the DB.
        again = WafPolicy.query.filter_by(application_id=a.id).first()
        assert again.to_dict()['disabled_rule_ids'] == ['942100', '920350']

    def test_disabled_rule_ids_must_be_list(self, app):
        a = _seed_app()
        with pytest.raises(ValueError):
            WafService.set_policy(a.id, disabled_rule_ids='942100')


# ---------------------------------------------------------------------------
# Audit-log parsing: events
# ---------------------------------------------------------------------------
SAMPLE_AUDIT_LINES = [
    json.dumps({
        "transaction": {
            "client_ip": "203.0.113.7",
            "time": "2026-06-19T12:00:01Z",
        },
        "request": {"uri": "/login?id=1' OR '1'='1"},
        "audit_data": {
            "messages": [
                {
                    "message": "SQL Injection Attack Detected",
                    "details": {"ruleId": "942100", "severity": "CRITICAL"},
                }
            ]
        },
    }),
    "this is not valid json {{{",  # malformed line — must be tolerated
    json.dumps({
        "transaction": {
            "client_ip": "198.51.100.4",
            "time": "2026-06-19T12:00:05Z",
        },
        "request": {"uri": "/admin"},
        "audit_data": {
            "messages": [
                "ModSecurity: Access denied [id \"920350\"] [severity \"WARNING\"]"
            ]
        },
    }),
]


class TestEvents:
    def _write_log(self, tmp_path):
        log = tmp_path / 'modsec_audit.log'
        log.write_text('\n'.join(SAMPLE_AUDIT_LINES) + '\n')
        return str(log)

    def test_parses_expected_count(self, app, tmp_path):
        log = self._write_log(tmp_path)
        events = WafService.events(application_id=1, log_path=log)
        # Two valid transactions -> two events; malformed line skipped.
        assert len(events) == 2

    def test_parses_structured_fields(self, app, tmp_path):
        log = self._write_log(tmp_path)
        events = WafService.events(application_id=1, log_path=log)
        # Newest first.
        ids = {e['rule_id'] for e in events}
        assert '942100' in ids
        assert '920350' in ids
        sqli = next(e for e in events if e['rule_id'] == '942100')
        assert sqli['client_ip'] == '203.0.113.7'
        assert sqli['severity'] == 'CRITICAL'
        assert sqli['uri'].startswith('/login')
        assert sqli['timestamp'] == '2026-06-19T12:00:01Z'

    def test_parses_string_message_fields(self, app, tmp_path):
        log = self._write_log(tmp_path)
        events = WafService.events(application_id=1, log_path=log)
        denied = next(e for e in events if e['rule_id'] == '920350')
        assert denied['severity'] == 'WARNING'
        assert denied['client_ip'] == '198.51.100.4'

    def test_limit_is_respected(self, app, tmp_path):
        log = self._write_log(tmp_path)
        events = WafService.events(application_id=1, log_path=log, limit=1)
        assert len(events) == 1

    def test_missing_log_returns_empty(self, app):
        assert WafService.events(application_id=1, log_path='/no/such/file.log') == []


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
class TestWafApi:
    def test_put_policy_round_trips(self, client, auth_headers, app, monkeypatch):
        a = _seed_app()
        # Don't touch nginx / the filesystem.
        monkeypatch.setattr(WafService, 'apply', lambda app_id: {'success': True})
        resp = client.put(
            f'/api/v1/waf/applications/{a.id}/policy',
            headers=auth_headers,
            json={'mode': 'block', 'paranoia_level': 2, 'disabled_rule_ids': ['942100']},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['mode'] == 'block'
        assert body['paranoia_level'] == 2
        assert body['disabled_rule_ids'] == ['942100']
        assert body['apply'] == {'success': True}

    def test_get_policy_returns_default(self, client, auth_headers, app):
        a = _seed_app()
        resp = client.get(
            f'/api/v1/waf/applications/{a.id}/policy', headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['mode'] == 'off'

    def test_put_invalid_mode_returns_400(self, client, auth_headers, app, monkeypatch):
        a = _seed_app()
        monkeypatch.setattr(WafService, 'apply', lambda app_id: {'success': True})
        resp = client.put(
            f'/api/v1/waf/applications/{a.id}/policy',
            headers=auth_headers,
            json={'mode': 'bogus'},
        )
        assert resp.status_code == 400

    def test_status_reports_installed(self, client, auth_headers, app, monkeypatch):
        monkeypatch.setattr(WafService, 'modsecurity_installed', classmethod(lambda cls: True))
        resp = client.get('/api/v1/waf/status', headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['installed'] is True

    def test_apply_endpoint(self, client, auth_headers, app, monkeypatch):
        a = _seed_app()
        monkeypatch.setattr(WafService, 'apply',
                            lambda app_id: {'success': True, 'wired': True})
        resp = client.post(
            f'/api/v1/waf/applications/{a.id}/apply', headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['wired'] is True

    def test_events_endpoint(self, client, auth_headers, app, monkeypatch):
        a = _seed_app()
        monkeypatch.setattr(WafService, 'events',
                            lambda application_id, limit=50: [{'rule_id': '942100'}])
        resp = client.get(
            f'/api/v1/waf/applications/{a.id}/events', headers=auth_headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['count'] == 1
        assert body['events'][0]['rule_id'] == '942100'

    def test_put_requires_auth(self, client, app):
        resp = client.put('/api/v1/waf/applications/1/policy', json={'mode': 'block'})
        assert resp.status_code == 401

    def test_status_requires_auth(self, client, app):
        assert client.get('/api/v1/waf/status').status_code == 401
