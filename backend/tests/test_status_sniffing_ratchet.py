"""The status-sniffing ratchet (plan 76, milestone C).

Second-wave rule 1: the ratchet comes before the migration, because a migration
without one regrows — and here the ratchet comes *well* before, since converging
these means deciding the service/route envelope (milestone C) rather than
editing 23 lines.

What it holds down is the population of HTTP statuses derived by searching an
error message for a phrase. Those are the visible symptom of a service that
returns ``{'success': False, 'error': '<prose>'}``: it knew the failure was a
denial, discarded that, and the route reconstructs it from the sentence — which
couples the status code to the wording, silently.
"""

from status_sniffing_census import census, count_file, read_ceiling, total


def test_the_count_is_at_or_below_the_ceiling():
    found = census()
    count = total(found)
    ceiling = read_ceiling()
    worst = sorted(found, key=lambda p: -len(found[p]))[:5]
    assert count <= ceiling, (
        f'{count} HTTP statuses are chosen by matching an error message, '
        f'ceiling is {ceiling}.\n'
        f'Raise a typed error from app/exceptions.py in the service and let the '
        f'global handler map it, instead of re-deriving the status from prose.\n'
        f'Files: ' + ', '.join(f'{p} ({len(found[p])})' for p in worst)
    )


def test_the_ceiling_is_not_stale():
    count, ceiling = total(), read_ceiling()
    assert ceiling - count <= 5, (
        f'ceiling {ceiling} is {ceiling - count} above the actual {count}; '
        f'run `python tests/status_sniffing_census.py --update`'
    )


class TestTheCensusCountsTheRightThings:
    """A miscounting ratchet is worse than none: it reads green either way."""

    def _count(self, tmp_path, source):
        path = tmp_path / 'sample.py'
        path.write_text(source, encoding='utf-8')
        return len(count_file(str(path)))

    def test_counts_a_substring_test(self, tmp_path):
        assert self._count(tmp_path, (
            "status = 403 if 'denied' in result.get('error', '').lower() else 400\n"
        )) == 1

    def test_counts_a_startswith_test(self, tmp_path):
        assert self._count(tmp_path, (
            "code = 404 if err.startswith('not found') else 400\n"
        )) == 1

    def test_counts_a_key_presence_test(self, tmp_path):
        """`'error' not in result` is the same coupling one step removed."""
        assert self._count(tmp_path, (
            "return jsonify(result), 200 if 'error' not in result else 400\n"
        )) == 1

    def test_does_not_count_a_status_chosen_from_a_real_signal(self, tmp_path):
        assert self._count(tmp_path, (
            'status = 403 if denied else 400\n'
            'other = 404 if result.missing else 200\n'
        )) == 0

    def test_does_not_count_a_non_status_conditional(self, tmp_path):
        """Only the pair-of-status-codes shape is the smell."""
        assert self._count(tmp_path, (
            "label = 'gone' if 'not found' in err else 'broken'\n"
            "limit = 10 if 'small' in mode else 50\n"
        )) == 0

    def test_does_not_count_a_typed_exception_mapping(self, tmp_path):
        """What the migration is supposed to produce must not read as debt."""
        assert self._count(tmp_path, (
            'def handler(exc):\n'
            '    return exc.status_code\n'
        )) == 0
