"""Dashboard board service (plan 62).

Owns the shipped default boards and the per-user CRUD around them. A board is a
dashboard tab; a widget instance is ``{i, type, x, y, w, h, cfg}`` placed on a
12-column grid.

Grid rules the defaults below obey (the frontend's ``grid/layout.js`` enforces
the same ones at runtime):

* 12 columns. ``x + w <= 12`` for every widget.
* No two widgets on a board overlap.
* Gravity-up: no widget can float higher without colliding, so there are no
  floating rows or holes above a widget.
* Every widget respects its type's minimum size from the widget registry.

``cfg`` is free-form per widget type and the backend never interprets it — it is
stored and handed back verbatim. The shapes used here mirror the widget table in
the plan contract:

* ``stat``       ``{metric, agg, resource, thresholds}``
* ``timeseries`` ``{metrics: [...], resource}``
* ``gauge``      ``{metric, resource, thresholds}``
* ``topn``       ``{metric, source, limit}``
* ``table``      ``{source: 'apps'|'servers'|'containers'|'deploys', limit}``
* ``logs``       ``{resource, lines}``
* ``deploys`` / ``alerts`` / ``status`` / ``feed``  ``{limit, …}``
* ``actions``    ``{actions: [...]}``
* ``specs``      ``{resource}``

``resource: '$server'`` is the server variable the dashboard topbar binds, so a
default board follows whichever server the operator has selected.

Metrics are limited to the ones the panel actually records
(``MetricsHistory``): cpu, ram, disk and load.
"""

import copy

from app import db
from app.models.dashboard import DashboardBoard

# Grid width. Mirrors GRID_COLS in the frontend's grid/layout.js.
GRID_COLS = 12

# Hard ceiling on widgets per board, enforced by the API layer. Generous for a
# real dashboard, small enough that a runaway client can't store a megabyte of
# JSON per board.
MAX_WIDGETS_PER_BOARD = 100


DEFAULT_BOARDS = [
    {
        'slug': 'overview',
        'name': 'Overview',
        'icon': 'grid',
        'position': 0,
        'widgets': [
            # Row 0-1: four stats across the top.
            {'i': 'w1', 'type': 'stat', 'x': 0, 'y': 0, 'w': 3, 'h': 2,
             'cfg': {'metric': 'cpu', 'agg': 'last', 'resource': '$server',
                     'thresholds': [70, 90]}},
            {'i': 'w2', 'type': 'stat', 'x': 3, 'y': 0, 'w': 3, 'h': 2,
             'cfg': {'metric': 'ram', 'agg': 'last', 'resource': '$server',
                     'thresholds': [80, 92]}},
            {'i': 'w3', 'type': 'stat', 'x': 6, 'y': 0, 'w': 3, 'h': 2,
             'cfg': {'metric': 'disk', 'agg': 'last', 'resource': '$server',
                     'thresholds': [75, 90]}},
            {'i': 'w4', 'type': 'stat', 'x': 9, 'y': 0, 'w': 3, 'h': 2,
             'cfg': {'metric': 'load', 'agg': 'last', 'resource': '$server',
                     'thresholds': None}},
            # Rows 2-5: the wide chart, with quick actions + host details stacked
            # in the right-hand column.
            {'i': 'w5', 'type': 'timeseries', 'x': 0, 'y': 2, 'w': 8, 'h': 4,
             'cfg': {'metrics': ['cpu', 'ram'], 'resource': '$server'}},
            {'i': 'w6', 'type': 'actions', 'x': 8, 'y': 2, 'w': 4, 'h': 2,
             'cfg': {'actions': ['new-app', 'deploy', 'terminal', 'backup']}},
            {'i': 'w7', 'type': 'specs', 'x': 8, 'y': 4, 'w': 4, 'h': 2,
             'cfg': {'resource': '$server'}},
            # Rows 6-9: inventory + what happened.
            {'i': 'w8', 'type': 'table', 'x': 0, 'y': 6, 'w': 8, 'h': 4,
             'cfg': {'source': 'apps', 'limit': 8}},
            {'i': 'w9', 'type': 'feed', 'x': 8, 'y': 6, 'w': 4, 'h': 4,
             'cfg': {'limit': 10}},
        ],
    },
    {
        'slug': 'infra',
        'name': 'Infrastructure',
        'icon': 'server',
        'position': 1,
        'widgets': [
            # Rows 0-3: fleet-wide chart + the ranked hot list.
            {'i': 'w1', 'type': 'timeseries', 'x': 0, 'y': 0, 'w': 8, 'h': 4,
             'cfg': {'metrics': ['cpu', 'ram', 'disk'], 'resource': '$server'}},
            {'i': 'w2', 'type': 'topn', 'x': 8, 'y': 0, 'w': 4, 'h': 4,
             'cfg': {'metric': 'cpu', 'source': 'servers', 'limit': 5}},
            # Rows 4-6: two dials and the up/down matrix.
            {'i': 'w3', 'type': 'gauge', 'x': 0, 'y': 4, 'w': 3, 'h': 3,
             'cfg': {'metric': 'cpu', 'resource': '$server',
                     'thresholds': [70, 90]}},
            {'i': 'w4', 'type': 'gauge', 'x': 3, 'y': 4, 'w': 3, 'h': 3,
             'cfg': {'metric': 'ram', 'resource': '$server',
                     'thresholds': [80, 92]}},
            {'i': 'w5', 'type': 'status', 'x': 6, 'y': 4, 'w': 6, 'h': 3,
             'cfg': {'limit': 12}},
            # Rows 7-10: containers + anything currently shouting.
            {'i': 'w6', 'type': 'table', 'x': 0, 'y': 7, 'w': 8, 'h': 4,
             'cfg': {'source': 'containers', 'limit': 8}},
            {'i': 'w7', 'type': 'alerts', 'x': 8, 'y': 7, 'w': 4, 'h': 4,
             'cfg': {'limit': 8, 'severity': 'all'}},
        ],
    },
    {
        'slug': 'apps',
        'name': 'Apps',
        'icon': 'rocket',
        'position': 2,
        'widgets': [
            # Rows 0-1: three wider stats, averaged over the selected range.
            {'i': 'w1', 'type': 'stat', 'x': 0, 'y': 0, 'w': 4, 'h': 2,
             'cfg': {'metric': 'cpu', 'agg': 'avg', 'resource': '$server',
                     'thresholds': [70, 90]}},
            {'i': 'w2', 'type': 'stat', 'x': 4, 'y': 0, 'w': 4, 'h': 2,
             'cfg': {'metric': 'ram', 'agg': 'avg', 'resource': '$server',
                     'thresholds': [80, 92]}},
            {'i': 'w3', 'type': 'stat', 'x': 8, 'y': 0, 'w': 4, 'h': 2,
             'cfg': {'metric': 'load', 'agg': 'last', 'resource': '$server',
                     'thresholds': None}},
            # Rows 2-5: load over time next to the deploy stream.
            {'i': 'w4', 'type': 'timeseries', 'x': 0, 'y': 2, 'w': 8, 'h': 4,
             'cfg': {'metrics': ['cpu', 'ram'], 'resource': '$server'}},
            {'i': 'w5', 'type': 'deploys', 'x': 8, 'y': 2, 'w': 4, 'h': 4,
             'cfg': {'limit': 8}},
            # Rows 6-9: full-width tail.
            {'i': 'w6', 'type': 'logs', 'x': 0, 'y': 6, 'w': 12, 'h': 4,
             'cfg': {'resource': '$server', 'lines': 60}},
        ],
    },
]


def get_default_board(slug):
    """A deep copy of one shipped default, or None when the slug is unknown."""
    for spec in DEFAULT_BOARDS:
        if spec['slug'] == slug:
            return copy.deepcopy(spec)
    return None


def seed_defaults(user_id):
    """Create the shipped default boards for a user. Returns the new rows."""
    created = []
    for spec in DEFAULT_BOARDS:
        board = DashboardBoard(
            user_id=user_id,
            slug=spec['slug'],
            name=spec['name'],
            icon=spec['icon'],
            position=spec['position'],
            widgets=copy.deepcopy(spec['widgets']),
        )
        db.session.add(board)
        created.append(board)
    db.session.commit()
    return created


def get_boards_for_user(user_id):
    """Every board owned by this user, seeding the shipped defaults on the
    first read for a user who has none."""
    boards = (DashboardBoard.query
              .filter_by(user_id=user_id)
              .order_by(DashboardBoard.position, DashboardBoard.id)
              .all())
    if boards:
        return boards
    seed_defaults(user_id)
    return (DashboardBoard.query
            .filter_by(user_id=user_id)
            .order_by(DashboardBoard.position, DashboardBoard.id)
            .all())


def get_board_for_user(user_id, board_id):
    """One board, scoped to its owner. None means "not yours / not there" — the
    caller must not distinguish the two."""
    return DashboardBoard.query.filter_by(id=board_id, user_id=user_id).first()


def create_board(user_id, name, icon=None, widgets=None):
    """Add a user-created board after the existing ones. ``slug`` stays NULL:
    a board the user invented has no shipped default to reset to."""
    last = (db.session.query(db.func.max(DashboardBoard.position))
            .filter(DashboardBoard.user_id == user_id).scalar())
    board = DashboardBoard(
        user_id=user_id,
        slug=None,
        name=name,
        icon=icon or 'grid',
        position=(last + 1) if last is not None else 0,
        widgets=list(widgets or []),
    )
    db.session.add(board)
    db.session.commit()
    return board


def update_board(board, name=None, icon=None, position=None, widgets=None):
    """Patch the fields that were actually supplied."""
    if name is not None:
        board.name = name
    if icon is not None:
        board.icon = icon
    if position is not None:
        board.position = position
    if widgets is not None:
        board.widgets = list(widgets)
    db.session.commit()
    return board


def delete_board(board):
    db.session.delete(board)
    db.session.commit()
    return True


def reset_board(board):
    """Restore a board to its shipped default. Returns None when the board was
    created by the user and therefore has no default to go back to."""
    spec = get_default_board(board.slug) if board.slug else None
    if not spec:
        return None
    board.name = spec['name']
    board.icon = spec['icon']
    board.widgets = copy.deepcopy(spec['widgets'])
    db.session.commit()
    return board
