"""Tests of the index submission checker (#197, ADR-0021).

Offline throughout: :class:`FakeFetcher` stands in for the network, so these
tests never touch the real GitHub. Covers the acceptance criterion directly:
a valid submission is green, and a wrong checksum, a missing license and a
mismatching manifest are each red with their own named cause.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from validate_submission import Problem, check_entry, check_index  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.marketplace_index import validate_index  # noqa: E402


def _zip_bytes(manifest: dict) -> bytes:
    """A minimal Bundle Zip that satisfies ``localbib-addon check``: the
    Manifest, its package's ``__init__.py``, one script and one locale file
    per declared language."""
    addon_id = manifest["id"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("plugin.json", json.dumps(manifest))
        zf.writestr(f"{addon_id}/__init__.py", "")
        zf.writestr(f"frontend/{addon_id}.js", "// demo\n")
        for lang in manifest["languages"]:
            zf.writestr(f"frontend/locales/{lang}.json", json.dumps({f"{addon_id}.nav.label": "Demo"}))
    return buf.getvalue()


def _manifest(**overrides) -> dict:
    addon_id = overrides.get("id", "demo")
    base = {
        "id": addon_id, "name": "Demo", "version": "1.0.0", "author": "A",
        "license": "MIT", "tagline": "t", "description": "d",
        "languages": ["en"], "default_language": "en",
        "api_version": 2, "min_core": "0.8.0", "python": "any",
        "permissions": [],
        "frontend": {"script": f"frontend/{addon_id}.js", "locales": {"en": "frontend/locales/en.json"}},
    }
    base.update(overrides)
    return base


ARTIFACT_URL = "https://github.com/example/localbib-demo/releases/download/v1.0.0/demo-1.0.0.zip"
HOMEPAGE = "https://github.com/example/localbib-demo"
GOOD_ZIP = _zip_bytes(_manifest())
GOOD_SHA = hashlib.sha256(GOOD_ZIP).hexdigest()


def _entry(**overrides) -> dict:
    base = {
        "id": "demo", "name": "Demo", "tagline": "t", "description": "d",
        "author": "A", "license": "MIT", "homepage": HOMEPAGE, "trust": "third-party",
        "languages": ["en"], "tags": [], "icon": "assets/demo/icon.png", "screenshots": [],
        "versions": [{
            "version": "1.0.0", "api_version": 2, "min_core": "0.8.0",
            "released": "2026-09-25", "changelog": "x", "requires_source": False,
            "permissions": [],
            "artifacts": [{"python": "any", "url": ARTIFACT_URL, "size": len(GOOD_ZIP), "sha256": GOOD_SHA}],
        }],
    }
    base.update(overrides)
    return base


def _index(*entries: dict) -> dict:
    return {"updated": "2026-09-25T00:00:00Z", "addons": list(entries)}


class FakeFetcher:
    def __init__(self, artifacts: dict[str, bytes], reachable: set[str]) -> None:
        self._artifacts = artifacts
        self._reachable = reachable

    def url_ok(self, url: str) -> bool:
        return url in self._reachable

    def get(self, url: str) -> bytes:
        return self._artifacts[url]


GOOD_FETCHER = FakeFetcher({ARTIFACT_URL: GOOD_ZIP}, {ARTIFACT_URL, HOMEPAGE})


# ---------------------------------------------------------------------------
# Acceptance: a valid submission is green
# ---------------------------------------------------------------------------

def test_a_valid_submission_is_green():
    assert check_index(_index(_entry()), GOOD_FETCHER) == []


def test_check_entry_alone_is_also_green():
    assert check_entry(_entry(), GOOD_FETCHER) == []


def test_an_announced_entry_without_a_version_is_green():
    """Texts and images first, the first release later (the release button
    adds a version to an existing entry): only the source repo is checked."""
    assert check_index(_index(_entry(versions=[])), GOOD_FETCHER) == []
    assert [p.kind for p in check_index(_index(_entry(versions=[])), FakeFetcher({}, set()))] == ["homepage"]


def test_a_native_bundle_with_a_build_tag_is_green():
    """A Bundle with a vendored stack names the interpreter it was built for."""
    native = _zip_bytes(_manifest(python="cp313-win_amd64"))
    entry = _entry()
    entry["versions"][0]["artifacts"] = [{"python": "cp313-win_amd64", "url": ARTIFACT_URL,
                                          "size": len(native), "sha256": hashlib.sha256(native).hexdigest()}]
    fetcher = FakeFetcher({ARTIFACT_URL: native}, {ARTIFACT_URL, HOMEPAGE})
    assert check_index(_index(entry), fetcher) == []


# ---------------------------------------------------------------------------
# Acceptance: each failure is red with a named cause
# ---------------------------------------------------------------------------

def test_a_wrong_checksum_is_refused_by_name():
    bad_entry = _entry()
    bad_entry["versions"][0]["artifacts"][0]["sha256"] = "f" * 64
    problems = check_index(_index(bad_entry), GOOD_FETCHER)
    assert [p.kind for p in problems] == ["checksum"]
    assert "does not match" in problems[0].detail


def test_a_missing_license_is_refused_by_the_reused_schema_check():
    bad_entry = _entry(license="")
    problems = check_index(_index(bad_entry), GOOD_FETCHER)
    assert [p.kind for p in problems] == ["schema"]
    assert "license" in problems[0].detail
    # Not a reimplementation: the exact message the core's own check produces.
    assert problems[0].detail in validate_index(_index(bad_entry))


def test_a_mismatching_manifest_is_refused_by_name():
    other_zip = _zip_bytes(_manifest(id="other"))
    other_sha = hashlib.sha256(other_zip).hexdigest()
    entry = _entry()
    entry["versions"][0]["artifacts"][0]["sha256"] = other_sha
    fetcher = FakeFetcher({ARTIFACT_URL: other_zip}, {ARTIFACT_URL, HOMEPAGE})

    problems = check_index(_index(entry), fetcher)
    assert [p.kind for p in problems] == ["manifest"]
    assert "id='other'" in problems[0].detail


def test_an_artifact_whose_build_tag_differs_from_its_manifest_is_refused():
    """The core picks an artifact by its ``python`` and then loads the Zip's
    Manifest: a native Bundle listed as ``any`` would be offered to every core
    and turn up incompatible after the download."""
    native = _zip_bytes(_manifest(python="cp313-win_amd64"))
    entry = _entry()
    entry["versions"][0]["artifacts"] = [{"python": "any", "url": ARTIFACT_URL,
                                          "size": len(native), "sha256": hashlib.sha256(native).hexdigest()}]
    fetcher = FakeFetcher({ARTIFACT_URL: native}, {ARTIFACT_URL, HOMEPAGE})

    problems = check_index(_index(entry), fetcher)
    assert [p.kind for p in problems] == ["manifest"]
    assert "python='cp313-win_amd64'" in problems[0].detail


def test_an_unreachable_artifact_is_refused_by_name():
    fetcher = FakeFetcher({}, {HOMEPAGE})
    problems = check_index(_index(_entry()), fetcher)
    assert [p.kind for p in problems] == ["artifact-url"]


def test_an_unlinked_source_repo_is_refused_by_name():
    problems = check_entry(_entry(homepage=""), GOOD_FETCHER)
    assert [p.kind for p in problems] == ["homepage"]


def test_an_unreachable_source_repo_is_refused_by_name():
    fetcher = FakeFetcher({ARTIFACT_URL: GOOD_ZIP}, {ARTIFACT_URL})  # homepage missing from reachable
    problems = check_entry(_entry(), fetcher)
    assert [p.kind for p in problems] == ["homepage"]


def test_a_bundle_that_fails_the_addon_check_is_refused_by_name():
    problems = check_entry(_entry(), GOOD_FETCHER, run_addon_check=lambda path: ["structure: missing frontend/"])
    assert [p.kind for p in problems] == ["addon-check"]
    assert problems[0].detail == "structure: missing frontend/"


def test_a_problem_prints_with_addon_and_version():
    problem = Problem("demo", "1.0.0", "checksum", "boom")
    assert str(problem) == "demo@1.0.0: [checksum] boom"
    assert str(Problem("", "", "schema", "boom")) == "index: [schema] boom"


def test_the_cli_reports_and_exits_nonzero(tmp_path, monkeypatch):
    import validate_submission as vs

    bad_entry = _entry()
    bad_entry["versions"][0]["artifacts"][0]["sha256"] = "f" * 64
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(_index(bad_entry)), encoding="utf-8")
    monkeypatch.setattr(vs, "UrllibFetcher", lambda: GOOD_FETCHER)

    assert vs.main([str(index_path)]) == 1


def test_the_cli_succeeds_on_a_clean_index(tmp_path, monkeypatch):
    import validate_submission as vs

    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(_index(_entry())), encoding="utf-8")
    monkeypatch.setattr(vs, "UrllibFetcher", lambda: GOOD_FETCHER)

    assert vs.main([str(index_path)]) == 0
