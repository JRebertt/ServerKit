"""Job-convergence tests for image CVE scans and Lynis audits."""

from unittest.mock import patch

import pytest

from app import db
from app.jobs.consumer import JobConsumer
from app.jobs.models import Job
from app.jobs.service import GROUP_SLUG, QUEUE_SLUG
from app.models import Application, ImageVulnerabilityScan, User
from app.queue_bus.service import QueueBusService
from app.services.image_scanner_service import (
    IMAGE_SCAN_JOB_KIND,
    ImageScannerService,
)
from app.services.security_service import LYNIS_SCAN_JOB_KIND, SecurityService


@pytest.fixture(autouse=True)
def isolated_jobs(app):
    QueueBusService.reset_broker()
    ImageScannerService.register_jobs()
    SecurityService.register_jobs()
    SecurityService._lynis_scan = None
    yield
    SecurityService._lynis_scan = None


@pytest.fixture
def image_app(app):
    owner = User(
        email='image-owner@test.local',
        username='image-owner',
        password_hash='unused',
        is_active=True,
    )
    db.session.add(owner)
    db.session.flush()
    application = Application(
        name='image-scan-app',
        app_type='docker',
        docker_image='registry.example.test/demo:latest',
        user_id=owner.id,
    )
    db.session.add(application)
    db.session.commit()
    return application


def _drain_once():
    messages = QueueBusService.receive(GROUP_SLUG, QUEUE_SLUG, max_messages=1)
    assert messages, 'expected one queued job'
    JobConsumer().process_message(messages[0])


def test_image_scan_keeps_legacy_fields_and_runs_as_a_job(image_app, monkeypatch):
    grype = {
        'descriptor': {'version': '1.2.3'},
        'matches': [{
            'vulnerability': {
                'id': 'CVE-TEST-1',
                'severity': 'High',
                'fix': {'versions': ['2.0']},
            },
            'artifact': {'name': 'demo', 'version': '1.0', 'type': 'deb'},
        }],
    }
    monkeypatch.setattr(
        ImageScannerService,
        '_run_grype',
        classmethod(lambda cls, image_ref: {'success': True, 'data': grype}),
    )

    response = ImageScannerService.scan_application(image_app.id)

    assert response['success'] is True
    assert response['status'] == 'running'
    assert response['scan_id']
    assert response['job_id']
    assert response['kind'] == IMAGE_SCAN_JOB_KIND
    job = db.session.get(Job, response['job_id'])
    assert job.owner_type == 'application'
    assert job.owner_id == str(image_app.id)
    assert job.get_payload()['scan_id'] == response['scan_id']

    _drain_once()

    job = db.session.get(Job, response['job_id'])
    scan = db.session.get(ImageVulnerabilityScan, response['scan_id'])
    assert job.status == Job.STATUS_SUCCEEDED
    assert job.get_result()['scan_id'] == scan.id
    assert scan.status == 'completed'
    assert scan.scanner_version == '1.2.3'
    assert scan.get_counts()['high'] == 1
    assert scan.get_findings()[0]['id'] == 'CVE-TEST-1'


def test_image_scan_api_preserves_200_and_adds_job_identity(
        client, auth_headers, image_app, monkeypatch):
    monkeypatch.setattr(
        ImageScannerService,
        '_run_grype',
        classmethod(lambda cls, image_ref: {'success': True, 'data': {'matches': []}}),
    )
    response = client.post(
        f'/api/v1/security/image-scans/applications/{image_app.id}',
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.get_json()
    assert {'scan_id', 'status', 'job_id', 'kind'} <= set(body)
    assert body['kind'] == IMAGE_SCAN_JOB_KIND


def test_lynis_scan_runs_as_a_job_and_status_remains_compatible(monkeypatch):
    monkeypatch.setattr(
        SecurityService,
        'get_lynis_status',
        classmethod(lambda cls: {'installed': True, 'version': '3.1'}),
    )

    class Completed:
        returncode = 0
        stderr = ''
        stdout = '\n'.join([
            'Warning: test warning',
            'Suggestion: test suggestion',
            'Hardening index : 72 [##############      ]',
        ])

    monkeypatch.setattr('app.services.security_service.subprocess.run',
                        lambda *args, **kwargs: Completed())

    response = SecurityService.run_lynis_scan()
    assert response['success'] is True
    assert response['status'] == 'running'
    assert response['job_id']
    assert response['kind'] == LYNIS_SCAN_JOB_KIND

    _drain_once()

    job = db.session.get(Job, response['job_id'])
    status = SecurityService.get_lynis_scan_status()
    assert job.status == Job.STATUS_SUCCEEDED
    assert status['status'] == 'completed'
    assert status['job_id'] == job.id
    assert status['job_status'] == Job.STATUS_SUCCEEDED
    assert status['hardening_index'] == 72
    assert status['warnings'] == ['Warning: test warning']
    assert status['suggestions'] == ['Suggestion: test suggestion']


def test_lynis_rejects_a_second_active_job(monkeypatch):
    monkeypatch.setattr(
        SecurityService,
        'get_lynis_status',
        classmethod(lambda cls: {'installed': True, 'version': '3.1'}),
    )
    first = SecurityService.run_lynis_scan()
    second = SecurityService.run_lynis_scan()
    assert first['success'] is True
    assert second == {'success': False, 'error': 'A scan is already in progress'}
