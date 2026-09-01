from datetime import datetime
from app import db
from app.models.mixins import SoftDeleteMixin, TimestampMixin


class SavedView(TimestampMixin, SoftDeleteMixin, db.Model):
    """A user's saved table view for a list page (Services, Domains, …).

    Captures the page's table state — filter, search, sort levels, hidden
    columns, page size — as JSON so the frontend can re-apply it verbatim.
    Built-in views ship in the frontend; only user-created views live here.
    At most one view per (user, page) is the default, enforced by the service.
    """

    __tablename__ = 'saved_views'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    page = db.Column(db.String(80), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    # URL-safe handle so a view can be linked: /domains?view=ssl-expiring-soon.
    # Unique per (user, page) among LIVE rows; derived from the name on create.
    slug = db.Column(db.String(140), nullable=True, index=True)
    state = db.Column(db.JSON, nullable=False, default=dict)
    is_default = db.Column(db.Boolean, nullable=False, default=False)

    # No table-level UNIQUE on (user_id, page, name): a deleted view keeps its
    # row, and the constraint would then refuse to let you re-create a view by
    # the same name. Migration 083 makes it a PARTIAL unique index restricted to
    # rows where deleted_at IS NULL.
    __table_args__ = ()

    user = db.relationship('User', backref=db.backref('saved_views', cascade='all, delete-orphan'))

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'page': self.page,
            'name': self.name,
            'slug': self.slug,
            'state': self.state or {},
            **self.soft_delete_dict(),
            'is_default': self.is_default,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<SavedView {self.page}/{self.name} user={self.user_id}>'
