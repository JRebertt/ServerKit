#!/usr/bin/env python3
"""Test-count ratchet — the guard the 2026-07 data loss taught us to want.

Back then code and its proving tests died TOGETHER, so the suite stayed green
(2572 -> 2209 passing) while whole features silently vanished — nobody diffs a
green number. This checks the collected-test count against a checked-in floor
(``backend/tests/BASELINE_COUNT``) and FAILS if collection has dropped below it.

- Raising the floor is expected as tests are added — run with ``--update`` to
  bump ``BASELINE_COUNT`` to the current count (or just edit the file).
- Lowering it requires editing ``BASELINE_COUNT`` in the same commit — an
  explicit, reviewable statement that tests were intentionally removed, instead
  of a silent regression.
- Collection runs with ``SERVERKIT_CLEAN_COLLECT=1`` so the number is the one a
  CLEAN CHECKOUT collects. A dev box carries gitignored extension copies that
  add parametrised cases CI can never see; ``--update`` used to bake those into
  the floor and leave the ratchet permanently red.

Usage:
    python tests/check_test_count.py           # verify (CI mode) — exit 1 if below
    python tests/check_test_count.py --update   # write current count as the new floor

Run from the ``backend/`` directory.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE_FILE = os.path.join(HERE, 'BASELINE_COUNT')


def read_baseline():
    try:
        with open(BASELINE_FILE) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def collect_count():
    """Return the number of tests pytest collects, without running them."""
    # Scoped to tests/ on purpose: a bare collect from backend/ also walks
    # whatever this machine has lying around (dev-data/, sibling checkouts),
    # which is how the floor was once --update'd ~282 items above anything a
    # clean checkout can collect, turning the ratchet permanently red.
    # SERVERKIT_CLEAN_COLLECT makes the count machine-independent: the only
    # module whose parametrisation varies with what is on disk
    # (test_builtin_extension_drift.py, which pairs builtin-extensions/<ext>
    # against the mostly-gitignored live copies under app/plugins/) restricts
    # itself to git-TRACKED copies when it is set. Without it, --update on a dev
    # box wrote a floor no clean checkout could reach -- 4431 -> 4417, and again
    # 4530 -> 4516, both times 14 cases from four gitignored extensions.
    env = dict(os.environ, SERVERKIT_CLEAN_COLLECT='1')
    proc = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests', '--collect-only', '-q',
         '-p', 'no:cacheprovider'],
        cwd=os.path.dirname(HERE),  # backend/
        capture_output=True, text=True, env=env,
    )
    out = proc.stdout + proc.stderr
    if proc.returncode != 0:
        # Collection errors silently DEFLATE the count — an import-broken
        # test module must fail the guard, not shrink the number it reports.
        sys.stderr.write(f'pytest collection exited {proc.returncode}; '
                         'refusing to trust a partial count.\n')
        sys.stderr.write(out[-2000:] + '\n')
        sys.exit(2)
    # pytest prints e.g. "2475 tests collected in 6.55s" (or "1 test collected")
    m = re.search(r'(\d+)\s+tests?\s+collected', out)
    if not m:
        sys.stderr.write('Could not parse a collected-test count from pytest.\n')
        sys.stderr.write(out[-2000:] + '\n')
        sys.exit(2)
    return int(m.group(1))


def main():
    update = '--update' in sys.argv[1:]
    collected = collect_count()
    baseline = read_baseline()

    if update:
        with open(BASELINE_FILE, 'w') as f:
            f.write(f'{collected}\n')
        print(f'BASELINE_COUNT updated: {baseline} -> {collected}')
        return 0

    print(f'collected={collected}  baseline={baseline}')
    if collected < baseline:
        sys.stderr.write(
            f'\nTEST-COUNT RATCHET FAILED: collected {collected} tests, but the '
            f'floor is {baseline}.\n'
            'Tests disappeared. If this is an intentional removal, lower '
            f'{os.path.relpath(BASELINE_FILE)} in THIS commit; otherwise a '
            'feature (and its proving tests) went missing — investigate before '
            'merging.\n')
        return 1
    if collected > baseline:
        print(f'note: {collected - baseline} new test(s) since the floor was '
              'set — run this with --update to raise BASELINE_COUNT.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
