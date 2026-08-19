"""Per-user dashboard boards (plan 62).

A *board* is one tab on the dashboard — a name, an icon, and an ordered bag of
widget instances laid out on a 12-column grid. Boards belong to a user, not to
the panel: two operators looking at the same server keep their own tabs, their
own widget placement and their own per-widget config.

The shipped defaults ('overview', 'infra', 'apps') are seeded as real rows the
first time a user reads their boards, so a user can drag, resize and delete them
like anything else. ``slug`` remembers which shipped default a row came from,
which is what makes ``POST /<id>/reset`` able to restore it; user-created boards
leave it NULL.

``widgets`` is a native JSON column (the dominant pattern in this codebase, and
dialect-agnostic across SQLite and PostgreSQL) holding the widget-instance list
``[{i, type, x, y, w, h, cfg}, …]``. The panel does not interpret ``cfg`` — that
is the widget renderer's business — but the API layer does validate the shape of
the geometry fields before storing anything.
"""

from datetime import datetime

from app import db
from app.models.mixins import TimestampMixin


class DashboardBoard(TimestampMixin, db.Model):
    """One dashboard tab belonging to one user."""

    __tablename__ = 'dashboard_boards'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    # The shipped-default id this board came from ('overview' / 'infra' /
    # 'apps'). NULL for boards the user created themselves — those have no
    # default to reset to.
    slug = db.Column(db.String(64), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    icon = db.Column(db.String(64), nullable=True, default='grid')
    position = db.Column(db.Integer, nullable=False, default=0)
    widgets = db.Column(db.JSON, nullable=False, default=list)


    def to_dict(self):
        return {
            'id': self.id,
            'slug': self.slug,
            'name': self.name,
            'icon': self.icon or 'grid',
            'position': self.position if self.position is not None else 0,
            'widgets': self.widgets or [],
        }

    def __repr__(self):
        return f'<DashboardBoard {self.id} u{self.user_id} {self.name!r}>'
