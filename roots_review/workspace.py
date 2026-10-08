"""Build the local workspace: pinned upstream trees plus replayed series.

Refs are namespaced so nothing collides:
  refs/tags/<remote>/<tag>     a tag fetched from that remote (core, knots, roots)
  refs/branches/<remote>/<b>   a branch head fetched from that remote
  refs/series/<release>        the release's patch series replayed onto its Core base

Published releases replay the .patch attached to the GitHub release. Candidates
(unreleased branches) are turned into a patch with the same `git format-patch`
invocation Roots' own ci/release/create-patch-series.sh uses, then replayed the
same way, so both kinds are analysed through one code path.

Integrity checks fail closed: a checksum or replay mismatch raises
VerificationError unless the caller explicitly allows unverified input.
"""

import hashlib
import os
import re
import urllib.error
import urllib.request

from . import DOWNLOADS, REPO, WORK, ReviewError, VerificationError, read_json, write_json
from .config import load_config, release_cfg, series_ref, tag_ref
from .git import fetch, git, has_ref, ok, rev

MAX_DOWNLOAD = 64 << 20
OFFLINE = False  # set by `build --offline`: use only what is already in .work/
_FROM = re.compile(rb"^From ([0-9a-f]{40}) Mon Sep 17 00:00:00 2001$", re.M)
_EXCLUDE_GITHUB = [".", ":(exclude).github/**"]


def init_repo():
    if not os.path.isdir(os.path.join(REPO, ".git")):
        os.makedirs(REPO, exist_ok=True)
        git("init", "--quiet")
    # The replay repo never has remotes: there is nothing it could push to.
    if git("remote").strip():
        raise ReviewError(f"{REPO} has git remotes configured; refusing to use it")


def _need_network(what):
    if OFFLINE:
        raise ReviewError(f"--offline: {what} is not in .work/ yet")


def ensure_tag(remote, tag):
    local = tag_ref(remote, tag)
    if not has_ref(local):
        _need_network(f"{remote} tag {tag}")
        fetch(load_config()["remotes"][remote], f"+refs/tags/{tag}:{local}", depth=1)
    return local


def ensure_branch(remote, branch, base_commit):
    """Fetch a branch deep enough that base_commit is an ancestor of its head."""
    local = f"refs/branches/{remote}/{branch}"
    if OFFLINE:
        if has_ref(local) and ok("merge-base", "--is-ancestor", base_commit, local):
            return local
        _need_network(f"{remote} branch {branch}")
    url = load_config()["remotes"][remote]
    for depth in (64, 128, 256, 512, 1024):
        fetch(url, f"+refs/heads/{branch}:{local}", depth=depth)
        if ok("merge-base", "--is-ancestor", base_commit, local):
            return local
    raise ReviewError(f"{remote}/{branch} does not descend from {base_commit[:12]} within 1024 commits")


def _download(url, dest, refresh=False):
    if os.path.exists(dest) and not refresh:
        return
    _need_network(os.path.basename(dest))
    if not url.startswith("https://"):
        raise ReviewError(f"refusing non-https download {url}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    size = 0
    try:
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 16):
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise ReviewError(f"{url} exceeds {MAX_DOWNLOAD >> 20} MiB")
                f.write(chunk)
    except urllib.error.URLError as e:
        raise ReviewError(f"download failed: {url}: {e}")
    os.replace(tmp, dest)


def _sha512(path):
    h = hashlib.sha512()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 16):
            h.update(chunk)
    return h.hexdigest()


def _original_commits(patch_path):
    with open(patch_path, "rb") as f:
        return [m.decode() for m in _FROM.findall(f.read())]


def _replay(release, base, patch, patch_sha):
    """Apply the patch onto base as refs/series/<release>; reuse if already built from it."""
    ref = series_ref(release)
    stamp_path = os.path.join(WORK, "series", f"{release}.json")
    if has_ref(ref) and os.path.exists(stamp_path):
        stamp = read_json(stamp_path)
        if stamp.get("patch_sha512") == patch_sha and stamp.get("base") == rev(base) \
                and stamp.get("head") == rev(ref):
            return ref
    git("checkout", "--quiet", "--detach", base)
    try:
        git("am", "--quiet", "--keep-cr", "--committer-date-is-author-date", patch)
    except ReviewError:
        git("am", "--abort", check=False)
        raise
    git("update-ref", ref, "HEAD")
    git("checkout", "--quiet", "--detach", base)
    write_json(stamp_path, {"patch_sha512": patch_sha, "base": rev(base), "head": rev(ref)})
    return ref


def setup(release, allow_unverified=False, refresh=False):
    """Fetch inputs for a release, replay its series, and verify it. Returns replay facts."""
    cfg = load_config()
    rel = release_cfg(cfg, release)
    init_repo()
    base = ensure_tag("core", rel["core_base"])
    base_commit = rev(base)

    if rel["kind"] == "published":
        version = release[1:]
        ddir = os.path.join(DOWNLOADS, release)
        patch = os.path.join(ddir, f"bitcoin-roots-{version}.patch")
        sums = os.path.join(ddir, "SHA512SUMS")
        _download(cfg["patch_url"].format(release=release, version=version), patch, refresh)
        _download(cfg["sums_url"].format(release=release), sums, refresh)
        listed = None
        with open(sums) as f:
            for line in f:
                parts = line.split()
                if len(parts) == 2 and parts[1].lstrip("*") == os.path.basename(patch):
                    listed = parts[0].lower()
        target = ensure_tag("roots", release)
        target_label = f"tag {release}"
        source = {"kind": "published", "patch_url": cfg["patch_url"].format(release=release, version=version)}
    else:
        target = ensure_branch("roots", rel["branch"], base_commit)
        target_label = f"branch {rel['branch']} at {rev(target)[:12]}"
        if git("rev-list", "--merges", "--count", f"{base_commit}..{target}").strip() != "0":
            raise ReviewError(f"{rel['branch']} has merge commits; the series must be linear")
        patch = os.path.join(WORK, "candidates", f"{release}.patch")
        os.makedirs(os.path.dirname(patch), exist_ok=True)
        text = git("format-patch", "--stdout", "--binary", "--full-index", f"--base={base_commit}",
                   f"{base_commit}..{target}", "--", *_EXCLUDE_GITHUB)
        with open(patch + ".tmp", "w") as f:
            f.write(text)
        os.replace(patch + ".tmp", patch)
        listed = None
        source = {"kind": "candidate", "branch": rel["branch"],
                  "note": "unreleased: patch generated locally with Roots' format-patch invocation"}

    digest = _sha512(patch)
    sha_ok = (listed == digest) if rel["kind"] == "published" else None
    if sha_ok is False and not allow_unverified:
        raise VerificationError(f"{release}: patch SHA512 {digest[:16]}... does not match SHA512SUMS "
                                f"({(listed or 'no entry')[:16]}...)")

    ref = _replay(release, base, patch, digest)
    reproduces = ok("diff", "--quiet", target, ref, "--", *_EXCLUDE_GITHUB)
    if not reproduces and not allow_unverified:
        raise VerificationError(f"{release}: replayed series differs from {target_label} outside .github/")

    originals = _original_commits(patch)
    replayed = git("rev-list", "--reverse", f"{base_commit}..{ref}").split()
    if len(originals) != len(replayed):
        raise VerificationError(f"{release}: patch has {len(originals)} commits, replay has {len(replayed)}")

    rel_patch = os.path.relpath(patch, WORK)
    return {
        "release": release,
        "kind": rel["kind"],
        "source": source,
        "patch_file": rel_patch,
        "patch_bytes": os.path.getsize(patch),
        "patch_sha512": digest,
        "sha512sums_entry": listed,
        "sha512_matches": sha_ok,
        "core_base": {"ref": rel["core_base"], "commit": base_commit},
        "target": {"label": target_label, "commit": rev(target)},
        "series_head": rev(ref),
        "replay_reproduces_target": reproduces,
        "commits": [{"index": i, "original": o, "replayed": r}
                    for i, (o, r) in enumerate(zip(originals, replayed), 1)],
        "unverified_allowed": bool(allow_unverified and (sha_ok is False or not reproduces)),
        "verify": ([f"sha512sum {os.path.basename(patch)}  # compare with SHA512SUMS"]
                   if rel["kind"] == "published" else
                   [f"git format-patch --stdout --binary --full-index {rel['core_base']}..{rel['branch']} "
                    f"-- . ':(exclude).github/**' > {os.path.basename(patch)}"]) + [
            f"git checkout {rel['core_base']} && git am --keep-cr {os.path.basename(patch)}",
            f"git diff --quiet {target_label.split()[1]} HEAD -- . ':(exclude).github/**' && echo reproduces",
        ],
    }


def ensure_reference(cfg, release):
    """Make sure the reference's base and tip exist locally (building a referenced release if needed)."""
    name = release_cfg(cfg, release)["reference"]
    if name.startswith("release:"):
        other = name[8:]
        if not has_ref(series_ref(other)):
            setup(other)
        ensure_tag("core", cfg["releases"][other]["core_base"])
        return
    ref = cfg["references"][name]
    ensure_tag(ref["base"]["remote"], ref["base"]["tag"])
    ensure_tag(ref["tip"]["remote"], ref["tip"]["tag"])
