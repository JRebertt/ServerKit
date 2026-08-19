"""The unreported-crash ratchet (plan 76, milestone B).

Second-wave rule 1: every door gets a ratchet before its migration starts,
because a migration without one regrows. This is milestone B's.

It holds at zero the number of API handlers that tell a caller "this crashed"
(HTTP 500) without the crash reaching the centralized error log. The failure it
prevents is silent: the endpoint still answers, the operator's /monitoring/errors
page just never learns the crash happened.
"""

from unreported_crash_census import census, count_file, read_ceiling, total


def test_the_count_is_at_or_below_the_ceiling():
    found = census()
    count = total(found)
    ceiling = read_ceiling()
    worst = sorted(found, key=lambda p: -len(found[p]))[:5]
    assert count <= ceiling, (
        f'{count} API handler(s) answer 500 without reporting the crash, '
        f'ceiling is {ceiling}.\n'
        f'Return app.error_reporting.unexpected_response(exc) instead of a '
        f'hand-shaped 500 — or call record_unexpected(exc) if the route must '
        f'keep its own caller-facing wording.\n'
        f'Best of all, delete the try/except and let the global 500 handler '
        f'answer.\n'
        f'Files: ' + ', '.join(f'{p} ({len(found[p])})' for p in worst)
    )


def test_the_ceiling_stays_at_zero():
    """This one is not a countdown — it started at 43 and closed in one pass.

    A raised ceiling here means somebody reintroduced an invisible crash, which
    is exactly the regression the ratchet exists to catch.
    """
    assert read_ceiling() == 0, (
        'the unreported-crash ceiling is not 0; this ratchet is not a legacy '
        'baseline to shrink but an invariant to hold'
    )


class TestTheCensusCountsTheRightThings:
    """A miscounting ratchet is worse than none: it reads green either way."""

    def _count(self, tmp_path, source):
        path = tmp_path / 'sample.py'
        path.write_text(source, encoding='utf-8')
        return len(count_file(str(path)))

    def test_counts_a_hand_shaped_500(self, tmp_path):
        assert self._count(tmp_path, (
            'def view():\n'
            '    try:\n'
            '        return work()\n'
            '    except Exception as exc:\n'
            "        return jsonify({'error': str(exc)}), 500\n"
        )) == 1

    def test_counts_a_bare_except(self, tmp_path):
        assert self._count(tmp_path, (
            'def view():\n'
            '    try:\n'
            '        return work()\n'
            '    except:\n'
            "        return jsonify({'error': 'boom'}), 500\n"
        )) == 1

    def test_does_not_count_one_that_goes_through_the_door(self, tmp_path):
        assert self._count(tmp_path, (
            'def view():\n'
            '    try:\n'
            '        return work()\n'
            '    except Exception as exc:\n'
            '        return unexpected_response(exc)\n'
        )) == 0

    def test_does_not_count_one_that_records_and_keeps_its_wording(self, tmp_path):
        """sso.py's shape: an auth failure should not read as a generic crash."""
        assert self._count(tmp_path, (
            'def view():\n'
            '    try:\n'
            '        return work()\n'
            '    except Exception as exc:\n'
            '        record_unexpected(exc)\n'
            "        return jsonify({'error': 'SSO authentication failed'}), 500\n"
        )) == 0

    def test_does_not_count_one_that_re_raises(self, tmp_path):
        """Re-raising reaches the global handler, which reports it."""
        assert self._count(tmp_path, (
            'def view():\n'
            '    try:\n'
            '        return work()\n'
            '    except Exception:\n'
            '        cleanup()\n'
            '        raise\n'
        )) == 0

    def test_does_not_count_a_narrow_except(self, tmp_path):
        """Catching a specific error is a domain decision, not a swallowed crash."""
        assert self._count(tmp_path, (
            'def view():\n'
            '    try:\n'
            '        return work()\n'
            '    except ValueError as exc:\n'
            "        return jsonify({'error': str(exc)}), 500\n"
        )) == 0

    def test_does_not_count_a_non_500_answer(self, tmp_path):
        """A 400/404 is mapping an expected failure, not declaring a crash."""
        assert self._count(tmp_path, (
            'def view():\n'
            '    try:\n'
            '        return work()\n'
            '    except Exception as exc:\n'
            "        return jsonify({'error': str(exc)}), 400\n"
        )) == 0
