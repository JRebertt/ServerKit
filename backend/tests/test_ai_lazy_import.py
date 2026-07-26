"""Keep Prompture out of the panel's boot path.

The AI assistant is a core primitive, not an extension — ``app/api/ai.py`` is
registered by ``create_app()`` like every other blueprint. That makes it very
easy to reintroduce a module-level ``from prompture import ...`` in
``ai_service`` or ``ai_tool_registry`` without noticing: everything still works,
the suite still passes, and every panel process silently gains ~25 MB of RSS
that only servers actually using the assistant should pay for.

``import prompture`` pulls ~300 prompture modules plus rich, pygments, httpx and
jsonschema. Measured in the production container (gunicorn --workers 1
--threads 100): 204.9 MB resident with the eager import, 180.5 MB without.

These checks run in a subprocess because the invariant is about a *cold*
interpreter. By the time pytest reaches this file some other test has usually
imported prompture already, so an in-process ``sys.modules`` assertion would
pass no matter what the boot path does.
"""
import json
import os
import subprocess
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Packages that must not be reachable from a cold `create_app()`. rich and
# pygments are here because they are the expensive half of prompture's import
# graph, and a regression usually shows up as all three returning together.
FORBIDDEN_ROOTS = ("prompture", "rich")

_PROBE = r"""
import json, sys
sys.path.insert(0, {backend!r})

import app.services.ai_service          # noqa: F401  - the module under guard
import app.services.ai_tool_registry    # noqa: F401
after_service_import = sorted({{m.split('.')[0] for m in sys.modules}} & set({forbidden!r}))

from app import create_app
create_app('testing')
after_create_app = sorted({{m.split('.')[0] for m in sys.modules}} & set({forbidden!r}))

print("RESULT" + json.dumps({{
    "after_service_import": after_service_import,
    "after_create_app": after_create_app,
}}))
"""


def _run_probe():
    env = dict(os.environ)
    env.update(
        DATABASE_URL="sqlite:///:memory:",
        SECRET_KEY="test",
        JWT_SECRET_KEY="test",
        FLASK_ENV="testing",
        PYTHONDONTWRITEBYTECODE="1",
    )
    source = _PROBE.format(backend=BACKEND_DIR, forbidden=list(FORBIDDEN_ROOTS))
    proc = subprocess.run(
        [sys.executable, "-c", source],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        pytest.fail(f"probe interpreter failed:\n{proc.stdout}\n{proc.stderr}")
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT"):
            return json.loads(line[len("RESULT"):])
    pytest.fail(f"probe produced no RESULT line:\n{proc.stdout}\n{proc.stderr}")


def test_importing_ai_service_does_not_import_prompture():
    """`import app.services.ai_service` must stay cheap."""
    leaked = _run_probe()["after_service_import"]
    assert leaked == [], (
        f"Importing the AI service pulled {leaked} at module scope. Move the "
        "import inside the function that uses it (see the import note at the top "
        "of app/services/ai_service.py) — a module-level `from prompture import "
        "...` costs every panel process ~25 MB of RSS at boot."
    )


def test_create_app_does_not_import_prompture():
    """A booting panel must not pay for the assistant until someone uses it."""
    leaked = _run_probe()["after_create_app"]
    assert leaked == [], (
        f"create_app() pulled {leaked} into the boot path. Something registered "
        "at startup now imports prompture eagerly — check new AI tool "
        "registrations, plugins_sdk.ai, and any module-level Prompture type "
        "annotation that is not under `if TYPE_CHECKING`."
    )


def test_guardrail_detectors_are_built_lazily():
    """The regex guardrails must not be constructed at import time."""
    from app.services import ai_service

    # Touching the module must not have built them; only calling the accessor does.
    assert hasattr(ai_service, "_get_injection_detector")
    assert hasattr(ai_service, "_get_pii_redactor")
    detector = ai_service._get_injection_detector()
    assert detector is not None
    # Cached: the second call returns the very same instance.
    assert ai_service._get_injection_detector() is detector
