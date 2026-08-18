"""The identity-door ratchet (plan 76, milestone A).

Plan 76's second-wave rule 1: every door gets a ratchet *before* its migration
starts, because a migration without one regrows. This is milestone A's.

The count it holds is the number of places that answer "who is calling" by
reading the JWT directly instead of going through
``app/middleware/rbac.get_current_user()``. It is a test rather than a CI shell
step so it runs on a dev box before the commit, and the counting is AST-based —
a grep for ``get_jwt_identity`` also matches token issuance, an id comparison,
and a docstring, none of which are identity lookups.

The remaining population is entirely on ``@jwt_required()``-only routes, where
reading the JWT is correct *today*. It is counted anyway because it is exactly
what breaks the moment such a route is moved to a policy decorator — which is
the rest of milestone A. The ceiling is what stops that migration from
converting a correct route into a 500.
"""

from identity_door_census import census, count_file, read_ceiling, total


def test_the_count_is_at_or_below_the_ceiling():
    found = census()
    count = total(found)
    ceiling = read_ceiling()
    worst = sorted(found, key=lambda p: -len(found[p]))[:5]
    assert count <= ceiling, (
        f'{count} identity lookups bypass rbac.get_current_user(), ceiling is '
        f'{ceiling}.\n'
        f'Resolve the caller with rbac.get_current_user() — it returns '
        f'g.api_key_user for X-API-Key requests, where get_jwt_identity() '
        f'raises.\n'
        f'If a lookup genuinely must be JWT-only, add the file to EXEMPT in '
        f'tests/identity_door_census.py in the same commit and say why.\n'
        f'Heaviest files: ' + ', '.join(f'{p} ({len(found[p])})' for p in worst)
    )


def test_the_ceiling_is_not_stale():
    """A ceiling above reality silently re-authorises what a migration removed."""
    count, ceiling = total(), read_ceiling()
    assert ceiling - count <= 10, (
        f'ceiling {ceiling} is {ceiling - count} above the actual {count}; '
        f'run `python tests/identity_door_census.py --update`'
    )


def test_no_bypass_survives_behind_an_api_key_capable_decorator():
    """The live-bug half of the ratchet.

    A bypass under ``@jwt_required()`` is merely legacy. The same bypass under a
    policy decorator is a 500 for every API-key caller, because
    ``auth_required()`` skips ``verify_jwt_in_request()`` once the key
    middleware has authenticated and ``get_jwt_identity()`` then raises. That
    population is zero and must stay zero.
    """
    import ast

    POLICY = {'admin_required', 'developer_required', 'viewer_required',
              'require_role', 'permission_required', 'require_app_member',
              'auth_required'}

    def _name(dec):
        while isinstance(dec, ast.Call):
            dec = dec.func
        return getattr(dec, 'attr', getattr(dec, 'id', ''))

    offenders = []
    for rel, hits in census().items():
        tree = ast.parse(open(rel, encoding='utf-8').read())
        lines = {line for line, _ in hits}
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            spans = [n.lineno for n in ast.walk(node) if hasattr(n, 'lineno')]
            inside = lines & set(range(node.lineno, max(spans or [node.lineno]) + 1))
            if not inside:
                continue
            policies = [_name(d) for d in node.decorator_list if _name(d) in POLICY]
            if policies:
                offenders.append(f'{rel}:{sorted(inside)[0]} {node.name}() '
                                 f'<- @{", @".join(policies)}')

    assert not offenders, (
        'these handlers admit API-key callers but resolve identity from the '
        'JWT, which raises for exactly those requests:\n  '
        + '\n  '.join(offenders)
    )


class TestTheCensusCountsTheRightThings:
    """A miscounting ratchet is worse than none: it reads green either way."""

    def _count(self, tmp_path, source):
        path = tmp_path / 'sample.py'
        path.write_text(source, encoding='utf-8')
        return len(count_file(str(path)))

    def test_counts_the_direct_shape(self, tmp_path):
        assert self._count(tmp_path, (
            'user = User.query.get(get_jwt_identity())\n'
        )) == 1

    def test_counts_the_indirect_shape(self, tmp_path):
        """The two-line variant is the same bug with a temporary name."""
        assert self._count(tmp_path, (
            'def view():\n'
            '    uid = get_jwt_identity()\n'
            '    return User.query.get(uid)\n'
        )) == 1

    def test_counts_a_coerced_identity(self, tmp_path):
        assert self._count(tmp_path, (
            'def view():\n'
            '    uid = get_jwt_identity()\n'
            '    return User.query.get(int(uid))\n'
        )) == 1

    def test_does_not_count_the_door_itself(self, tmp_path):
        """get_current_user() is the fix, not an instance of the problem."""
        assert self._count(tmp_path, (
            'def view():\n'
            '    return get_current_user()\n'
        )) == 0

    def test_does_not_count_a_lookup_by_an_unrelated_id(self, tmp_path):
        """Loading some *other* user is not an identity lookup."""
        assert self._count(tmp_path, (
            'def view(target_id):\n'
            '    return User.query.get(target_id)\n'
        )) == 0

    def test_does_not_count_the_identity_used_as_a_value(self, tmp_path):
        """Comparing or logging the id never touches the API-key path."""
        assert self._count(tmp_path, (
            'def view(app):\n'
            '    return app.user_id == get_jwt_identity()\n'
        )) == 0

    def test_does_not_count_a_lookup_on_another_model(self, tmp_path):
        assert self._count(tmp_path, (
            'def view():\n'
            '    return Server.query.get(get_jwt_identity())\n'
        )) == 0
