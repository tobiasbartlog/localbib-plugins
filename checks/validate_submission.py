#!/usr/bin/env python3
"""Validate a Marketplace-Index submission (#197, ADR-0021).

Runs as the CI of the ``localbib-plugins`` repository on every pull request
that touches ``index.json`` (see ``.github/workflows/validate.yml``, added by
the export together with ``marketplace_index.py`` — see the import fallback
below). It checks:

* **Schema** — reuses :func:`marketplace_index.validate_index`, the exact
  function ``services/marketplace`` and the export's own verification hold
  the index to, so this checker never drifts into a looser or stricter shape
  than what the core actually reads.
* **Reachable artifact URL** and **reachable, linked source repository**
  (``homepage``) — the schema does not require either to be *live*, only
  present; this is what makes the difference.
* **Checksum against the asset** — the artifact is downloaded and its SHA-256
  compared against the entry.
* **Manifest inside the Zip against the entry** — the downloaded artifact's
  ``plugin.json`` must declare the same ``id``, ``version`` and ``license``
  the index entry claims, and the ``python`` build tag its artifact is listed
  under.
* **``localbib-addon check`` on the unpacked Bundle** — the same tool an
  author runs locally (``pip install "localbib-plugin-api[dev]"`` gives it).

Every network access goes through an injected :class:`Fetcher`, so the whole
module is testable offline (see ``tests/test_validate_submission.py``): the
tests pass a fake, the CI passes :class:`UrllibFetcher`.

Usage:
    python checks/validate_submission.py [index.json]

Exit codes: 0 clean, 1 at least one problem (named and printed).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

# marketplace_index.py has two lives: a sibling module once the export added
# it next to this file (the real, shipped CI), and scripts/marketplace_index.py
# of the private development repo while this file is still being authored and
# tested there. Both are the exact same file (the export copies it verbatim,
# see scripts/export_targets.py's INDEX_CHECKER_SOURCE) — this is not a
# reimplementation, it is the two places the one file can be found.
_HERE = Path(__file__).resolve().parent
if (_HERE / "marketplace_index.py").is_file():
    sys.path.insert(0, str(_HERE))
    from marketplace_index import validate_index  # type: ignore[import-not-found]
else:
    sys.path.insert(0, str(_HERE.parents[1]))  # marketplace/checks -> marketplace -> repo root
    from scripts.marketplace_index import validate_index  # noqa: E402


class Fetcher(Protocol):
    """What :func:`check_entry` needs from the network — injectable for tests."""

    def url_ok(self, url: str) -> bool: ...

    def get(self, url: str) -> bytes: ...


class UrllibFetcher:
    """The real fetcher: stdlib only, so the index repo's CI needs no extra
    dependency beyond the Add-on Contract itself."""

    def url_ok(self, url: str) -> bool:
        import urllib.request

        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=15) as resp:
                return 200 <= resp.status < 400
        except Exception:
            return False

    def get(self, url: str) -> bytes:
        import urllib.request

        with urllib.request.urlopen(url, timeout=60) as resp:
            return resp.read()


@dataclass(frozen=True)
class Problem:
    """One named reason a submission cannot merge."""

    addon_id: str
    version: str
    kind: str      # "schema" | "homepage" | "artifact-url" | "checksum" | "manifest" | "addon-check"
    detail: str

    def __str__(self) -> str:
        where = f"{self.addon_id}@{self.version}" if self.version else (self.addon_id or "index")
        return f"{where}: [{self.kind}] {self.detail}"


def _run_addon_check(bundle_dir: Path) -> list[str]:
    """``localbib-addon check`` on an unpacked Bundle (the CI installs
    ``localbib-plugin-api[dev]`` first, so this import is available there)."""
    from plugin_api.addon_tool import check_bundle

    return check_bundle(bundle_dir).errors


def check_entry(
    entry: dict,
    fetcher: Fetcher,
    *,
    run_addon_check: Callable[[Path], list[str]] = _run_addon_check,
) -> list[Problem]:
    """Every reason one index entry's newest version should not merge.

    Assumes the entry is already schema-valid (call after
    :func:`marketplace_index.validate_index` reports nothing for it).
    """
    addon_id = str(entry.get("id") or "?")
    problems: list[Problem] = []

    homepage = str(entry.get("homepage") or "")
    if not homepage.startswith(("http://", "https://")):
        problems.append(Problem(addon_id, "", "homepage",
                                "the source repository ('homepage') must be an http(s) URL"))
    elif not fetcher.url_ok(homepage):
        problems.append(Problem(addon_id, "", "homepage",
                                f"source repository is not reachable: {homepage}"))

    versions = entry.get("versions") or []
    if not versions:
        return problems
    version = versions[0]  # the newest — merge_snippet always prepends it
    version_str = str(version.get("version") or "?")

    for artifact in version.get("artifacts") or []:
        url = str(artifact.get("url") or "")
        if not fetcher.url_ok(url):
            problems.append(Problem(addon_id, version_str, "artifact-url", f"artifact is not reachable: {url}"))
            continue
        try:
            data = fetcher.get(url)
        except Exception as exc:  # network/transport failure — name it, don't crash the run
            problems.append(Problem(addon_id, version_str, "artifact-url", f"could not download artifact: {exc}"))
            continue

        digest = hashlib.sha256(data).hexdigest()
        expected = str(artifact.get("sha256") or "")
        if digest != expected:
            problems.append(Problem(addon_id, version_str, "checksum",
                                    f"sha256 {digest} does not match the index entry ({expected})"))
            continue

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                manifest = json.loads(zf.read("plugin.json"))
        except KeyError:
            problems.append(Problem(addon_id, version_str, "manifest", "the artifact has no plugin.json at its root"))
            continue
        except zipfile.BadZipFile:
            problems.append(Problem(addon_id, version_str, "manifest", "the artifact is not a valid zip"))
            continue

        # ``python`` too: the core picks the artifact by this tag, then loads
        # the Zip's Manifest — a native Bundle listed as "any" would install
        # everywhere and turn up incompatible.
        expected_fields = {"id": addon_id, "version": version_str, "python": str(artifact.get("python") or "")}
        for field, want in expected_fields.items():
            if str(manifest.get(field)) != want:
                problems.append(Problem(addon_id, version_str, "manifest",
                                        f"plugin.json {field}={manifest.get(field)!r} does not match "
                                        f"the index entry ({want!r})"))
        if entry.get("license") and manifest.get("license") != entry.get("license"):
            problems.append(Problem(addon_id, version_str, "manifest",
                                    f"plugin.json license={manifest.get('license')!r} does not match "
                                    f"the index entry ({entry.get('license')!r})"))

        with tempfile.TemporaryDirectory(prefix="localbib-submission-") as tmp:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                zf.extractall(tmp)
            for error in run_addon_check(Path(tmp)):
                problems.append(Problem(addon_id, version_str, "addon-check", error))

    return problems


def check_index(
    index: dict,
    fetcher: Fetcher,
    *,
    run_addon_check: Callable[[Path], list[str]] = _run_addon_check,
) -> list[Problem]:
    """Every reason ``index`` should not merge as-is.

    A schema problem short-circuits: an index the core cannot even parse
    correctly cannot be walked entry by entry (there is no reliable "newest
    version" to check an artifact of).
    """
    schema_problems = validate_index(index)
    if schema_problems:
        return [Problem("", "", "schema", message) for message in schema_problems]
    return [
        problem
        for entry in (index.get("addons") or [])
        for problem in check_entry(entry, fetcher, run_addon_check=run_addon_check)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the Marketplace-Index for a pull request.")
    parser.add_argument("index", nargs="?", default="index.json")
    args = parser.parse_args(argv)

    index = json.loads(Path(args.index).read_text(encoding="utf-8"))
    problems = check_index(index, UrllibFetcher())
    for problem in problems:
        print(f"ERROR: {problem}")
    if problems:
        print(f"{len(problems)} problem(s) found.")
        return 1
    print("OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
