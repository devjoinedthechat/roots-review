"""roots-review command line.

  roots-review build [RELEASE ...] [--force] [--offline] [--refresh] [--allow-unverified]
  roots-review discover                          list published Roots tags and which are built
  roots-review clean [--all]

Exit codes: 0 ok, 2 usage or config error, 3 verification failure, 4 other operational error.
Nothing is pushed, posted or published.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import time

from . import OUT, TOOL, WORK, ReviewError, VerificationError, read_json, sha256_file, write_json
from . import delta, series, workspace
from .config import load_config, reference, release_cfg, set_known_tags
from .git import git, rev

FILES = ("replay", "series", "delta")


def tool_source_hash():
    """Hash of this package's source, so a code change invalidates cached output."""
    h = hashlib.sha256()
    pkg = os.path.dirname(os.path.abspath(__file__))
    for name in sorted(os.listdir(pkg)):
        if name.endswith(".py"):
            h.update(name.encode() + b"\0")
            with open(os.path.join(pkg, name), "rb") as f:
                h.update(f.read())
    return h.hexdigest()


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


def _deps(cfg, release):
    """(required, optional) dependencies: a release used as the reference is required;
    the previous release only feeds the delta, so a release without one still builds."""
    rel = release_cfg(cfg, release)
    required = [rel["reference"][8:]] if rel["reference"].startswith("release:") else []
    optional = [rel["previous"]] if rel.get("previous") and rel["previous"] not in required else []
    return required, optional


def build_order(cfg, releases, required=None):
    """Dependencies first. Returns [(release, required)]. Releases in `required` (default: all
    of `releases`) and their reference releases must build; anything else that fails is
    reported and skipped instead of stopping the run."""
    order, seen, stack = [], set(), set()
    required = set(releases if required is None else required)

    def visit(r, needed):
        if needed:
            required.add(r)
        if r in seen:
            return
        if r in stack:
            raise ReviewError(f"dependency cycle at {r}")
        stack.add(r)
        req, opt = _deps(cfg, r)
        for d in req:
            visit(d, needed)
        for d in opt:
            visit(d, False)
        stack.discard(r)
        seen.add(r)
        order.append(r)

    for r in releases:
        release_cfg(cfg, r)
        visit(r, r in required)
    return [(r, r in required) for r in order]


def _release_tags(cfg):
    """Published v<core>-roots.<n> tags: from the remote, or offline from what is built."""
    if workspace.OFFLINE:
        names = os.listdir(OUT) if os.path.isdir(OUT) else []
        return [n for n in names if os.path.exists(os.path.join(OUT, n, "manifest.json"))] + list(cfg["releases"])
    out = git("ls-remote", "--tags", "--refs", cfg["remotes"]["roots"], cwd=None)
    return [line.split("refs/tags/", 1)[1] for line in out.splitlines() if "refs/tags/" in line]


def load_release(release):
    rdir = os.path.join(OUT, release)
    data = {}
    for name in FILES:
        p = os.path.join(rdir, f"{name}.json")
        if os.path.exists(p):
            data[name] = read_json(p)
    return data


def _meta(name, release, fp):
    return {"schema": f"roots-review/{name}@2", "tool": TOOL, "release": release, "fingerprint": fp}


def build_one(cfg, release, args):
    t0 = time.time()
    rel = release_cfg(cfg, release)
    rdir = os.path.join(OUT, release)
    _log(f"[{release}] workspace")
    replay = workspace.setup(release, allow_unverified=args.allow_unverified, refresh=args.refresh)
    workspace.ensure_reference(cfg, release)
    ref = reference(cfg, release)
    prev = rel.get("previous")
    prev_manifest = os.path.join(OUT, prev, "manifest.json") if prev else None
    if prev and not os.path.exists(prev_manifest):
        _log(f"[{release}] previous release {prev} is not available; building without a delta")
        prev, prev_manifest = None, None
    release_config = {k: v for k, v in rel.items() if k != "previous"} | ({"previous": prev} if prev else {})

    inputs = {
        "tool": TOOL,
        "tool_source": tool_source_hash(),
        "config_sha256": cfg["_sha256"],
        "core_base": replay["core_base"]["commit"],
        "series_head": replay["series_head"],
        "patch_sha512": replay["patch_sha512"],
        "reference": {"name": ref["name"], "base": rev(ref["base"]), "tip": rev(ref["tip"])},
        "release_config": release_config,
        "previous": read_json(prev_manifest)["fingerprint"] if prev_manifest else None,
    }
    fp = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    manifest_path = os.path.join(rdir, "manifest.json")
    if not args.force and os.path.exists(manifest_path):
        m = read_json(manifest_path)
        if m.get("fingerprint") == fp and all(os.path.exists(os.path.join(rdir, f)) for f in m["files"]):
            _log(f"[{release}] up to date ({fp[:12]})")
            return

    _log(f"[{release}] series index")
    results = {"replay": replay, "series": series.series_index(cfg, release, replay)}
    if prev:
        _log(f"[{release}] delta from {prev}")
        results["delta"] = delta.release_delta(cfg, prev, release, load_release(prev)["replay"], replay)

    if os.path.isdir(rdir):
        for f in os.listdir(rdir):
            if f.endswith((".json", ".md")) and f != "manifest.json" and f[:-5] not in results:
                os.remove(os.path.join(rdir, f))
    hashes = {}
    for name, obj in results.items():
        path = os.path.join(rdir, f"{name}.json")
        write_json(path, {"meta": _meta(name, release, fp), **obj})
        hashes[f"{name}.json"] = sha256_file(path)
    write_json(manifest_path, {"tool": TOOL, "release": release, "release_config": release_config,
                               "fingerprint": fp, "inputs": inputs, "files": hashes})
    _log(f"[{release}] done in {time.time() - t0:.0f}s: {len(replay['commits'])} commits verified and indexed")


def cmd_build(args):
    cfg = load_config()
    workspace.OFFLINE = args.offline
    set_known_tags(cfg, _release_tags(cfg))
    configured = [r for r, rel in cfg["releases"].items() if not rel.get("derived")]
    if args.releases:
        targets, required = args.releases, set(args.releases)
    else:
        # Every published release plus the configured candidates. A published release that
        # cannot be fetched (for example one released without a patch) is reported and skipped.
        targets, required = cfg["_known_tags"] + configured, set(configured)
    order = build_order(cfg, targets, required)
    workspace.init_repo()
    for r, needed in order:
        try:
            build_one(cfg, r, args)
        except VerificationError:
            raise  # a checksum or replay mismatch is never skipped
        except ReviewError as e:
            if needed:
                raise
            _log(f"[{r}] skipped: {str(e).splitlines()[0]}")
    return 0


def cmd_discover(args):
    cfg = load_config()
    out = git("ls-remote", "--tags", "--refs", cfg["remotes"]["roots"], cwd=None)
    tags = [line.split("refs/tags/")[1] for line in out.splitlines() if "refs/tags/" in line]
    set_known_tags(cfg, tags)
    for t in cfg["_known_tags"]:
        built = os.path.exists(os.path.join(OUT, t, "manifest.json"))
        try:
            rel = release_cfg(cfg, t)
            note = ("built" if built else "buildable") + f"; previous: {rel.get('previous') or 'none'}"
        except ReviewError as e:
            note = f"not buildable: {str(e).split(';')[0]}"
        print(f"{t:18} {note}")
    return 0


def cmd_clean(args):
    shutil.rmtree(OUT, ignore_errors=True)
    if args.all:
        shutil.rmtree(WORK, ignore_errors=True)
    return 0


def parser():
    p = argparse.ArgumentParser(prog="roots-review", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="fetch, replay, analyse; write out/<release>/")
    b.add_argument("releases", nargs="*")
    b.add_argument("--force", action="store_true", help="rebuild even if inputs are unchanged")
    b.add_argument("--offline", action="store_true", help="use only refs and downloads already in .work/")
    b.add_argument("--refresh", action="store_true", help="re-download published patches and checksums")
    b.add_argument("--allow-unverified", action="store_true",
                   help="continue past checksum/replay mismatches (recorded in the output)")
    b.set_defaults(fn=cmd_build)
    d = sub.add_parser("discover", help="list published Roots tags and which are built")
    d.set_defaults(fn=cmd_discover)
    k = sub.add_parser("clean", help="remove out/ (and .work/ with --all)")
    k.add_argument("--all", action="store_true")
    k.set_defaults(fn=cmd_clean)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return args.fn(args)
    except VerificationError as e:
        _log(f"VERIFICATION FAILED: {e}")
        return 3
    except ReviewError as e:
        _log(f"error: {e}")
        return 2 if "config" in str(e) or "unknown release" in str(e) else 4
    except KeyboardInterrupt:
        return 130
    except Exception:  # a bug: report it distinctly from usage and verification errors
        import traceback
        traceback.print_exc()
        _log("internal error (exit 4); please report with the traceback above")
        return 4
