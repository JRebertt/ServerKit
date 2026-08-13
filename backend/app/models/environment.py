from datetime import datetime
from app import db


class Environment(db.Model):
    """An Environment (production/staging/development) under a Project.

    Applications carry a nullable environment_id. A project always has at least
    one default environment ("production") created alongside it.
    """
    __tablename__ = 'environments'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)
    slug = db.Column(db.String(64), nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    order = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('project_id', 'slug', name='uq_environment_project_slug'),
    )

    def to_dict(self, include_counts=False):
        result = {
            'id': self.id,
            'project_id': self.project_id,
            'name': self.name,
            'slug': self.slug,
            'is_default': self.is_default,
            'order': self.order,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_counts:
            from app.models.application import Application
            # Live apps only — see Project.to_dict.
            result['app_count'] = Application.query_active().filter_by(environment_id=self.id).count()
        return result

    def __repr__(self):
        return f'<Environment {self.name} (project={self.project_id})>'
