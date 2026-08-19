"""Plan 77 B4 ratchet: models parse JSON through ONE door.

Every hand-rolled ``json.loads`` in a model file is a bypass of
``JsonColumnMixin._json_read`` — a place where a corrupt row raises and
500s every endpoint that serializes the model instead of degrading to the
accessor's default. Plan 77 B4 converted the last of them; this ratchet
keeps the count at zero. If this test fails, use ``self._json_read(...)``
(inherit ``JsonColumnMixin`` first in the bases) instead of ``json.loads``.
"""

from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parents[1] / 'app' / 'models'

# The mixin is the one place allowed to call json.loads.
ALLOWED = {'json_column_mixin.py'}


def test_no_model_file_hand_rolls_json_loads():
    offenders = {}
    for path in sorted(MODELS_DIR.glob('*.py')):
        if path.name in ALLOWED:
            continue
        lines = [
            f'{path.name}:{lineno}'
            for lineno, line in enumerate(
                path.read_text(encoding='utf-8').splitlines(), start=1
            )
            if 'json.loads(' in line
        ]
        if lines:
            offenders[path.name] = lines
    assert not offenders, (
        'json.loads( in model files outside json_column_mixin.py — '
        f'use self._json_read instead: {offenders}'
    )
