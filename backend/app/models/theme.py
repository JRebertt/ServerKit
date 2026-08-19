"""Theme model (plan 60).

A theme is DATA, not code: a validated map of CSS custom-property tokens plus
gallery metadata. Installed themes (imported, studio-authored, or pulled from
the registry) live here; the always-present bundled seed themes ship as JSON
under ``app/data/themes/`` and are merged in by ``theme_service`` — they are not
rows unless an admin explicitly imports one.

No zips, no sha256, no permissions: reviewing a theme is reading a diff of color
values, so themes deliberately bypass the whole extension trust machinery.
"""
from datetime import datetime

from app import db
from app.models.mixins import TimestampMixin


class Theme(TimestampMixin, db.Model):
    __tablename__ = 'themes'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(64), nullable=False, unique=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    author = db.Column(db.String(120), nullable=True, default='')
    version = db.Column(db.String(32), nullable=True, default='1.0.0')
    description = db.Column(db.Text, nullable=True, default='')
    # 'dark' | 'light' — which mode this theme is primarily a skin of.
    base = db.Column(db.String(8), nullable=False, default='dark')
    # { "dark": {token: value, …}, "light": {…} } — already sanitised.
    tokens = db.Column(db.JSON, nullable=False, default=dict)
    # Optional single accent hex; ThemeContext derives the ramp.
    accent = db.Column(db.String(32), nullable=True)
    # 4 gallery swatches.
    preview = db.Column(db.JSON, nullable=True, default=list)
    # Where it came from: 'registry' | 'import' | 'studio' | 'bundled'.
    source = db.Column(db.String(16), nullable=False, default='import')

    def to_dict(self):
        return {
            'schema_version': 1,
            'slug': self.slug,
            'name': self.name,
            'author': self.author or '',
            'version': self.version or '1.0.0',
            'description': self.description or '',
            'base': self.base or 'dark',
            'tokens': self.tokens or {},
            'accent': self.accent,
            'preview': self.preview or [],
            'source': self.source,
            'builtin': False,
            'installed': True,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
