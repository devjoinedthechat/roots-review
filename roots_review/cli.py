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
from .config import load_config, reference, release_cfg
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
    rel = release_cfg(cfg, release)
    deps = []
    if rel["reference"].startswith("release:"):
        deps.append(rel["reference"][8:])
    if rel.get("previous") and rel["previous"] not in deps:
        deps.append(rel["previous"])
    return deps


def build_order(cfg, releases):
    order, seen, stack = [], set(), set()

    def visit(r):
        if r in seen:
            return
        if r in stack:
            raise ReviewError(f"dependency cycle at {r}")
        stack.add(r)
        for d in _deps(cfg, r):
            visit(d)
        stack.discard(r)
        seen.add(r)
        order.append(r)

    for r in releases:
        release_cfg(cfg, r)
        visit(r)
    return order


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

    inputs = {
        "tool": TOOL,
        "tool_source": tool_source_hash(),
        "config_sha256": cfg["_sha256"],
        "core_base": replay["core_base"]["commit"],
        "series_head": replay["series_head"],
        "patch_sha512": replay["patch_sha512"],
        "reference": {"name": ref["name"], "base": rev(ref["base"]), "tip": rev(ref["tip"])},
        "previous": read_json(prev_manifest)["fingerprint"] if prev_manifest and os.path.exists(prev_manifest) else None,
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
    write_json(manifest_path, {"tool": TOOL, "release": release, "fingerprint": fp,
                               "inputs": inputs, "files": hashes})
    _log(f"[{release}] done in {time.time() - t0:.0f}s: {len(replay['commits'])} commits verified and indexed")


def cmd_build(args):
    cfg = load_config()
    workspace.OFFLINE = args.offline
    targets = args.releases or list(cfg["releases"])
    order = build_order(cfg, targets)
    workspace.init_repo()
    for r in order:
        build_one(cfg, r, args)
    return 0


def cmd_discover(args):
    import re
    cfg = load_config()
    out = git("ls-remote", "--tags", "--refs", cfg["remotes"]["roots"], cwd=None)
    tags = sorted({line.split("refs/tags/")[1] for line in out.splitlines() if "refs/tags/" in line},
                  key=lambda t: [int(x) for x in re.findall(r"\d+", t)])
    for t in tags:
        if not re.match(r"^v\d+\.\d+-roots\.\d+$", t):
            continue
        built = os.path.exists(os.path.join(OUT, t, "manifest.json"))
        try:
            release_cfg(cfg, t)
            note = "built" if built else "buildable: roots-review build " + t
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
