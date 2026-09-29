#!/usr/bin/env python3
"""The Marketplace-Index as the core reads it — validate it, and feed it (#195, ADR-0021).

``marketplace/index.json`` is exported as the repo ``localbib-plugins`` and
fetched by the core (``marketplace_client.INDEX_URL``), which judges it in
``services/marketplace.py``. This module holds the two halves of the
maintainer's side of that contract:

* :func:`validate_index` — the shape ``services/marketplace`` consumes:
  ``{"updated", "addons": [{id, name, trust, icon, screenshots, versions:
  [{version, api_version, min_core, permissions, requires_source, artifacts:
  [{python, url, size, sha256}]}]}]}``, with every image path present in the
  index tree. The export verification of the ``index`` target runs it.
  ``versions: []`` is an *announced* Add-on (editorial entry, no release
  yet); the core lists no card for it.
* :func:`merge_snippet` — turns the index snippet that ``localbib-addon build``
  writes (``{id, version, api_version, min_core, python, artifact, size,
  sha256}``) into a version entry of that Add-on and puts it into the index.
  This is how a checksum reaches the index: copied by code from the release
  asset, never by hand (user story 47; the Console button is #196).

Pure and stdlib-only; no network.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Iterable, Mapping

TRUST_LEVELS = ("official", "third-party")


def artifact_url(repo_slug: str, tag: str, artifact: str) -> str:
    """Where the build workflow's release asset is downloadable."""
    return f"https://github.com/{repo_slug}/releases/download/{tag}/{artifact}"


def version_entry_from_snippet(
    snippet: Mapping[str, Any],
    *,
    repo_slug: str,
    tag: str,
    permissions: Iterable[str],
    released: str,
    changelog: str = "",
) -> dict:
    """One index version entry from a ``localbib-addon build`` snippet."""
    return {
        "version": str(snippet["version"]),
        "api_version": snippet["api_version"],
        "min_core": str(snippet["min_core"]),
        "released": released,
        "changelog": changelog,
        "requires_source": False,
        "permissions": list(permissions),
        "artifacts": [{
            "python": str(snippet.get("python") or "any"),
            "url": artifact_url(repo_slug, tag, str(snippet["artifact"])),
            "size": int(snippet["size"]),
            "sha256": str(snippet["sha256"]),
        }],
    }


def merge_snippet(
    index: Mapping[str, Any],
    snippet: Mapping[str, Any],
    *,
    repo_slug: str,
    tag: str,
    permissions: Iterable[str],
    released: str,
    changelog: str = "",
) -> dict:
    """A copy of ``index`` whose entry for ``snippet['id']`` carries this version.

    Other versions are kept. A **published version is immutable**: users
    installed exactly those bytes, and the core compares their checksum
    against the index. So a snippet for a version the index already lists is
    a no-op when it names the same artifact (URL and SHA-256), and refused
    with :class:`PublishedVersionError` when it names another one — a rebuilt
    artifact gets a new version number. The Add-on must already be listed
    (``KeyError`` otherwise): its texts, trust level and images are editorial
    decisions, not build output.
    """
    merged = copy.deepcopy(dict(index))
    addon_id = str(snippet["id"])
    entry = next((a for a in merged.get("addons") or [] if a.get("id") == addon_id), None)
    if entry is None:
        raise KeyError(f"the index has no entry for {addon_id!r}; add its metadata first")
    version = version_entry_from_snippet(
        snippet, repo_slug=repo_slug, tag=tag, permissions=permissions,
        released=released, changelog=changelog,
    )
    listed = [v for v in entry.get("versions") or [] if str(v.get("version")) == version["version"]]
    if listed:
        new = version["artifacts"][0]
        if any(a.get("url") == new["url"] and a.get("sha256") == new["sha256"]
               for v in listed for a in v.get("artifacts") or []):
            return merged
        raise PublishedVersionError(addon_id, version["version"])
    entry["versions"] = [version, *(entry.get("versions") or [])]
    return merged


class PublishedVersionError(ValueError):
    """A snippet would change a version the index already publishes."""

    def __init__(self, addon_id: str, version: str) -> None:
        super().__init__(
            f"{addon_id} {version} is already in the index with another artifact; a published "
            "version is immutable - release the rebuilt artifact under a new version"
        )
        self.addon_id = addon_id
        self.version = version


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_version(where: str, version: Any) -> list[str]:
    if not isinstance(version, dict):
        return [f"{where}: a version must be an object"]
    problems = []
    for key in ("version", "min_core"):
        if not isinstance(version.get(key), str) or not version.get(key):
            problems.append(f"{where}: '{key}' must be a non-empty string")
    if not _is_int(version.get("api_version")):
        problems.append(f"{where}: 'api_version' must be an integer")
    if not isinstance(version.get("permissions", []), list):
        problems.append(f"{where}: 'permissions' must be a list")
    artifacts = version.get("artifacts") or []
    if not isinstance(artifacts, list):
        return problems + [f"{where}: 'artifacts' must be a list"]
    if not version.get("requires_source") and not artifacts:
        problems.append(f"{where}: no artifact and not 'requires_source' — nothing to install")
    for n, art in enumerate(artifacts):
        at = f"{where}.artifacts[{n}]"
        if not isinstance(art, dict):
            problems.append(f"{at}: must be an object")
            continue
        if not str(art.get("url") or "").lower().startswith("https://"):
            problems.append(f"{at}: 'url' must be an https:// URL")
        sha = str(art.get("sha256") or "")
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            problems.append(f"{at}: 'sha256' must be 64 lowercase hex digits")
        if not _is_int(art.get("size")) or art.get("size") <= 0:
            problems.append(f"{at}: 'size' must be a positive integer")
        if not isinstance(art.get("python"), str) or not art.get("python"):
            problems.append(f"{at}: 'python' must be 'any' or a build tag")
    return problems


def validate_index(data: Any, root: Path | None = None) -> list[str]:
    """Every reason the core would misread ``data``; ``root`` checks image paths."""
    if not isinstance(data, dict):
        return ["the index must be a JSON object"]
    addons = data.get("addons")
    if not isinstance(addons, list):
        return ["'addons' must be a list"]
    problems: list[str] = []
    seen: set[str] = set()
    for n, entry in enumerate(addons):
        where = f"addons[{n}]"
        if not isinstance(entry, dict):
            problems.append(f"{where}: must be an object")
            continue
        addon_id = entry.get("id")
        if not isinstance(addon_id, str) or not addon_id:
            problems.append(f"{where}: 'id' must be a non-empty string")
            continue
        where = f"addons[{addon_id}]"
        if addon_id in seen:
            problems.append(f"{where}: listed twice")
        seen.add(addon_id)
        if entry.get("trust") not in TRUST_LEVELS:
            problems.append(f"{where}: 'trust' must be one of {TRUST_LEVELS}")
        for key in ("name", "tagline", "license"):
            if not isinstance(entry.get(key), str) or not entry.get(key):
                problems.append(f"{where}: '{key}' must be a non-empty string")
        images = [entry.get("icon"), *(entry.get("screenshots") or [])]
        for image in images:
            if not isinstance(image, str) or not image:
                problems.append(f"{where}: image paths must be non-empty strings")
                continue
            if image.startswith("/") or ".." in image.split("/") or "://" in image:
                problems.append(f"{where}: image {image!r} must be relative to the index repo")
            elif root is not None and not (Path(root) / image).is_file():
                problems.append(f"{where}: image {image!r} is not in the index tree")
        versions = entry.get("versions")
        # An empty list is an announced Add-on: its texts and images are in,
        # its first release is not yet (merge_snippet needs the entry to add
        # one). The core shows no card for it until a version arrives.
        if not isinstance(versions, list):
            problems.append(f"{where}: 'versions' must be a list")
            continue
        for v, version in enumerate(versions):
            problems += _validate_version(f"{where}.versions[{v}]", version)
    return problems
