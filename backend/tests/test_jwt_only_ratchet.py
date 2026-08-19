"""The JWT-only adoption ratchet (plan 76, milestone A closure).

This ratchet records a DECISION, not a debt: bare ``@jwt_required()`` routes
are JWT-only on purpose, because converting one to ``auth_required()`` grants
API-key access — a per-route policy call, never a sweep. See the module
docstring in ``jwt_only_census.py`` for the recorded decision.

What the ceiling enforces is the two directions that must not happen:

  * the population must not GROW — a new route picks a policy decorator;
  * a conversion must not be silent — shrinking the count requires the
    committer to refresh the ceiling in the same commit, which is exactly
    the "a commit that says so" the decision demands.
"""

from jwt_only_census import census, count_file, read_ceiling, total


def test_the_count_is_at_or_below_the_ceiling():
    found = census()
    count = total(found)
    ceiling = read_ceiling()
    worst = sorted(found, key=lambda p: -len(found[p]))[:5]
    assert count <= ceiling, (
        f'{count} routes authenticate with bare @jwt_required(), ceiling is '
        f'{ceiling}.\n'
        f'New routes must use a policy decorator (auth_required() or a role '
        f'decorator), not bare @jwt_required().\n'
        f'Heaviest files: ' + ', '.join(f'{p} ({len(found[p])})' for p in worst)
    )


def test_the_ceiling_is_not_stale():
    """A slack ceiling would let JWT-only routes creep back in unnoticed."""
    count, ceiling = total(), read_ceiling()
    assert ceiling - count <= 10, (
        f'ceiling {ceiling} is {ceiling - count} above the actual {count}; '
        f'run `python tests/jwt_only_census.py --update`'
    )


class TestTheCensusCountsTheRightThings:
    """A miscounting ratchet is worse than none: it reads green either way."""

    def _count(self, tmp_path, source):
        path = tmp_path / 'sample.py'
        path.write_text(source, encoding='utf-8')
        return len(count_file(str(path)))

    def test_counts_the_called_decorator(self, tmp_path):
        assert self._count(tmp_path, (
            "@bp.route('/x')\n"
            '@jwt_required()\n'
            'def handler():\n'
            '    pass\n'
        )) == 1

    def test_counts_the_bare_decorator(self, tmp_path):
        assert self._count(tmp_path, (
            '@jwt_required\n'
            'def handler():\n'
            '    pass\n'
        )) == 1

    def test_does_not_count_policy_decorators(self, tmp_path):
        assert self._count(tmp_path, (
            "@bp.route('/x')\n"
            '@auth_required()\n'
            'def a():\n'
            '    pass\n'
            '\n'
            '@admin_required\n'
            'def b():\n'
            '    pass\n'
        )) == 0

    def test_does_not_count_a_call_inside_the_body(self, tmp_path):
        """Only the decorator position is an authentication choice."""
        assert self._count(tmp_path, (
            'def handler():\n'
            '    verify = jwt_required()\n'
        )) == 0
