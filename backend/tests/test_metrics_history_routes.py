"""Compatibility tests for the local metrics-history routes."""

import pytest

from app.services.metrics_history_service import MetricsHistoryService


HISTORY_PATHS = (
    '/api/v1/metrics/history',
    '/api/v1/system/performance-history',
)
VALID_PERIODS = ('1h', '6h', '24h', '7d', '30d')


@pytest.mark.parametrize('period', VALID_PERIODS)
def test_history_routes_return_the_same_payload(
        client, viewer_headers, monkeypatch, period):
    calls = []
    payload = {
        'period': period,
        'points': 1,
        'data': [{'timestamp': '2026-09-03T12:00:00Z'}],
        'summary': {'cpu': {'average': 12.5}},
    }

    def fake_get_history(_cls, requested_period):
        calls.append(requested_period)
        return payload

    monkeypatch.setattr(
        MetricsHistoryService, 'get_history', classmethod(fake_get_history))

    old_response = client.get(
        f'{HISTORY_PATHS[0]}?period={period}', headers=viewer_headers)
    new_response = client.get(
        f'{HISTORY_PATHS[1]}?period={period}', headers=viewer_headers)

    assert old_response.status_code == 200
    assert new_response.status_code == 200
    assert old_response.get_json() == new_response.get_json() == payload
    assert calls == [period, period]


@pytest.mark.parametrize('path', HISTORY_PATHS)
def test_history_routes_require_authentication(client, path):
    response = client.get(f'{path}?period=1h')

    assert response.status_code == 401


@pytest.mark.parametrize('path', HISTORY_PATHS)
def test_history_routes_reject_invalid_periods(
        client, viewer_headers, monkeypatch, path):
    def fail_if_called(_cls, _period):
        raise AssertionError('invalid periods must not reach the service')

    monkeypatch.setattr(
        MetricsHistoryService, 'get_history', classmethod(fail_if_called))

    response = client.get(f'{path}?period=2h', headers=viewer_headers)

    assert response.status_code == 400
    assert response.get_json() == {
        'error': 'Invalid period. Must be one of: 1h, 6h, 24h, 7d, 30d'
    }
