import logging

from app import db
from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.saved_view import SavedView
from app.utils.slug import slugify as _slugify, unique_slug

logger = logging.getLogger(__name__)

MAX_VIEWS_PER_PAGE = 50


def slugify(value):
    """URL handle for a view name: 'SSL expiring ≤ 30d' -> 'ssl-expiring-30d'.

    The regex lives in ``app.utils.slug``; the 140-char cap is this caller's
    own rule (the column width) and stays here.
    """
    return _slugify(value)[:140] or 'view'


def _unique_slug(user_id, page, name, exclude_id=None):
    """A slug unique among that user's LIVE views on the page.

    Scoped to live rows only: a tombstoned view must not reserve its handle
    forever, or deleting a view would burn the link name with it.
    """
    def taken(candidate):
        q = (SavedView.query_active()
             .filter_by(user_id=user_id, page=page, slug=candidate))
        if exclude_id is not None:
            q = q.filter(SavedView.id != exclude_id)
        return q.first() is not None

    # start=2 keeps the handles this service has always generated.
    return unique_slug(slugify(name), taken, default='view', start=2)


def get_by_slug(user_id, page, slug):
    """Resolve ?view=<slug> back to a saved view."""
    view = (SavedView.query_active()
            .filter_by(user_id=user_id, page=page, slug=slug)
            .first())
    return view.to_dict() if view else None


def list_views(user_id, page):
    """All saved views a user has for one list page, defaults first."""
    views = (SavedView.query_active()
             .filter_by(user_id=user_id, page=page)
             .order_by(SavedView.is_default.desc(), SavedView.name.asc())
             .all())
    return [v.to_dict() for v in views]


def _validate(page, name, state):
    if not page or not isinstance(page, str) or len(page) > 80:
        raise ValidationError('A view needs a page key (max 80 chars)')
    if not name or not isinstance(name, str) or not name.strip():
        raise ValidationError('A view needs a name')
    if len(name) > 120:
        raise ValidationError('View names are limited to 120 characters')
    if not isinstance(state, dict):
        raise ValidationError('View state must be an object')


def _clear_default(user_id, page):
    (SavedView.query_active()
     .filter_by(user_id=user_id, page=page, is_default=True)
     .update({'is_default': False}, synchronize_session=False))


def create_view(user_id, page, name, state, is_default=False):
    """Create a saved view and return its dict; raises typed errors."""
    _validate(page, name, state)
    name = name.strip()
    if SavedView.query_active().filter_by(user_id=user_id, page=page).count() >= MAX_VIEWS_PER_PAGE:
        raise ValidationError(f'You can save at most {MAX_VIEWS_PER_PAGE} views per page')
    if SavedView.query_active().filter_by(user_id=user_id, page=page, name=name).first():
        raise ConflictError(f'You already have a "{name}" view on this page')
    if is_default:
        _clear_default(user_id, page)
    view = SavedView(user_id=user_id, page=page, name=name, state=state,
                     slug=_unique_slug(user_id, page, name),
                     is_default=bool(is_default))
    db.session.add(view)
    db.session.commit()
    return view.to_dict()


def update_view(user_id, view_id, data):
    """Rename / restate / (un)default a saved view; raises typed errors."""
    view = SavedView.query_active().filter_by(id=view_id, user_id=user_id).first()
    if not view:
        raise NotFoundError('View not found')

    if 'name' in data:
        _validate(view.page, data['name'], view.state or {})
        name = data['name'].strip()
        clash = (SavedView.query_active()
                 .filter_by(user_id=user_id, page=view.page, name=name)
                 .filter(SavedView.id != view.id)
                 .first())
        if clash:
            raise ConflictError(f'You already have a "{name}" view on this page')
        view.name = name
        view.slug = _unique_slug(user_id, view.page, name, exclude_id=view.id)

    if 'state' in data:
        if not isinstance(data['state'], dict):
            raise ValidationError('View state must be an object')
        view.state = data['state']

    if 'is_default' in data:
        if data['is_default']:
            _clear_default(user_id, view.page)
        view.is_default = bool(data['is_default'])

    db.session.commit()
    return view.to_dict()


def delete_view(user_id, view_id):
    """Send a saved view to the Recycle Bin; raises NotFoundError if absent.

    Soft, not destructive: a view is a piece of work someone tuned, and the
    only way to get it back used to be rebuilding it from memory.
    """
    view = SavedView.query_active().filter_by(id=view_id, user_id=user_id).first()
    if not view:
        raise NotFoundError('View not found')
    view.soft_delete(user_id=user_id)
    db.session.commit()
