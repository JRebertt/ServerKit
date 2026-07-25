"""Retrying an install that failed part-way.

A template install writes its directory before it starts containers, so a
failure at "Start Docker Compose stack" leaves the directory behind. The guard
against clobbering an existing app then refused the retry — "App directory
already exists" — and the only way forward was a shell. That is a dead end in
the one flow where a user is most likely to try again.

A directory with no Application row pointing at it was left by a failure: the
row is written only after the plan completes. Those can be reused. Anything
else is somebody's data and is still refused.
"""

import os

import pytest

from app import db
from app.models.application import Application
from app.services.deployment_job_service import DeploymentJobService


@pytest.fixture
def app_dir(tmp_path):
    path = tmp_path / 'uptime-kuma'
    path.mkdir()
    return str(path)


class TestAbandonedDirectoryDetection:
    def test_a_failed_installs_leftovers_are_reusable(self, app, app_dir):
        # What the deploy wrote before it failed.
        open(os.path.join(app_dir, 'docker-compose.yml'), 'w').close()
        open(os.path.join(app_dir, '.serverkit-template.json'), 'w').close()

        assert DeploymentJobService._is_abandoned_install_dir(app_dir) is True

    def test_an_empty_directory_is_reusable(self, app, app_dir):
        assert DeploymentJobService._is_abandoned_install_dir(app_dir) is True

    def test_a_directory_owned_by_an_app_is_not(self, app, app_dir):
        # A finished install: the Application row is written once the plan has
        # run, so its presence means this is a live app, not wreckage.
        open(os.path.join(app_dir, '.serverkit-template.json'), 'w').close()
        db.session.add(Application(name='uptime-kuma', app_type='docker',
                                   status='running', root_path=app_dir, user_id=1))
        db.session.commit()

        assert DeploymentJobService._is_abandoned_install_dir(app_dir) is False

    def test_someone_elses_files_are_never_reused(self, app, app_dir):
        # No marker and not empty — could be anything. Refuse rather than
        # overwrite it.
        open(os.path.join(app_dir, 'important.db'), 'w').close()

        assert DeploymentJobService._is_abandoned_install_dir(app_dir) is False

    def test_an_unreadable_directory_counts_as_occupied(self, app, monkeypatch):
        def _boom(_path):
            raise PermissionError('nope')

        monkeypatch.setattr(os, 'listdir', _boom)
        assert DeploymentJobService._is_abandoned_install_dir('/root/secret') is False


class TestInstallGuard:
    def _install(self, monkeypatch, app_path, template_id='actualbudget'):
        """Drive install_template far enough to hit the directory guard."""
        monkeypatch.setattr(
            'app.services.template_service.TemplateService.build_install_plan',
            classmethod(lambda cls, **kwargs: {
                'success': True, 'app_path': app_path,
                'plan': {'steps': [], 'app_name': kwargs.get('app_name')},
            }))
        # Stop before anything is queued; the guard is what is under test.
        monkeypatch.setattr(DeploymentJobService, '_enqueue_install',
                            classmethod(lambda cls, job: None))
        return DeploymentJobService.install_template(
            template_id=template_id, app_name='uptime-kuma', user_id=1)

    def test_retry_after_a_failed_install_is_allowed(self, app, app_dir, monkeypatch):
        open(os.path.join(app_dir, '.serverkit-template.json'), 'w').close()

        result = self._install(monkeypatch, app_dir)

        assert result['success'] is True, result.get('error')

    def test_a_real_directory_conflict_still_refuses_and_says_what_to_do(
            self, app, app_dir, monkeypatch):
        open(os.path.join(app_dir, 'important.db'), 'w').close()

        result = self._install(monkeypatch, app_dir)

        assert result['success'] is False
        assert 'already exists' in result['error']
        # The old message was a dead end; this one names a way forward.
        assert 'different name' in result['error']

    def test_the_name_collision_guard_is_untouched(self, app, app_dir, monkeypatch):
        db.session.add(Application(name='uptime-kuma', app_type='docker',
                                   status='running', root_path='/elsewhere', user_id=1))
        db.session.commit()

        result = self._install(monkeypatch, app_dir)

        assert result['success'] is False
        assert 'already exists on this target server' in result['error']
