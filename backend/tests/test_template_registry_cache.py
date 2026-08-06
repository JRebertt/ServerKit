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
    """The cache is class-level state; never leak it between tests."""
    TemplateService.invalidate_remote_cache()
    yield
    TemplateService.invalidate_remote_cache()


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
