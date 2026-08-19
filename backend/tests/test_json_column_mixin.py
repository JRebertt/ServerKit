"""The JsonColumnMixin contract (plan 75 §F2).

The mixin exists so the next fix to JSON-column handling lands in ONE place
instead of twenty. These tests pin the semantics every converted model now
shares: empty is the default, corrupt is the default (never a 500 on a
hand-edited row), wrong-shape JSON is the default when a shape is declared,
and falsy-on-write stores the column's empty form.
"""

from app.models.json_column_mixin import JsonColumnMixin


class _Row(JsonColumnMixin):
    def __init__(self, **cols):
        for key, value in cols.items():
            setattr(self, key, value)


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #

def test_valid_json_round_trips():
    row = _Row(details='{"a": 1}')
    assert row._json_read('details') == {'a': 1}


def test_default_is_a_fresh_dict_each_call():
    row = _Row(details=None)
    first, second = row._json_read('details'), row._json_read('details')
    assert first == second == {}
    assert first is not second  # no shared mutable default


def test_explicit_default_is_used():
    row = _Row(events=None)
    assert row._json_read('events', []) == []


def test_none_is_a_legitimate_default():
    row = _Row(repair_ref=None)
    assert row._json_read('repair_ref', None) is None


def test_corrupt_json_reads_as_the_default_never_raises():
    """A hand-edited row must not 500 every endpoint that serializes it."""
    row = _Row(details='{"a": 1')  # truncated
    assert row._json_read('details') == {}


def test_wrong_shape_reads_as_the_default_when_expect_is_set():
    row = _Row(creds='["not", "a", "mapping"]')
    assert row._json_read('creds', expect=dict) == {}
    row2 = _Row(creds='{"ok": true}')
    assert row2._json_read('creds', expect=dict) == {'ok': True}


def test_expect_none_imposes_no_shape_check():
    row = _Row(data='[1, 2]')
    assert row._json_read('data') == [1, 2]


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #

def test_write_serializes_truthy_values():
    row = _Row(details=None)
    row._json_write('details', {'a': 1})
    assert row.details == '{"a": 1}'


def test_falsy_writes_null_by_default():
    row = _Row(details='{"a": 1}')
    row._json_write('details', {})
    assert row.details is None


def test_falsy_writes_the_columns_empty_form_when_declared():
    row = _Row(events=None)
    row._json_write('events', [], falsy='[]')
    assert row.events == '[]'


# --------------------------------------------------------------------------- #
# The models actually opted in
# --------------------------------------------------------------------------- #

def test_converted_models_inherit_the_mixin():
    """A model converted back to a hand-rolled copy is the second door
    reopening — the plan's thesis. Pin the opt-in list."""
    from app.models.agent_plugin import AgentPlugin, AgentPluginInstall
    from app.models.ai import AiConversation, AiMessage, AiPendingAction
    from app.models.application import Application
    from app.models.audit_log import AuditLog
    from app.models.backup_run import BackupRun
    from app.models.cloud_server import CloudServer
    from app.models.db_snapshot import DatabaseSnapshot, SyncJob
    from app.models.deployment import DeploymentDiff
    from app.models.deployment_job import DeploymentJob, DeploymentJobLog
    from app.models.dns_zone import DNSZone
    from app.models.environment_activity import EnvironmentActivity
    from app.models.host_snapshot import HostSnapshot
    from app.models.image_scan import SbomArtifact
    from app.models.plugin import InstalledPlugin
    from app.models.project import Project
    from app.models.promotion_job import PromotionJob
    from app.models.registrar_connection import RegistrarConnection
    from app.models.server_onboarding_log import ServerOnboardingLog
    from app.models.server_survey import ServerSurvey
    from app.models.server_template import ServerTemplate, ServerTemplateAssignment
    from app.models.site_import import SiteImport
    from app.models.system_settings import SystemSettings
    from app.models.user import User
    from app.models.wordpress_site import (
        WordPressReport,
        WordPressSite,
        WordPressUpdateRun,
    )
    from app.models.workflow import Workflow, WorkflowExecution
    from app.models.workspace import Workspace, WorkspaceApiKey

    adopters = (
        AgentPlugin, AgentPluginInstall,
        AiConversation, AiMessage, AiPendingAction,
        Application,
        AuditLog,
        BackupRun,
        CloudServer,
        DatabaseSnapshot, SyncJob,
        DeploymentDiff,
        DeploymentJob, DeploymentJobLog,
        DNSZone,
        EnvironmentActivity,
        HostSnapshot,
        SbomArtifact,
        InstalledPlugin,
        Project,
        PromotionJob,
        RegistrarConnection,
        ServerOnboardingLog,
        ServerSurvey,
        ServerTemplate, ServerTemplateAssignment,
        SiteImport,
        SystemSettings,
        User,
        WordPressSite, WordPressUpdateRun, WordPressReport,
        Workflow, WorkflowExecution,
        Workspace, WorkspaceApiKey,
    )
    for model in adopters:
        assert issubclass(model, JsonColumnMixin), model.__name__


def test_a_converted_model_end_to_end(app):
    """Through the ORM, not just the mixin: corrupt column -> default."""
    from app import db
    from app.models.audit_log import AuditLog

    entry = AuditLog(action='test.json_mixin', details='not json{')
    db.session.add(entry)
    db.session.commit()

    assert entry.get_details() == {}
    entry.set_details({'k': 'v'})
    assert entry.details == '{"k": "v"}'
    assert entry.get_details() == {'k': 'v'}
