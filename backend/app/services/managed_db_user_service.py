"""Managed database users — durable rows for the users/grants ServerKit creates.

The engines already know their users; ServerKit didn't. This service creates
users *in* the engine (CREATE USER / GRANT via the same host/docker exec paths
``database_service`` uses) and records a ``ManagedDatabaseUser`` row beside the
managed database so the panel survives restarts and SSO can mint scoped,
single-use shadow credentials.

Passwords are generated with ``secrets`` unless supplied, returned exactly once
from ``create_user`` and never stored or logged. All engine SQL funnels through
the single choke-point ``_exec_sql`` so tests can stub it.
"""
import logging
import re
import secrets
from datetime import datetime

from app import db
from app.models.managed_database_user import ManagedDatabaseUser  # explicit import registers the table
from app.services import db_exec
from app.utils.crypto import decrypt_secret_safe

logger = logging.getLogger(__name__)

SUPPORTED_ENGINES = ('mysql', 'postgresql')

# Engine identifiers we will interpolate into SQL. Deliberately strict.
_USERNAME_RE = re.compile(r'^[A-Za-z0-9_]{1,32}$')
_DBNAME_RE = re.compile(r'^[A-Za-z0-9_\-]{1,64}$')
# Grant keywords: uppercase words (optionally multi-word, e.g. LOCK TABLES).
_GRANT_RE = re.compile(r'^[A-Z][A-Z_ ]{0,40}$')


class ManagedDbUserService:
    """Create/list/delete database users on a managed database + track rows."""

    # ── choke-point: all engine SQL goes through here (tests monkeypatch it) ──
    @classmethod
    def _exec_sql(cls, managed, sql):
        """Execute ``sql`` against the engine backing ``managed``.

        Returns the ``{'success': bool, 'output': str, 'error': str|None}``
        shape of ``DatabaseService`` executors.
        """
        secret = decrypt_secret_safe(managed.admin_secret_encrypted or '') or None
        return db_exec.exec_sql(db_exec.target_from_managed(managed, password=secret), sql)

    # ── validation / quoting helpers ──
    @staticmethod
    def generate_password():
        return secrets.token_urlsafe(24)

    @staticmethod
    def _validate_username(username):
        return bool(username) and bool(_USERNAME_RE.match(username))

    @staticmethod
    def _validate_grants(grants):
        return all(isinstance(g, str) and _GRANT_RE.match(g.strip().upper())
                   for g in grants)

    @staticmethod
    def _escape_mysql_string(value):
        return value.replace('\\', '\\\\').replace("'", "\\'")

    @staticmethod
    def _escape_pg_string(value):
        return value.replace("'", "''")

    # ── SQL builders (pure, unit-testable) ──
    @classmethod
    def _create_user_sql(cls, engine, db_name, username, password, grants):
        """The statements that create + scope a user to ONE database."""
        grant_list = ', '.join(g.strip().upper() for g in grants)
        if engine == 'mysql':
            pw = cls._escape_mysql_string(password)
            privs = 'ALL PRIVILEGES' if grant_list == 'ALL' else grant_list
            return [
                f"CREATE USER '{username}'@'%' IDENTIFIED BY '{pw}';",
                f"GRANT {privs} ON `{db_name}`.* TO '{username}'@'%';",
                'FLUSH PRIVILEGES;',
            ]
        if engine == 'postgresql':
            pw = cls._escape_pg_string(password)
            stmts = [f"CREATE USER \"{username}\" WITH PASSWORD '{pw}';"]
            if grant_list == 'ALL':
                stmts.append(
                    f'GRANT ALL PRIVILEGES ON DATABASE "{db_name}" TO "{username}";')
            else:
                stmts.append(
                    f'GRANT CONNECT ON DATABASE "{db_name}" TO "{username}";')
                stmts.append(
                    f'GRANT {grant_list} ON ALL TABLES IN SCHEMA public TO "{username}";')
            return stmts
        return []

    @classmethod
    def _drop_user_sql(cls, engine, username):
        if engine == 'mysql':
            return [f"DROP USER IF EXISTS '{username}'@'%';", 'FLUSH PRIVILEGES;']
        if engine == 'postgresql':
            return [f'DROP USER IF EXISTS "{username}";']
        return []

    # ── operations ──
    @classmethod
    def create_user(cls, managed, username=None, password=None, grants=None,
                    is_shadow=False, expires_at=None):
        """CREATE USER + GRANT scoped to this one database, then record the row.

        Returns ``{'user': dict, 'password': str}`` — the only time the
        password is ever visible — or ``{'error': msg}``.
        """
        if managed.engine not in SUPPORTED_ENGINES:
            return {'error': 'unsupported engine'}
        if not _DBNAME_RE.match(managed.name or ''):
            return {'error': 'Invalid database name'}

        username = (username or f'sk_{secrets.token_hex(3)}').strip()
        if not cls._validate_username(username):
            return {'error': 'Invalid username: letters, digits and underscores only (max 32)'}

        grants = list(grants or ['ALL'])
        if not grants or not cls._validate_grants(grants):
            return {'error': 'Invalid grants'}

        existing = ManagedDatabaseUser.query.filter_by(
            managed_database_id=managed.id, username=username).first()
        if existing:
            return {'error': 'User already tracked for this database'}

        password = password or cls.generate_password()

        for sql in cls._create_user_sql(managed.engine, managed.name,
                                        username, password, grants):
            result = cls._exec_sql(managed, sql)
            if not result.get('success'):
                # Best-effort cleanup so a failed GRANT doesn't leave an orphan user.
                for cleanup in cls._drop_user_sql(managed.engine, username):
                    cls._exec_sql(managed, cleanup)
                return {'error': result.get('error') or 'Engine statement failed'}

        row = cls.ensure_recorded(managed, username, grants=grants,
                                  is_shadow=is_shadow, expires_at=expires_at)
        return {'user': row.to_dict(), 'password': password}

    @classmethod
    def ensure_recorded(cls, managed, username, grants=None, is_shadow=False,
                        expires_at=None):
        """Find-or-create the tracking row WITHOUT touching the engine —
        used to adopt users that already exist server-side."""
        row = ManagedDatabaseUser.query.filter_by(
            managed_database_id=managed.id, username=username).first()
        if row is None:
            row = ManagedDatabaseUser(managed_database_id=managed.id,
                                      username=username)
            db.session.add(row)
        row.set_grants(grants or ['ALL'])
        row.is_shadow = bool(is_shadow)
        row.expires_at = expires_at
        db.session.commit()
        return row

    @classmethod
    def list_users(cls, managed, include_shadow=False):
        """Tracked rows merged best-effort with the live engine user list.

        Each tracked row carries ``present`` (True/False/None=unknown); live
        users ServerKit didn't create are appended as untracked stubs.
        """
        q = ManagedDatabaseUser.query.filter_by(managed_database_id=managed.id)
        if not include_shadow:
            q = q.filter_by(is_shadow=False)
        rows = q.order_by(ManagedDatabaseUser.created_at.asc()).all()

        live = cls._list_engine_usernames(managed)
        users = []
        for row in rows:
            present = None if live is None else (row.username in live)
            users.append(row.to_dict(live={'present': present}))
        if live is not None:
            tracked = {r.username for r in rows}
            for name in live:
                if name not in tracked and not name.startswith('sk_sso_'):
                    users.append({'username': name, 'tracked': False, 'present': True})
        return users

    @classmethod
    def _list_engine_usernames(cls, managed):
        """Best-effort live usernames, or None when the engine is unreachable."""
        if managed.engine == 'mysql':
            sql = "SELECT User FROM mysql.user WHERE User NOT IN ('root', 'mysql.sys', 'mysql.session', 'mysql.infoschema');"
        elif managed.engine == 'postgresql':
            sql = "SELECT rolname FROM pg_roles WHERE rolcanlogin = true AND rolname <> 'postgres';"
        else:
            return None
        try:
            result = cls._exec_sql(managed, sql)
            if not result.get('success'):
                return None
            lines = [ln.strip() for ln in (result.get('output') or '').strip().split('\n')]
            # mysql CLI prints a header row; psql -t -A does not.
            if managed.engine == 'mysql' and lines and lines[0].lower() == 'user':
                lines = lines[1:]
            return [ln for ln in lines if ln]
        except Exception as e:  # pragma: no cover - defensive
            logger.debug('live user listing failed for %s: %s', managed.name, e)
            return None

    @classmethod
    def delete_user(cls, managed, row):
        """DROP USER in the engine, then remove the tracking row."""
        if managed.engine not in SUPPORTED_ENGINES:
            return {'error': 'unsupported engine'}
        for sql in cls._drop_user_sql(managed.engine, row.username):
            result = cls._exec_sql(managed, sql)
            if not result.get('success'):
                return {'error': result.get('error') or 'DROP USER failed'}
        db.session.delete(row)
        db.session.commit()
        return {'success': True}

    @classmethod
    def reap_expired_shadow_users(cls):
        """Drop expired shadow credentials engine-side and delete their rows.
        Best-effort per user; returns the number of rows removed."""
        now = datetime.utcnow()
        expired = (ManagedDatabaseUser.query
                   .filter(ManagedDatabaseUser.is_shadow.is_(True))
                   .filter(ManagedDatabaseUser.expires_at.isnot(None))
                   .filter(ManagedDatabaseUser.expires_at < now)
                   .all())
        removed = 0
        for row in expired:
            managed = row.managed_database
            try:
                if managed is not None:
                    for sql in cls._drop_user_sql(managed.engine, row.username):
                        cls._exec_sql(managed, sql)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning('Failed to drop expired shadow user %s: %s',
                               row.username, e)
            db.session.delete(row)
            removed += 1
        if removed:
            db.session.commit()
            logger.info('Reaped %d expired shadow database user(s)', removed)
        return removed
