"""The hand-shaped-error-body ratchet (plan 76, milestone B closure).

The conversion itself is migrate-when-touched (invariant 9); this ceiling is
what makes that policy real — see ``error_shape_census.py`` for the contract.
"""

from error_shape_census import census, count_file, read_ceiling, total


def test_the_count_is_at_or_below_the_ceiling():
    found = census()
    count = total(found)
    ceiling = read_ceiling()
    worst = sorted(found, key=lambda p: -len(found[p]))[:5]
    assert count <= ceiling, (
        f'{count} hand-shaped error bodies in app/api, ceiling is {ceiling}.\n'
        f'Raise a typed error from app.exceptions instead — the global handler '
        f'owns the body, the status, and the request id.\n'
        f'Heaviest files: ' + ', '.join(f'{p} ({len(found[p])})' for p in worst)
    )


def test_the_ceiling_is_not_stale():
    count, ceiling = total(), read_ceiling()
    assert ceiling - count <= 25, (
        f'ceiling {ceiling} is {ceiling - count} above the actual {count}; '
        f'run `python tests/error_shape_census.py --update`'
    )


class TestTheCensusCountsTheRightThings:
    """A miscounting ratchet is worse than none: it reads green either way."""

    def _count(self, tmp_path, source):
        path = tmp_path / 'sample.py'
        path.write_text(source, encoding='utf-8')
        return len(count_file(str(path)))

    def test_counts_a_jsonified_error_body(self, tmp_path):
        assert self._count(tmp_path, (
            "def handler():\n"
            "    return jsonify({'error': 'nope'}), 404\n"
        )) == 1

    def test_counts_a_bare_dict_error_body(self, tmp_path):
        assert self._count(tmp_path, (
            "def handler():\n"
            "    return {'error': 'nope'}, 400\n"
        )) == 1

    def test_does_not_count_a_success_body(self, tmp_path):
        assert self._count(tmp_path, (
            "def handler():\n"
            "    return jsonify({'success': True, 'data': []}), 200\n"
        )) == 0

    def test_does_not_count_a_typed_raise(self, tmp_path):
        """What the migration produces must not read as debt."""
        assert self._count(tmp_path, (
            "def handler():\n"
            "    raise NotFoundError('nope')\n"
        )) == 0

    def test_does_not_count_a_variable_body(self, tmp_path):
        """`return body, status` where body was built elsewhere is out of
        scope for a syntactic census — the recorder helpers return those."""
        assert self._count(tmp_path, (
            "def handler():\n"
            "    body, status = unexpected_response(exc)\n"
            "    return body, status\n"
        )) == 0
