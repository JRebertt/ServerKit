"""JSON-file config persistence — one door for the load-or-default /
dump-or-error mechanics (plan 75 §F4).

Five services shipped byte-identical ``save_config`` copies and seven more the
same ``get_config`` skeleton, each a place a fix (an atomic write, a better
error) would have had to land N times. These two helpers own the mechanics;
the per-service parts stay per-service: the path, the default, and any extra
behaviour around the write (cache invalidation, secret merging — those keep
their own methods and may call these helpers inside).

Deliberate parity with the copies they replace: plain ``open(..., 'w')``, no
locking, no atomic rename — none of the originals had them, and adding them
here would be a behaviour change smuggled in with a consolidation. If atomic
writes are ever wanted, they land here, once.
"""
import json
import os


def load_json_config(path, default):
    """JSON file → dict; *default* on missing or corrupt.

    A corrupt config reads as the default, never raises — the same contract
    the hand-rolled copies had, and the one callers rely on at boot.
    """
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            pass
    return default


def save_json_config(path, config):
    """dict → JSON file (indented), creating the parent dir. Returns the
    service-dict shape every caller already returns."""
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w') as f:
            json.dump(config, f, indent=2)
        return {'success': True, 'message': 'Configuration saved'}
    except Exception as e:  # noqa: BLE001
        return {'success': False, 'error': str(e)}
