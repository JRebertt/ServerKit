"""One implementation of the JSON-in-a-Text-column accessor pattern (plan 75 §F2).

Dozens of models hand-roll the same pair over a ``db.Text`` column:

    def get_details(self):
        if self.details:
            try:
                return json.loads(self.details)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

Every hand-rolled copy is a place a fix has to be made N times — the exact
duplication this plan exists to remove. Models opt in by inheriting the mixin
and delegating:

    class AuditLog(JsonColumnMixin, db.Model):
        def get_details(self):
            return self._json_read('details')

The per-model parts stay per-model: the accessor's *name* (``get_details`` vs
``get_metadata``), the *column* it reads, and its *default*. What is
consolidated is only the mechanics — empty-is-default, corrupt-is-default,
optional shape check, falsy-on-write.

Corrupt JSON reads as the default, never raises: a hand-edited or
partially-written row must not 500 every endpoint that serializes the model.
This is the dominant in-tree convention; the handful of models that let
``json.loads`` raise on corrupt data are deliberately NOT converted (that
would be a behaviour change, not a consolidation).
"""
import json

_UNSET = object()


class JsonColumnMixin:
    """Helpers for models storing JSON in Text columns. See module docstring."""

    def _json_read(self, column, default=_UNSET, expect=None):
        """Parsed JSON from *column*, or *default* (``{}`` when omitted) when
        the column is empty, unparseable, or — when *expect* is given — valid
        JSON of the wrong shape (a corrupt ``[]`` where a mapping belongs)."""
        fallback = {} if default is _UNSET else default
        raw = getattr(self, column)
        if not raw:
            return fallback
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return fallback
        if expect is not None and not isinstance(value, expect):
            return fallback
        return value

    def _json_write(self, column, value, falsy=None):
        """Serialize *value* into *column*; store *falsy* verbatim when *value*
        is falsy (``None`` → NULL by default, ``'[]'``/``'{}'`` for columns
        whose readers expect a container)."""
        setattr(self, column, json.dumps(value) if value else falsy)
