"""Load and validate config.json; resolve releases and references to git refs."""

import json
import re

from . import CONFIG, ReviewError, sha256_file

_SCHEMA = "roots-review/config@2"
_NAME = re.compile(r"^[A-Za-z0-9._-]+$")

_cache = {}


def load_config(path=None):
    path = path or CONFIG
    if path in _cache:
        return _cache[path]
    try:
        with open(path) as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ReviewError(f"cannot read config {path}: {e}")
    validate(cfg)
    cfg["_sha256"] = sha256_file(path)
    _cache[path] = cfg
    return cfg


def validate(cfg):
    def need(cond, msg):
        if not cond:
            raise ReviewError(f"config: {msg}")

    need(cfg.get("schema") == _SCHEMA, f"schema must be {_SCHEMA!r}")
    remotes = cfg.get("remotes", {})
    for name, url in remotes.items():
        need(url.startswith("https://"), f"remote {name} must be https")
    for name, ref in cfg.get("references", {}).items():
        need(_NAME.match(name), f"bad reference name {name!r}")
        for side in ("base", "tip"):
            need(ref.get(side, {}).get("remote") in remotes, f"reference {name}.{side}: unknown remote")
            need(_NAME.match(ref[side].get("tag", "")), f"reference {name}.{side}: bad tag")
    releases = cfg.get("releases", {})
    need(releases, "no releases configured")
    for name, rel in releases.items():
        need(_NAME.match(name), f"bad release name {name!r}")
        need(rel.get("kind") in ("published", "candidate"), f"{name}: kind must be published|candidate")
        need(_NAME.match(rel.get("core_base", "")), f"{name}: bad core_base")
        if rel["kind"] == "candidate":
            need(re.match(r"^[A-Za-z0-9._/-]+$", rel.get("branch", "")), f"{name}: candidate needs branch")
        ref = rel.get("reference", "")
        if ref.startswith("release:"):
            need(ref[8:] in releases, f"{name}: reference release {ref[8:]!r} not configured")
        else:
            need(ref in cfg.get("references", {}), f"{name}: unknown reference {ref!r}")
        prev = rel.get("previous")
        need(prev is None or prev in releases, f"{name}: unknown previous {prev!r}")
    for core, ref in cfg.get("reference_by_core", {}).items():
        need(re.match(r"^\d+\.\d+$", core), f"reference_by_core: bad Core line {core!r}")
        need(ref in cfg.get("references", {}), f"reference_by_core.{core}: unknown reference {ref!r}")
    url = cfg.get("patch_browser_url", "")
    need(not url or (url.startswith("https://") and "{release}" in url), "patch_browser_url must be https with {release}")


# --------------------------------------------------------------------------- ref naming

def tag_ref(remote, tag):
    return f"refs/tags/{remote}/{tag}"


def core_ref(tag):
    return tag_ref("core", tag)


def series_ref(release):
    return f"refs/series/{release}"


_TAG = re.compile(r"^v(\d+\.\d+)-roots\.(\d+)$")


def release_cfg(cfg, release):
    """A configured release, or one derived from a published tag name.

    Published Roots tags follow v<core>-roots.<n>, so v29.4-roots.5 needs no config
    entry: its Core base is v29.4, its reference comes from reference_by_core, and its
    previous release is v29.4-roots.4.
    """
    if release in cfg["releases"]:
        return cfg["releases"][release]
    m = _TAG.match(release)
    core = m and m.group(1)
    if not m or core not in cfg.get("reference_by_core", {}):
        known = ", ".join(cfg["releases"])
        hint = f" (no reference_by_core entry for Core {core})" if m else ""
        raise ReviewError(f"unknown release {release!r}{hint}; configured: {known}")
    n = int(m.group(2))
    rel = {"kind": "published", "core_base": f"v{core}", "reference": cfg["reference_by_core"][core],
           "derived": True}
    if n > 1:
        rel["previous"] = f"v{core}-roots.{n - 1}"
        release_cfg(cfg, rel["previous"])
    cfg["releases"][release] = rel
    return rel


def patch_browser_url(cfg, release, commit=None, file=None):
    """The project's own patch-browser page for a published release, commit or file."""
    base = cfg.get("patch_browser_url")
    if not base or cfg["releases"].get(release, {}).get("kind") != "published":
        return None
    url = base.format(release=release)
    if commit:
        url += f"commit-{commit}/"
        if file:
            url += f"file-{file}/"
    return url


def reference(cfg, release):
    """The (base, tip) pair a release is compared against, as local refs."""
    rel = release_cfg(cfg, release)
    name = rel["reference"]
    if name.startswith("release:"):
        other = name[8:]
        orel = cfg["releases"][other]
        return {
            "name": name,
            "label": f"Roots {other}",
            "kind": "release",
            "release": other,
            "base": core_ref(orel["core_base"]),
            "base_label": f"Core {orel['core_base']}",
            "tip": series_ref(other),
            "tip_label": other,
        }
    ref = cfg["references"][name]
    return {
        "name": name,
        "label": ref["label"],
        "kind": "upstream",
        "base": tag_ref(ref["base"]["remote"], ref["base"]["tag"]),
        "base_label": f"{ref['base']['remote'].title()} {ref['base']['tag']}",
        "tip": tag_ref(ref["tip"]["remote"], ref["tip"]["tag"]),
        "tip_label": ref["tip"]["tag"],
    }
