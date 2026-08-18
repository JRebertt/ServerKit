"""JSON-file config persistence — one door for the load-or-default /
dump-or-error mechanics (plan 75 §F4).

Five services shipped byte-identical ``save_config`` copies and seven more the
same ``get_config`` skeleton, each a place a fix (an atomic write, a better
error) would have had to land N times. These two helpers own the mechanics;
the per-service parts stay per-service: the path, the default, and any extra
behaviour around the write (cache invalidation, secret merging — those keep
their own methods and may call these helpers inside).

The write is atomic (plan 75 §G6). The consolidation that created this module
deliberately kept the copies' plain ``open(..., 'w')`` so that no behaviour
change rode along with it, and noted that atomic writes, if ever wanted, would
land here once. This is that once: a truncating write that dies mid-``json.dump``
— a full disk, a killed process — leaves a truncated file where a config used
to be, and every caller's load path treats a corrupt config as "use the
default". That is a config silently reset to defaults, which is precisely the
class of false fact this plan exists to remove.

``file_integrity_service._save_state`` already used tmp + ``os.replace`` and is
the pattern followed here.
"""
import copy
import json
import os


def load_json_config(path, default):
    """JSON file → dict; *default* on missing or corrupt.

    A corrupt config reads as the default, never raises — the same contract
    the hand-rolled copies had, and the one callers rely on at boot. The
    fallback is a deep copy: callers mutate what they get back, and a shared
    default object would leak those mutations into every later call.
    """
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            pass
    return copy.deepcopy(default)


def save_json_config(path, config):
    """dict → JSON file (indented), creating the parent dir. Returns the
    service-dict shape every caller already returns.

    Written to a sibling temp file and ``os.replace``d into position, so a
    reader never sees a half-written config and a failed write leaves the
    previous one intact. ``os.replace`` is atomic on POSIX and on Windows.
    """
    directory = os.path.dirname(path) or '.'
    tmp = f'{path}.tmp'
    try:
        os.makedirs(directory, exist_ok=True)
        with open(tmp, 'w') as f:
            json.dump(config, f, indent=2)
        os.replace(tmp, path)
        return {'success': True, 'message': 'Configuration saved'}
    except Exception as e:  # noqa: BLE001
        # The old file is still whole; drop the partial temp so a later write
        # is not confused by it. Cleanup failure must not mask the real error.
        try:
            os.remove(tmp)
        except OSError:
            pass
        return {'success': False, 'error': str(e)}
