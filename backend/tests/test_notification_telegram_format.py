"""Telegram alerts are sent with parse_mode='HTML', so every interpolated
value has to be escaped.

Unescaped, an alert message as ordinary as "Disk usage > 90% on /var & /tmp"
makes the Bot API reject the request with "can't parse entities" and the whole
notification is dropped — precisely when something is already wrong on the box.
These pin the escaping and that the literal markup survives it.
"""

from unittest.mock import patch

from app.services.notification_service import NotificationService


TELEGRAM_CONFIG = {
    'enabled': True,
    'bot_token': 'test-token',
    'chat_id': '123456',
    'notify_on': ['critical', 'warning', 'info'],
}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _send(alerts, hostname='test-host'):
    """Run send_telegram against a stubbed API and return the posted payload."""
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured['url'] = url
        captured['payload'] = json
        return _FakeResponse({'ok': True})

    with patch('app.services.notification_service.requests.post', side_effect=fake_post), \
            patch.object(NotificationService, 'get_hostname', return_value=hostname):
        result = NotificationService.send_telegram(alerts, config=dict(TELEGRAM_CONFIG))

    assert result['success'] is True, result
    return captured['payload']


def test_alert_message_with_html_metacharacters_is_escaped():
    """The regression: > and & in a message used to reach Telegram raw."""
    payload = _send([{
        'severity': 'warning',
        'type': 'disk',
        'message': 'Disk usage > 90% on /var & /tmp',
    }])

    text = payload['text']
    assert 'Disk usage &gt; 90% on /var &amp; /tmp' in text
    # The raw form must be gone, or the API rejects the whole message.
    assert 'Disk usage > 90%' not in text


def test_angle_bracket_payload_cannot_inject_markup():
    """A value that looks like a tag is data, not markup."""
    payload = _send([{
        'severity': 'critical',
        'type': 'service',
        'message': 'container <b>web</b> exited',
    }])

    text = payload['text']
    assert '&lt;b&gt;web&lt;/b&gt;' in text
    assert '<b>web</b>' not in text


def test_hostname_and_threshold_values_are_escaped():
    """Every interpolated field, not just the message."""
    payload = _send(
        [{
            'severity': 'warning',
            'type': 'cpu',
            'message': 'high load',
            'value': '95% > limit',
            'threshold': '90% & rising',
        }],
        hostname='box<1>&2',
    )

    text = payload['text']
    assert 'box&lt;1&gt;&amp;2' in text
    assert 'Current: 95% &gt; limit' in text
    assert 'Threshold: 90% &amp; rising' in text


def test_literal_markup_and_parse_mode_survive_escaping():
    """Escaping data must not escape the template's own tags."""
    payload = _send([{
        'severity': 'info',
        'type': 'test',
        'message': 'plain message',
    }])

    text = payload['text']
    assert payload['parse_mode'] == 'HTML'
    assert '<b>🔔 ServerKit Alert</b>' in text
    assert '<i>Host: test-host</i>' in text
    assert '<b>INFO: TEST</b>' in text
