"""Transaction ownership contract for top-level service use cases."""

import pytest

from app.services.unit_of_work import unit_of_work


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_unit_of_work_commits_once_after_success():
    session = FakeSession()

    with unit_of_work(session):
        pass

    assert session.commits == 1
    assert session.rollbacks == 0


def test_unit_of_work_rolls_back_and_preserves_original_failure():
    session = FakeSession()

    with pytest.raises(RuntimeError, match='operation failed'):
        with unit_of_work(session):
            raise RuntimeError('operation failed')

    assert session.commits == 0
    assert session.rollbacks == 1


def test_unit_of_work_rolls_back_a_failed_commit():
    class FailedCommitSession(FakeSession):
        def commit(self):
            super().commit()
            raise RuntimeError('commit failed')

    session = FailedCommitSession()
    with pytest.raises(RuntimeError, match='commit failed'):
        with unit_of_work(session):
            pass

    assert session.commits == 1
    assert session.rollbacks == 1
