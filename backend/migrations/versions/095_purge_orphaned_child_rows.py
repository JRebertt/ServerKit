"""Purge child rows orphaned by past parent hard-deletes.

Before the delete-cascade policy (app/models/_delete_cascade_policy.py) and
the parent-side relationships that feed it, hard-deleting a parent left its
NOT NULL-FK children behind: SQLite ships with FK enforcement off, so nothing
stopped the delete, and nothing cleaned up after it. Worse, SQLite may reuse a
deleted parent's id, so an orphaned row — an application's env-var SECRETS
being the ugly case — could silently attach to a future record.

This is the one-off sweep for installs that accumulated such orphans. Going
forward the ORM cascades (or an explicit guard on the parent's delete path)
keep these tables clean, so downgrade has nothing to restore.

Revision ID: 095_purge_orphaned_child_rows
Revises: 094_connection_provider_health
Create Date: 2026-08-31
"""

import sqlalchemy as sa
from alembic import op

revision = '095_purge_orphaned_child_rows'
down_revision = '094_connection_provider_health'
branch_labels = None
depends_on = None

# (child_table, fk_column, parent_table) — the 26 audited relationship-less
# NOT NULL FKs, plus the Application children the first cascade fix covered
# (their orphans from purges before that fix are just as stale).
ORPHAN_SWEEP = [
    ('agent_rollouts', 'version_id', 'agent_versions'),
    ('ai_conversations', 'user_id', 'users'),
    ('ai_pending_actions', 'user_id', 'users'),
    ('api_keys', 'user_id', 'users'),
    ('application_manifests', 'project_id', 'projects'),
    ('application_preview_settings', 'application_id', 'applications'),
    ('application_previews', 'application_id', 'applications'),
    ('container_scale_policies', 'application_id', 'applications'),
    ('container_sleep_policies', 'application_id', 'applications'),
    ('dashboard_boards', 'user_id', 'users'),
    ('ddns_hosts', 'zone_id', 'dns_zones'),
    ('deployments', 'app_id', 'applications'),
    ('environment_variable_history', 'application_id', 'applications'),
    ('environment_variables', 'application_id', 'applications'),
    ('event_subscriptions', 'user_id', 'users'),
    ('exposed_services', 'tunnel_id', 'tunnels'),
    ('fleet_doctor_results', 'server_id', 'servers'),
    ('invitations', 'invited_by', 'users'),
    ('login_links', 'user_id', 'users'),
    ('projects', 'workspace_id', 'workspaces'),
    ('proxy_stacks', 'server_id', 'servers'),
    ('queue_messages', 'group_id', 'queue_groups'),
    ('resource_grants', 'user_id', 'users'),
    ('restore_drills', 'policy_id', 'backup_policies'),
    ('server_surveys', 'server_id', 'servers'),
    ('tunnels', 'edge_server_id', 'servers'),
    ('tunnels', 'private_server_id', 'servers'),
    ('waf_policies', 'application_id', 'applications'),
    ('wordpress_site_plugins', 'wordpress_site_id', 'wordpress_sites'),
]


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for child, fk, parent in ORPHAN_SWEEP:
        if child not in existing or parent not in existing:
            continue
        bind.execute(sa.text(
            f'DELETE FROM {child} '                       # noqa: S608 — names
            f'WHERE {fk} IS NOT NULL '                    # come from the fixed
            f'AND {fk} NOT IN (SELECT id FROM {parent})'  # list above
        ))


def downgrade():
    # The deleted rows were orphans — there is nothing meaningful to restore.
    pass
