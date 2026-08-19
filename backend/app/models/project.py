from datetime import datetime
from app import db
from app.models.mixins import TimestampMixin
import json


class Project(TimestampMixin, db.Model):
    """A Project groups applications under a Workspace.

    Hierarchy: Workspace -> Project -> Environment -> Applications.

    OPT-IN and backward compatible: applications carry a nullable project_id, so
    existing apps remain "unassigned" until a user organizes them into projects.
    """
    __tablename__ = 'projects'

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    slug = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)


    # Environments belonging to this project. Deleting a project cascades to its
    # environments (apps are detached/blocked separately by the service layer).
    environments = db.relationship(
        'Environment',
        backref='project',
        lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='Environment.order',
    )

    __table_args__ = (
        db.UniqueConstraint('workspace_id', 'slug', name='uq_project_workspace_slug'),
    )

    @property
    def metadata_(self):
        return json.loads(self.metadata_json) if self.metadata_json else {}

    @metadata_.setter
    def metadata_(self, v):
        self.metadata_json = json.dumps(v) if v else None

    def to_dict(self, include_counts=False):
        result = {
            'id': self.id,
            'workspace_id': self.workspace_id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description,
            'metadata': self.metadata_,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_counts:
            from app.models.application import Application
            result['environment_count'] = self.environments.count()
            # Live apps only — a project claiming 5 while showing 3 is just wrong.
            result['app_count'] = Application.query_active().filter_by(project_id=self.id).count()
        return result

    def __repr__(self):
        return f'<Project {self.name}>'
