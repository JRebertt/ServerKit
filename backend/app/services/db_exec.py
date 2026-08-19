"""One SQL-exec dispatcher (plan 75 §G5).

`engine × host` dispatch — mysql/postgres crossed with native/docker — was
written three times: `db_config_tuner_service`, `db_process_service`, and
`managed_db_user_service`. Only the last delegated fully to `DatabaseService`'s
four executors; the other two grew private copies that had already drifted (one
never learned about `ON_ERROR_STOP=1`, so psql reported success for statements
the server rejected).

This module is the dispatch, and nothing else. The four executors stay in
`DatabaseService` — this does not become a second place where SQL is run, only
the single place where "which executor" is decided.

Every executor returns the same shape, and so does this::

    {'success': bool, 'output': str, 'error': str|None}

A target is a plain dict so callers can build one from a `ManagedDatabase` row,
a container name, or a tuner probe without a common base class:

    {'engine': 'mysql'|'postgresql', 'container': str|None,
     'user': str|None, 'password': str|None, 'database': str|None}

`container` is what decides native-vs-docker. `None`/absent means native.
"""

from typing import Optional

from app.services.database_service import DatabaseService

# The names the rest of the codebase spells these engines with. Kept here so an
# unknown engine is *reported*, never silently routed to mysql (§A).
MYSQL_ALIASES = ('mysql', 'mariadb')
POSTGRES_ALIASES = ('postgresql', 'postgres', 'pgsql')


def target(engine: str, *, container: Optional[str] = None,
           user: Optional[str] = None, password: Optional[str] = None,
           database: Optional[str] = None) -> dict:
    """Build a target dict. Keyword-only so a call site reads at a glance."""
    return {'engine': engine, 'container': container, 'user': user,
            'password': password, 'database': database}


def target_from_managed(managed, *, password: Optional[str] = None) -> dict:
    """A target for a ``ManagedDatabase`` row.

    The admin secret is passed in rather than decrypted here: decryption needs
    app context, and this module deliberately does not reach for it.
    """
    return target(
        managed.engine,
        container=managed.container_ref if managed.host_kind == 'docker' else None,
        user=managed.admin_username or None,
        password=password,
    )


def exec_sql(tgt: dict, sql: str, *, machine_readable: bool = False,
             timeout: int = 30) -> dict:
    """Run *sql* against *tgt*'s engine, native or containerised.

    ``machine_readable`` asks the client for parse-friendly output (no headers,
    tab-separated). Pass it when the caller splits the output; leave it off
    when the output is shown to a person.
    """
    engine = (tgt.get('engine') or '').strip().lower()
    container = tgt.get('container')
    user = tgt.get('user')
    password = tgt.get('password')
    database = tgt.get('database')

    if engine in MYSQL_ALIASES:
        if container:
            return DatabaseService.docker_mysql_execute(
                container, sql, database=database, user=user or 'root',
                password=password, machine_readable=machine_readable,
                timeout=timeout)
        return DatabaseService.mysql_execute(
            sql, database=database, root_password=password)

    if engine in POSTGRES_ALIASES:
        if container:
            return DatabaseService.docker_pg_execute(
                container, sql, database=database or 'postgres',
                user=user or 'postgres', password=password,
                timeout=timeout, machine_readable=machine_readable)
        return DatabaseService.pg_execute(
            sql, database=database or 'postgres', user=user or 'postgres')

    # Not a default. An unrecognised engine that quietly ran as mysql would
    # produce a syntax error blamed on the caller's SQL.
    return {'success': False, 'output': '',
            'error': f"unsupported engine: {tgt.get('engine')!r}"}
