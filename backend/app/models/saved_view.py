from datetime import datetime
from app import db


class SavedView(db.Model):
    """A user's saved table view for a list page (Services, Domains, …).

    Captures the page's table state — filter, search, sort levels, hidden
    columns, page size — as JSON so the frontend can re-apply it verbatim.
    Built-in views ship in the frontend; only user-created views live here.
    At most one view per (user, page) is the default, enforced by the service.
    """

    __tablename__ = 'saved_views'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    page = db.Column(db.String(80), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    state = db.Column(db.JSON, nullable=False, default=dict)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'page', 'name', name='uq_saved_views_user_page_name'),
    )

    user = db.relationship('User', backref=db.backref('saved_views', cascade='all, delete-orphan'))

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'page': self.page,
            'name': self.name,
            'state': self.state or {},
            'is_default': self.is_default,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<SavedView {self.page}/{self.name} user={self.user_id}>'
