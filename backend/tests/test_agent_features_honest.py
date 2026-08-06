"""
Regression tests for audit H2: the Agent Plugin and Server Template features
used to dispatch to a non-existent `get_agent_gateway()` (ImportError, swallowed)
and leave DB rows stuck in an in-progress state forever. The agent implements
none of these commands. These tests assert the operations now report honestly
instead of silently pretending to work.
"""
from app import db
from app.models.server import Server
from app.models.agent_plugin import AgentPlugin, AgentPluginInstall
from app.models.server_template import ServerTemplate, ServerTemplateAssignment
from app.services.agent_plugin_service import AgentPluginService
from app.services.server_template_service import ServerTemplateService

import pytest
# Installs plugins, and plugin_service hot-loads their blueprints onto the
# live app. Flask refuses register_blueprint once an app has served a
# request, so these need a private app (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app


def test_plugin_install_reports_unimplemented_not_stuck_installing(app):
    with app.app_context():
        plugin = AgentPluginService.create_plugin({
            "name": "demo-plugin",
            "display_name": "Demo Plugin",
            "version": "1.0.0",
        })
        server = Server(name="srv", agent_id="agent-h2-1")
        db.session.add(server)
        db.session.commit()

        install = AgentPluginService.install_plugin(plugin.id, server.id)

        # Honest failure, not a permanent 'installing' limbo.
        assert install.status == AgentPluginInstall.STATUS_ERROR
        assert install.status != AgentPluginInstall.STATUS_INSTALLING
        assert "not implemented" in (install.error_message or "").lower()


def test_template_drift_check_reports_unimplemented_not_stuck_checking(app):
    with app.app_context():
        tmpl = ServerTemplate(name="base-template", version="1.0.0")
        server = Server(name="srv2", agent_id="agent-h2-2")
        db.session.add_all([tmpl, server])
        db.session.commit()
        assignment = ServerTemplateAssignment(template_id=tmpl.id, server_id=server.id)
        db.session.add(assignment)
        db.session.commit()

        result = ServerTemplateService.check_drift(assignment.id)

        assert result.status == ServerTemplateAssignment.STATUS_UNKNOWN
        assert result.status != ServerTemplateAssignment.STATUS_CHECKING
        assert "not implemented" in (result.drift_report.get("error") or "").lower()


def test_template_remediate_reports_unimplemented(app):
    with app.app_context():
        tmpl = ServerTemplate(name="base-template-2", version="1.0.0")
        server = Server(name="srv3", agent_id="agent-h2-3")
        db.session.add_all([tmpl, server])
        db.session.commit()
        assignment = ServerTemplateAssignment(template_id=tmpl.id, server_id=server.id)
        db.session.add(assignment)
        db.session.commit()

        result = ServerTemplateService.remediate(assignment.id)

        assert result.status == ServerTemplateAssignment.STATUS_UNKNOWN
        assert "not implemented" in (result.drift_report.get("error") or "").lower()
