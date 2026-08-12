"""Shared list-query layer: ``$select`` / ``$filter`` / ``$orderby`` / ``$skip`` / ``$top``.

Ported from the author's ``conuco_v2`` query layer, with two deliberate changes.

**ORM, not Core.** conuco resolves columns through ``table.c``; ServerKit is
Flask-SQLAlchemy ORM, so fields resolve against the mapper's column set. That
set is also the allowlist — a field that is not a real mapped column is a 400,
never an ``getattr`` into arbitrary model attributes.

**``$select`` is not only a column narrowing.** This is where the actual win is
here. ``Application.to_dict()`` costs roughly three extra queries per row on top
of the row itself: ``image_scans.first()`` and ``image_update_checks.first()``
are ``lazy='dynamic'`` relationships (immune to eager loading — a dynamic
attribute *is* a Query), and ``sleep_policy`` / ``server`` / ``project`` /
``environment`` are lazy scalars. Drawing a 100-app list is ~300 queries. So
``parse_select`` hands back a *field set* that ``to_dict`` uses to skip the
loads it was not asked for: ``$select=id,name`` goes from 3 queries per row to
zero extra ones.

Not implemented here: ``$view``. conuco resolves a named server-side view into
default ``$filter``/``$orderby``/``$select``, but ServerKit's saved views are
per-user rows already resolved in the browser (see
``components/ds/grid/viewState.js``) — the grid knows the concrete config and
can serialize it, so a second server-side copy of the same concept would be a
place for the two to disagree.

Usage::

    from app.api._query import apply_query

    q = apply_query(Application.query, Application, request)
    apps = q.query.all()
    return jsonify({'apps': [a.to_dict(fields=q.fields) for a in apps]})

Every parameter is optional: with none of them present this is a no-op and the
endpoint behaves exactly as it did before.
"""

import re
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, inspect

# Hard ceiling on ``$top``. A list endpoint that answers "give me everything"
# is how /apps got to an unbounded ``query.all()``; a caller that genuinely
# wants more than this should page.
MAX_TOP = 500

COMPARE_OPS = {
    'eq': lambda col, val: col == val,
    'ne': lambda col, val: col != val,
    'gt': lambda col, val: col > val,
    'ge': lambda col, val: col >= val,
    'lt': lambda col, val: col < val,
    'le': lambda col, val: col <= val,
}


class QueryParseError(ValueError):
    """A malformed query parameter. API layers turn this into a 400."""


def _columns(model):
    """The model's real mapped columns — and the field allowlist."""
    return {c.key: getattr(model, c.key) for c in inspect(model).mapper.column_attrs}


def _column(model, field):
    field = (field or '').strip()
    cols = _columns(model)
    if field not in cols:
        raise QueryParseError(f"Unknown field '{field}' for '{model.__tablename__}'.")
    return cols[field]


def _coerce(value):
    """Literal -> Python. Quoted stays a string; bare words get typed."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    low = value.lower()
    if low == 'true':
        return True
    if low == 'false':
        return False
    if low in ('null', 'none'):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


# ---------------------------------------------------------------- $filter

_FUNCS = (
    ('contains', r"contains\(([^,]+),\s*['\"]([^'\"]*)['\"]\)",
     lambda col, v: col.ilike(f'%{v}%')),
    ('startswith', r"startswith\(([^,]+),\s*['\"]([^'\"]*)['\"]\)",
     lambda col, v: col.ilike(f'{v}%')),
    ('endswith', r"endswith\(([^,]+),\s*['\"]([^'\"]*)['\"]\)",
     lambda col, v: col.ilike(f'%{v}')),
)


def _parse_function(condition, model):
    """A function-call condition, or None if this isn't one."""
    for _name, pattern, build in _FUNCS:
        match = re.findall(pattern, condition)
        if match:
            field, value = match[0]
            return build(_column(model, field), value)

    match = re.findall(r'notempty\(([^)]+)\)', condition)
    if match:
        col = _column(model, match[0])
        return and_(col.isnot(None), col != '')

    match = re.findall(r"date\(([^,]+),\s*['\"]([^'\"]*)['\"]\)", condition)
    if match:
        field, value = match[0]
        try:
            day = datetime.strptime(value.strip(), '%Y-%m-%d')
        except ValueError as exc:
            raise QueryParseError(f"date() needs YYYY-MM-DD, got '{value}'.") from exc
        col = _column(model, field)
        return and_(col >= day, col < day + timedelta(days=1))

    match = re.findall(r'daysAgo\(([^,]+),\s*([^)]+)\)', condition)
    if match:
        field, raw = match[0]
        try:
            days = int(raw.strip())
        except ValueError as exc:
            raise QueryParseError(f"daysAgo() needs an integer, got '{raw}'.") from exc
        return _column(model, field) >= datetime.utcnow() - timedelta(days=days)

    return None


def _parse_condition(condition, model):
    built = _parse_function(condition, model)
    if built is not None:
        return built

    match = re.match(r'^\s*(\S+)\s+(eq|ne|gt|ge|lt|le)\s+(.+?)\s*$', condition)
    if not match:
        raise QueryParseError(f"Could not parse condition '{condition.strip()}'.")
    field, op, raw = match.groups()
    return COMPARE_OPS[op](_column(model, field), _coerce(raw))


def parse_filter(filter_str, model):
    """``$filter`` -> a WHERE clause, or None.

    One combiner per string (``and`` OR ``or``, not both) — same restriction as
    the original. Mixing them without parentheses is ambiguous, and silently
    picking a precedence is worse than refusing.
    """
    if not filter_str or not filter_str.strip():
        return None

    has_and = re.search(r'\s+and\s+', filter_str, re.IGNORECASE)
    has_or = re.search(r'\s+or\s+', filter_str, re.IGNORECASE)
    if has_and and has_or:
        raise QueryParseError("Mixing 'and' with 'or' needs separate requests — it is ambiguous here.")

    combiner, pattern = (or_, r'\s+or\s+') if has_or else (and_, r'\s+and\s+')
    parts = [p for p in re.split(pattern, filter_str, flags=re.IGNORECASE) if p.strip()]
    clauses = [_parse_condition(p, model) for p in parts]
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else combiner(*clauses)


# --------------------------------------------------------------- $orderby

def parse_orderby(orderby_str, model):
    """``$orderby=name asc,created_at desc`` -> a list of ORDER BY clauses."""
    if not orderby_str or not orderby_str.strip():
        return []
    out = []
    for part in orderby_str.split(','):
        bits = part.strip().split()
        if not bits:
            continue
        col = _column(model, bits[0])
        direction = (bits[1] if len(bits) > 1 else 'asc').lower()
        if direction not in ('asc', 'desc'):
            raise QueryParseError(f"Sort direction must be asc or desc, got '{direction}'.")
        out.append(col.desc() if direction == 'desc' else col.asc())
    return out


# ---------------------------------------------------------------- $select

def parse_select(select_str, model, extra=()):
    """``$select`` -> the requested field set, or None for "everything".

    `extra` names DERIVED fields a model's ``to_dict`` can emit that are not
    mapped columns (``project_name``, ``image_scan``, ``domains``…). They are
    accepted here so a caller can ask for one, and it is precisely by NOT
    asking that the caller skips its lazy load.
    """
    if not select_str or not select_str.strip():
        return None
    allowed = set(_columns(model)) | set(extra)
    fields = set()
    for raw in select_str.split(','):
        name = raw.strip()
        if not name:
            continue
        if name not in allowed:
            raise QueryParseError(f"Unknown field '{name}' for '{model.__tablename__}'.")
        fields.add(name)
    # The primary key always comes back — a row the client cannot identify is
    # not much use, and every UI keys its rows on it.
    pk = inspect(model).mapper.primary_key
    for col in pk:
        fields.add(col.key)
    return fields


# ------------------------------------------------------------- apply_query

class QueryResult:
    """The narrowed query plus what the caller needs to serialize it."""

    __slots__ = ('query', 'fields', 'skip', 'top', 'total')

    def __init__(self, query, fields, skip, top, total):
        self.query = query
        self.fields = fields
        self.skip = skip
        self.top = top
        self.total = total

    def as_meta(self):
        """Paging metadata for the response envelope."""
        return {'total': self.total, 'skip': self.skip, 'top': self.top}


def apply_query(query, model, request, *, default_top=None, select_extra=()):
    """Apply the query params present on `request` to `query`.

    Returns a :class:`QueryResult`. With no params present this is a no-op and
    ``.fields`` is None, so an endpoint can adopt it without changing any
    existing caller's response.

    `default_top` bounds an endpoint that has no explicit ``$top``; leave it
    None to keep today's unbounded behaviour while callers migrate.
    """
    args = request.args
    where = parse_filter(args.get('$filter'), model)
    if where is not None:
        query = query.filter(where)

    order = parse_orderby(args.get('$orderby'), model)
    if order:
        query = query.order_by(*order)

    fields = parse_select(args.get('$select'), model, extra=select_extra)

    # `total` is the count BEFORE paging — the client needs it to render "12 of
    # 340", and computing it after .limit() would just return the page size.
    total = None
    skip = _int_arg(args.get('$skip'), 0, '$skip')
    top = _int_arg(args.get('$top'), default_top, '$top')
    if top is not None:
        top = max(0, min(top, MAX_TOP))
    if skip or top is not None:
        total = query.order_by(None).count()
        if skip:
            query = query.offset(skip)
        if top is not None:
            query = query.limit(top)

    return QueryResult(query, fields, skip, top, total)


def _int_arg(raw, fallback, name):
    if raw is None or raw == '':
        return fallback
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise QueryParseError(f'{name} must be an integer.') from exc
    if value < 0:
        raise QueryParseError(f'{name} cannot be negative.')
    return value
