"""Business logic for the Project / Environment hierarchy.

Hierarchy: Workspace -> Project -> Environment -> Applications.

The model is OPT-IN: applications carry nullable project_id/environment_id, so
existing apps remain unassigned and keep working. ProjectService centralizes the
CRUD plus the invariant that every project has at least one default environment.
"""
from datetime import datetime

from app import db
from app.models.project import Project
from app.models.environment import Environment
from app.models.application import Application
from app.utils.slug import unique_slug, slugify


# Canonical environment names a project starts with / can add. Free-form names
# are allowed too; these are just the well-known ones the UI nudges toward.
KNOWN_ENVIRONMENTS = ('production', 'staging', 'development')
DEFAULT_PROJECT_NAME = 'Default'
DEFAULT_ENVIRONMENT_NAME = 'production'


class ProjectService:
    """Static-method service for projects and their environments."""

    # ------------------------------------------------------------------ #
    # Projects
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_projects(workspace_id):
        """All projects in a workspace, newest first."""
        return (Project.query
                .filter_by(workspace_id=workspace_id)
                .order_by(Project.created_at.desc())
                .all())

    @staticmethod
    def get_project(project_id):
        return Project.query.get(project_id)

    @staticmethod
    def _unique_project_slug(workspace_id, name):
        return unique_slug(
            name,
            lambda s: Project.query.filter_by(workspace_id=workspace_id, slug=s).first() is not None,
            default='project',
        )

    @staticmethod
    def create_project(workspace_id, name, description=None, metadata=None,
                       default_environment=DEFAULT_ENVIRONMENT_NAME):
        """Create a project and auto-create its default environment.

        Returns the new Project. Raises ValueError on a blank name.
        """
        name = (name or '').strip()
        if not name:
            raise ValueError('Project name is required')

        slug = ProjectService._unique_project_slug(workspace_id, name)
        project = Project(
            workspace_id=workspace_id,
            name=name,
            slug=slug,
            description=(description or None),
        )
        if metadata:
            project.metadata_ = metadata
        db.session.add(project)
        db.session.flush()  # assign project.id before creating the environment

        ProjectService.create_environment(
            project.id,
            name=default_environment or DEFAULT_ENVIRONMENT_NAME,
            is_default=True,
        )
        db.session.commit()
        return project

    @staticmethod
    def update_project(project_id, name=None, description=None, metadata=None):
        project = Project.query.get(project_id)
        if not project:
            return None
        if name is not None and name.strip():
            project.name = name.strip()
        if description is not None:
            project.description = description or None
        if metadata is not None:
            project.metadata_ = metadata
        project.updated_at = datetime.utcnow()
        db.session.commit()
        return project

    @staticmethod
    def delete_project(project_id):
        """Delete a project. Returns True on success, or the string 'has_apps' if
        the project still has applications assigned (caller should 409)."""
        project = Project.query.get(project_id)
        if not project:
            return None
        # Deliberately counts tombstones too: a soft-deleted app still points at
        # this project, and hard-deleting the project would leave it unrestorable.
        if Application.query.filter_by(project_id=project_id).count() > 0:
            return 'has_apps'
        db.session.delete(project)  # cascades to environments
        db.session.commit()
        return True

    @staticmethod
    def ensure_default(workspace_id):
        """Find-or-create the workspace's Default project (with a default
        environment). Idempotent — safe to call repeatedly."""
        existing = Project.query.filter_by(
            workspace_id=workspace_id, slug=slugify(DEFAULT_PROJECT_NAME)
        ).first()
        if existing:
            # Guarantee it still has at least one environment (self-heal).
            if existing.environments.count() == 0:
                ProjectService.create_environment(
                    existing.id, name=DEFAULT_ENVIRONMENT_NAME, is_default=True)
                db.session.commit()
            return existing
        return ProjectService.create_project(
            workspace_id,
            name=DEFAULT_PROJECT_NAME,
            description='Default project (auto-created).',
        )

    # ------------------------------------------------------------------ #
    # Environments
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_environments(project_id):
        return (Environment.query
                .filter_by(project_id=project_id)
                .order_by(Environment.order, Environment.id)
                .all())

    @staticmethod
    def get_environment(environment_id):
        return Environment.query.get(environment_id)

    @staticmethod
    def _unique_environment_slug(project_id, name):
        return unique_slug(
            name,
            lambda s: Environment.query.filter_by(project_id=project_id, slug=s).first() is not None,
            default='environment',
        )

    @staticmethod
    def create_environment(project_id, name, is_default=False, order=None):
        """Create an environment under a project. Does NOT commit unless the
        project was just created via create_project; callers that need a commit
        (the API) should commit themselves — but create_environment flushes so the
        id is available immediately."""
        name = (name or '').strip()
        if not name:
            raise ValueError('Environment name is required')

        slug = ProjectService._unique_environment_slug(project_id, name)
        if order is None:
            current_max = (db.session.query(db.func.max(Environment.order))
                           .filter_by(project_id=project_id).scalar())
            order = (current_max + 1) if current_max is not None else 0

        env = Environment(
            project_id=project_id,
            name=name,
            slug=slug,
            is_default=bool(is_default),
            order=order,
        )
        db.session.add(env)
        db.session.flush()
        return env

    @staticmethod
    def update_environment(environment_id, name=None, is_default=None):
        env = Environment.query.get(environment_id)
        if not env:
            return None
        if name is not None and name.strip():
            env.name = name.strip()
        if is_default is not None:
            env.is_default = bool(is_default)
        db.session.commit()
        return env

    @staticmethod
    def delete_environment(environment_id):
        """Delete an environment. Refuses to delete the last/only environment of a
        project (returns 'last'), and detaches any apps assigned to it (sets their
        environment_id to NULL) so apps are never orphaned. Returns True on
        success, 'last' if it's the only one, None if not found."""
        env = Environment.query.get(environment_id)
        if not env:
            return None
        sibling_count = Environment.query.filter_by(project_id=env.project_id).count()
        if sibling_count <= 1:
            return 'last'

        # Detach apps from the deleted environment (keep them in the project).
        # Tombstones included on purpose — the Environment row is going away, so
        # leaving a soft-deleted app pointing at it would dangle on restore.
        Application.query.filter_by(environment_id=environment_id).update(
            {'environment_id': None}, synchronize_session=False)
        was_default = env.is_default
        db.session.delete(env)
        db.session.flush()

        # If we removed the default env, promote the first remaining one.
        if was_default:
            replacement = (Environment.query
                           .filter_by(project_id=env.project_id)
                           .order_by(Environment.order, Environment.id)
                           .first())
            if replacement:
                replacement.is_default = True
        db.session.commit()
        return True

    @staticmethod
    def reorder_environments(project_id, ordered_ids):
        """Apply a new ordering to a project's environments. ordered_ids is the
        list of environment ids in the desired order. Ids not belonging to the
        project are ignored. Returns the reordered list."""
        envs = {e.id: e for e in Environment.query.filter_by(project_id=project_id).all()}
        position = 0
        for eid in ordered_ids:
            env = envs.get(eid)
            if env is not None:
                env.order = position
                position += 1
        # Any environments not named in ordered_ids keep a stable tail order.
        for env in sorted(envs.values(), key=lambda e: (e.order, e.id)):
            if env.id not in set(ordered_ids):
                env.order = position
                position += 1
        db.session.commit()
        return ProjectService.list_environments(project_id)

    # ------------------------------------------------------------------ #
    # App membership helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_project_apps(project_id):
        return Application.query_active().filter_by(project_id=project_id).all()

    @staticmethod
    def list_environment_apps(environment_id):
        return Application.query_active().filter_by(environment_id=environment_id).all()

    @staticmethod
    def count_project_apps(project_id):
        return Application.query_active().filter_by(project_id=project_id).count()
