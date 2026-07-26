"""Guard the Dockerfile's botocore prune against drift.

The production image deletes botocore's bundled API models for every AWS service
except a small whitelist (``ARG BOTOCORE_KEEP`` in the root ``Dockerfile``),
because botocore ships models for 400+ services and ServerKit talks to three.

That prune is invisible from Python: a ``boto3.client('sns')`` added later works
perfectly in dev (where the full botocore is installed) and raises
``UnknownServiceError`` only in the built image, at the moment a user triggers
the feature. This test closes that gap by parsing both sides and asserting they
agree — no network, no AWS credentials, no Docker.

If this fails, add the service to ``BOTOCORE_KEEP`` in the Dockerfile.
"""
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCKERFILE = os.path.join(REPO_ROOT, "Dockerfile")
APP_DIR = os.path.join(REPO_ROOT, "backend", "app")

# boto3.client('s3', ...) / boto3.resource("s3") / boto3.Session().client('ses')
_CLIENT_CALL = re.compile(r"""boto3\s*\.\s*(?:client|resource)\s*\(\s*['"]([a-z0-9-]+)['"]""")
_KEEP_ARG = re.compile(r"""^\s*ARG\s+BOTOCORE_KEEP\s*=\s*["']?([^"'\n]+)["']?\s*$""", re.M)


def _whitelisted_services():
    with open(DOCKERFILE, "r", encoding="utf-8") as fh:
        match = _KEEP_ARG.search(fh.read())
    assert match, "Dockerfile no longer declares ARG BOTOCORE_KEEP — did the prune move?"
    return set(match.group(1).split())


def _services_used_in_code():
    used = {}
    for dirpath, dirnames, filenames in os.walk(APP_DIR):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
            for service in _CLIENT_CALL.findall(source):
                used.setdefault(service, []).append(os.path.relpath(path, REPO_ROOT))
    return used


def test_every_boto3_client_survives_the_image_prune():
    """Each boto3 service the code constructs must be kept in the image."""
    kept = _whitelisted_services()
    used = _services_used_in_code()

    missing = {svc: sites for svc, sites in used.items() if svc not in kept}
    assert not missing, (
        "These boto3 services are used in code but their botocore models are "
        "deleted from the production image, so they will raise UnknownServiceError "
        "at runtime. Add them to ARG BOTOCORE_KEEP in the Dockerfile:\n"
        + "\n".join(f"  - {svc!r} used in {', '.join(sorted(set(sites)))}" for svc, sites in sorted(missing.items()))
    )


def test_whitelist_is_not_silently_over_broad():
    """The whitelist should stay close to what the code actually needs.

    ``sts`` is intentionally kept without a direct ``boto3.client('sts')`` call —
    botocore resolves it while signing requests. Anything else unused is dead
    weight that should be dropped rather than carried forever.
    """
    kept = _whitelisted_services()
    used = set(_services_used_in_code())
    implicit = {"sts"}

    unexplained = kept - used - implicit
    assert not unexplained, (
        "ARG BOTOCORE_KEEP lists services no boto3 call site uses: "
        f"{sorted(unexplained)}. Drop them from the Dockerfile, or note here why "
        "botocore needs them implicitly."
    )
