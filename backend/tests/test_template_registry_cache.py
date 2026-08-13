"""Proving tests for the template catalog's dedupe + remote-index cache.

Two bugs motivated these, both only latent while ``DEFAULT_REPOS`` pointed at a
404:

1. ``list_all_templates()`` concatenated local + remote with no id merge, so
   every bundled template appeared TWICE the moment a real registry answered
   (measured: 106 bundled + 106 remote = 213 entries for 107 unique ids).
2. It called ``fetch_remote_templates()`` inline on EVERY listing with a 30s
   timeout and no memoization, so one unreachable repo stalled the Templates
   page on every render.
"""
import os

import pytest

from app.services.template_service import TemplateService

REPO_URL = "https://example.test/templates"

# Ids that really are bundled in backend/templates/, so the dedupe test
# exercises a genuine local-vs-remote collision rather than a synthetic one.
BUNDLED_IDS = ["ollama-webui", "litellm"]


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clean_cache():
    """Both caches are class-level state; never leak them between tests."""
    TemplateService.invalidate_remote_cache()
    TemplateService.invalidate_local_cache()
    yield
    TemplateService.invalidate_remote_cache()
    TemplateService.invalidate_local_cache()


@pytest.fixture
def one_repo(monkeypatch):
    """Pin the repo list so these tests never read the operator's config."""
    monkeypatch.setattr(
        TemplateService, "get_config",
        classmethod(lambda cls: {"repos": [{"name": "t", "url": REPO_URL,
                                            "enabled": True}]}),
    )


def _serve(monkeypatch, payload=None, fail=False):
    """Install a fake requests.get and return its call counter."""
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if fail:
            raise RuntimeError("connection refused")
        return _FakeResponse(payload or {"templates": []})

    monkeypatch.setattr("app.services.template_service.requests.get", fake_get)
    return calls


def _index(*ids):
    return {"templates": [{"id": i, "name": i, "categories": []} for i in ids]}


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------
def test_bundled_template_is_not_listed_twice(monkeypatch, one_repo):
    """A repo serving ids that are also bundled must not double the catalog."""
    _serve(monkeypatch, _index(*BUNDLED_IDS))

    listed = TemplateService.list_all_templates()
    ids = [t["id"] for t in listed]

    assert len(ids) == len(set(ids)), "catalog contains duplicate ids"
    for bundled in BUNDLED_IDS:
        assert ids.count(bundled) == 1


def test_local_entry_wins_over_remote(monkeypatch, one_repo):
    """Local outranks every repo, matching get_template()'s resolution order."""
    _serve(monkeypatch, _index(*BUNDLED_IDS))

    by_id = {t["id"]: t for t in TemplateService.list_all_templates()}

    for bundled in BUNDLED_IDS:
        assert by_id[bundled]["source"] == "local"


def test_remote_only_template_is_still_listed(monkeypatch, one_repo):
    """Dedupe must not swallow ids the bundle does not carry."""
    _serve(monkeypatch, _index("not-a-bundled-template"))

    by_id = {t["id"]: t for t in TemplateService.list_all_templates()}

    assert by_id["not-a-bundled-template"]["source"] == "remote"


def test_first_enabled_repo_wins_among_remotes(monkeypatch):
    """Two repos claiming one id: the earlier repo keeps it."""
    monkeypatch.setattr(
        TemplateService, "get_config",
        classmethod(lambda cls: {"repos": [
            {"name": "a", "url": "https://a.test/t", "enabled": True},
            {"name": "b", "url": "https://b.test/t", "enabled": True},
        ]}),
    )

    def fake_get(url, **kwargs):
        return _FakeResponse(_index("shared-id"))

    monkeypatch.setattr("app.services.template_service.requests.get", fake_get)

    by_id = {t["id"]: t for t in TemplateService.list_all_templates()}
    assert by_id["shared-id"]["repo_url"] == "https://a.test/t"


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------
def test_remote_index_fetched_once_across_listings(monkeypatch, one_repo):
    """Rendering the catalog twice must not hit the network twice."""
    calls = _serve(monkeypatch, _index("remote-a"))

    TemplateService.list_all_templates()
    TemplateService.list_all_templates()
    TemplateService.list_all_templates()

    assert len(calls) == 1


def test_dead_repo_is_not_refetched_on_every_listing(monkeypatch, one_repo):
    """The original bug: a 404 repo cost a request (and a timeout) per render."""
    calls = _serve(monkeypatch, fail=True)

    for _ in range(5):
        TemplateService.list_all_templates()

    assert len(calls) == 1


def test_failure_serves_last_good_index_repeatedly(monkeypatch, one_repo):
    """A transient failure must not blank a catalog the panel already showed --
    and the SECOND failure must still serve it, not decay to empty."""
    monkeypatch.setattr(TemplateService, "_REMOTE_TTL_SECONDS", 0)
    monkeypatch.setattr(TemplateService, "_REMOTE_ERROR_TTL_SECONDS", 0)

    _serve(monkeypatch, _index("remote-a"))
    assert TemplateService.fetch_remote_templates(REPO_URL)[0]["id"] == "remote-a"

    _serve(monkeypatch, fail=True)
    for attempt in range(3):
        served = TemplateService.fetch_remote_templates(REPO_URL)
        assert [t["id"] for t in served] == ["remote-a"], f"lost on attempt {attempt}"


def test_failure_with_no_last_good_returns_empty(monkeypatch, one_repo):
    """No prior success means an honest empty list, not an exception."""
    _serve(monkeypatch, fail=True)
    assert TemplateService.fetch_remote_templates(REPO_URL) == []


def test_force_bypasses_the_cache(monkeypatch, one_repo):
    """An explicit sync must see current data, not a cached index."""
    calls = _serve(monkeypatch, _index("remote-a"))

    TemplateService.fetch_remote_templates(REPO_URL)
    TemplateService.fetch_remote_templates(REPO_URL, force=True)

    assert len(calls) == 2


def test_saving_config_invalidates_the_cache(monkeypatch, one_repo, tmp_path):
    """Adding or removing a repo must take effect on the next listing, not
    after the TTL. save_config is the choke point for every repo mutation."""
    calls = _serve(monkeypatch, _index("remote-a"))
    monkeypatch.setattr(TemplateService, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(TemplateService, "TEMPLATE_CONFIG",
                        str(tmp_path / "templates.json"))

    TemplateService.list_all_templates()
    assert len(calls) == 1

    TemplateService.save_config({"repos": [], "installed": {}})

    TemplateService.list_all_templates()
    assert len(calls) == 2


def test_cached_entries_are_copies(monkeypatch, one_repo):
    """A caller mutating a returned entry must not corrupt the cache."""
    _serve(monkeypatch, _index("remote-a"))

    first = TemplateService.fetch_remote_templates(REPO_URL)
    first[0]["name"] = "mutated"

    second = TemplateService.fetch_remote_templates(REPO_URL)
    assert second[0]["name"] == "remote-a"


# ---------------------------------------------------------------------------
# Local parse cache
#
# With the remote fetch memoized, re-parsing every bundled YAML on every call
# became the whole cost of a Templates page load (118 files, ~0.4s).
# ---------------------------------------------------------------------------
MINIMAL = """\
name: {name}
version: "1.0"
description: A fixture template
categories:
  - test
compose:
  services:
    app:
      image: nginx:alpine
"""


@pytest.fixture
def template_dirs(monkeypatch, tmp_path):
    """Point both template directories at a temp tree.

    ``TEMPLATES_DIR`` is the primary (synced/user) directory and
    ``LOCAL_TEMPLATES_DIR`` the bundled fallback -- the same precedence
    ``list_local_templates`` walks in production."""
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"
    primary.mkdir()
    fallback.mkdir()
    monkeypatch.setattr(TemplateService, "TEMPLATES_DIR", str(primary))
    monkeypatch.setattr(TemplateService, "LOCAL_TEMPLATES_DIR", str(fallback))
    TemplateService.invalidate_local_cache()
    return primary, fallback


@pytest.fixture
def parse_calls(monkeypatch):
    """Record every real parse so the tests assert on work done, not wall time."""
    calls = []
    original = TemplateService.parse_template

    def counting(template_path):
        calls.append(template_path)
        return original(template_path)

    monkeypatch.setattr(TemplateService, "parse_template", staticmethod(counting))
    return calls


def test_repeat_listing_does_not_reparse(template_dirs, parse_calls):
    """The bug: every catalog render re-read and re-parsed the whole bundle."""
    primary, _ = template_dirs
    for i in range(3):
        (primary / f"t{i}.yaml").write_text(MINIMAL.format(name=f"T{i}"))

    assert len(TemplateService.list_local_templates()) == 3
    assert len(parse_calls) == 3

    TemplateService.list_local_templates()
    TemplateService.list_local_templates()

    assert len(parse_calls) == 3, "repeat listing re-parsed unchanged files"


def test_editing_one_template_reparses_only_that_file(template_dirs, parse_calls):
    """Per-file keying: a sync that rewrites one template costs one parse."""
    primary, _ = template_dirs
    for i in range(3):
        (primary / f"t{i}.yaml").write_text(MINIMAL.format(name=f"T{i}"))
    TemplateService.list_local_templates()
    parse_calls.clear()

    # Changes both mtime and size, so this holds even on a filesystem with
    # coarse mtime granularity.
    (primary / "t1.yaml").write_text(MINIMAL.format(name="Renamed") + "\n# edited\n")

    listed = {t["id"]: t for t in TemplateService.list_local_templates()}

    assert [os.path.basename(p) for p in parse_calls] == ["t1.yaml"]
    assert listed["t1"]["name"] == "Renamed"
    assert listed["t0"]["name"] == "T0"


def test_deleted_template_disappears_and_is_pruned(template_dirs):
    """A removed file leaves the catalog and does not linger in the cache."""
    primary, _ = template_dirs
    path = primary / "gone.yaml"
    path.write_text(MINIMAL.format(name="Gone"))

    assert [t["id"] for t in TemplateService.list_local_templates()] == ["gone"]
    assert str(path) in TemplateService._local_cache

    path.unlink()

    assert TemplateService.list_local_templates() == []
    assert str(path) not in TemplateService._local_cache


def test_unparseable_template_is_not_retried_until_it_changes(template_dirs, parse_calls):
    """One malformed YAML must not cost a parse on every single render."""
    primary, _ = template_dirs
    broken = primary / "broken.yaml"
    broken.write_text("name: [unclosed\n")

    assert TemplateService.list_local_templates() == []
    assert len(parse_calls) == 1

    TemplateService.list_local_templates()
    TemplateService.list_local_templates()
    assert len(parse_calls) == 1, "malformed template re-parsed on every listing"

    broken.write_text(MINIMAL.format(name="Fixed"))

    assert [t["id"] for t in TemplateService.list_local_templates()] == ["broken"]
    assert len(parse_calls) == 2


def test_unparseable_primary_does_not_block_the_fallback(template_dirs):
    """A file that fails to parse must not claim its id, so a valid file of the
    same name in the fallback directory still supplies it."""
    primary, fallback = template_dirs
    (primary / "dup.yaml").write_text("name: [unclosed\n")
    (fallback / "dup.yaml").write_text(MINIMAL.format(name="FromFallback"))

    assert [t["name"] for t in TemplateService.list_local_templates()] == ["FromFallback"]


def test_primary_directory_wins_over_fallback(template_dirs):
    """Precedence is unchanged by caching: the primary directory shadows the bundle."""
    primary, fallback = template_dirs
    (primary / "dup.yaml").write_text(MINIMAL.format(name="FromPrimary"))
    (fallback / "dup.yaml").write_text(MINIMAL.format(name="FromFallback"))

    listed = TemplateService.list_local_templates()

    assert len(listed) == 1
    assert listed[0]["name"] == "FromPrimary"


def test_local_entries_are_copies(template_dirs):
    """A caller mutating an entry -- or its nested categories list -- must not
    corrupt the cache."""
    primary, _ = template_dirs
    (primary / "c.yaml").write_text(MINIMAL.format(name="C"))

    first = TemplateService.list_local_templates()[0]
    first["categories"].append("mutated")
    first["name"] = "mutated"

    second = TemplateService.list_local_templates()[0]

    assert second["categories"] == ["test"]
    assert second["name"] == "C"
