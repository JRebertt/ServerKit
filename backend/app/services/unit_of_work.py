"""Small transaction boundary for top-level service use cases."""

from contextlib import contextmanager

from app import db


@contextmanager
def unit_of_work(session=None):
    """Commit one use case atomically and always roll back a failed attempt.

    Lower-level helpers called inside this context may flush, but must not
    commit.  External side effects belong after the context so a remote call is
    never mistaken for part of the database transaction.
    """

    active_session = session if session is not None else db.session
    try:
        yield active_session
        active_session.commit()
    except Exception:
        active_session.rollback()
        raise
