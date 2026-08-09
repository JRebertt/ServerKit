import logging

from app import db
from app.models.saved_view import SavedView

logger = logging.getLogger(__name__)

MAX_VIEWS_PER_PAGE = 50


def list_views(user_id, page):
    """All saved views a user has for one list page, defaults first."""
    views = (SavedView.query
             .filter_by(user_id=user_id, page=page)
             .order_by(SavedView.is_default.desc(), SavedView.name.asc())
             .all())
    return [v.to_dict() for v in views]


def _validate(page, name, state):
    if not page or not isinstance(page, str) or len(page) > 80:
        return 'A view needs a page key (max 80 chars)'
    if not name or not isinstance(name, str) or not name.strip():
        return 'A view needs a name'
    if len(name) > 120:
        return 'View names are limited to 120 characters'
    if not isinstance(state, dict):
        return 'View state must be an object'
    return None


def _clear_default(user_id, page):
    (SavedView.query
     .filter_by(user_id=user_id, page=page, is_default=True)
     .update({'is_default': False}))


def create_view(user_id, page, name, state, is_default=False):
    """Create a saved view. Returns ``(view_dict, error)``."""
    err = _validate(page, name, state)
    if err:
        return None, err
    name = name.strip()
    if SavedView.query.filter_by(user_id=user_id, page=page).count() >= MAX_VIEWS_PER_PAGE:
        return None, f'You can save at most {MAX_VIEWS_PER_PAGE} views per page'
    if SavedView.query.filter_by(user_id=user_id, page=page, name=name).first():
        return None, f'You already have a "{name}" view on this page'
    if is_default:
        _clear_default(user_id, page)
    view = SavedView(user_id=user_id, page=page, name=name, state=state, is_default=bool(is_default))
    db.session.add(view)
    db.session.commit()
    return view.to_dict(), None


def update_view(user_id, view_id, data):
    """Rename / restate / (un)default a saved view. Returns ``(view_dict, error)``."""
    view = SavedView.query.filter_by(id=view_id, user_id=user_id).first()
    if not view:
        return None, 'View not found'

    if 'name' in data:
        err = _validate(view.page, data['name'], view.state or {})
        if err:
            return None, err
        name = data['name'].strip()
        clash = (SavedView.query
                 .filter_by(user_id=user_id, page=view.page, name=name)
                 .filter(SavedView.id != view.id)
                 .first())
        if clash:
            return None, f'You already have a "{name}" view on this page'
        view.name = name

    if 'state' in data:
        if not isinstance(data['state'], dict):
            return None, 'View state must be an object'
        view.state = data['state']

    if 'is_default' in data:
        if data['is_default']:
            _clear_default(user_id, view.page)
        view.is_default = bool(data['is_default'])

    db.session.commit()
    return view.to_dict(), None


def delete_view(user_id, view_id):
    """Delete a saved view. Returns ``(True, error)``."""
    view = SavedView.query.filter_by(id=view_id, user_id=user_id).first()
    if not view:
        return None, 'View not found'
    db.session.delete(view)
    db.session.commit()
    return True, None
