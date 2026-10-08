"""What changed between two series, commit by commit.

Same Core base (29.4-roots.3 -> 29.4-roots.4): a release delta.
Different bases (29.4-roots.4 -> 30.3 candidate): a port map. Every commit of
the old series should have a counterpart, and commits that cite a
"semantic source" should cite one that exists.
"""

import re

from .config import release_cfg, series_ref
from .git import git

_PAIR = re.compile(r"^\s*(\d+|-):\s+([0-9a-f]+|-+)\s+([=!<>])\s+(\d+|-):\s+([0-9a-f]+|-+)\s+(.*)$")
_STATUS = {"=": "unchanged", "!": "modified", "<": "removed", ">": "added"}
_SOURCE = re.compile(r"semantic source ([0-9a-f]{7,40})", re.I)


def parse_range_diff(text):
    pairs = []
    for line in text.split("\n"):
        m = _PAIR.match(line)
        if m:
            pairs.append({
                "old_index": None if m.group(1) == "-" else int(m.group(1)),
                "new_index": None if m.group(4) == "-" else int(m.group(4)),
                "status": _STATUS[m.group(3)],
                "subject": m.group(6),
                "interdiff": [],
            })
        elif pairs and line.strip():
            pairs[-1]["interdiff"].append(line)
    for p in pairs:
        p["interdiff"] = "\n".join(p["interdiff"])
        p["interdiff_lines"] = p["interdiff"].count("\n") + 1 if p["interdiff"] else 0
    return pairs


def release_delta(cfg, old, new, old_replay, new_replay):
    base_old = f"refs/tags/core/{release_cfg(cfg, old)['core_base']}"
    base_new = f"refs/tags/core/{release_cfg(cfg, new)['core_base']}"
    a, b = series_ref(old), series_ref(new)
    pairs = parse_range_diff(git("range-diff", "--no-color", "--creation-factor=80",
                                 f"{base_old}..{a}", f"{base_new}..{b}"))
    counts = {}
    for p in pairs:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    same_base = git("rev-parse", base_old) == git("rev-parse", base_new)
    out = {
        "from": old,
        "to": new,
        "same_core_base": same_base,
        "summary": counts,
        "pairs": pairs,
        "verify": [f"git range-diff {base_old.split('/')[-1]}..{old} {base_new.split('/')[-1]}..{new}"],
    }
    if same_base:
        out["net_tree_change"] = git("diff", "--shortstat", a, b, "--", ".", ":(exclude).github/**").strip()
        out["net_files"] = git("diff", "--name-status", a, b, "--", ".", ":(exclude).github/**").splitlines()
    else:
        out["port"] = _port_map(pairs, old_replay, new_replay)
    return out


def _port_map(pairs, old_replay, new_replay):
    """Coverage of the old series by the new one, and trailer resolution."""
    old_by_sha = {c["original"]: c["index"] for c in old_replay["commits"]}
    paired_old = {p["old_index"] for p in pairs if p["old_index"] and p["new_index"]}
    unported = [c["index"] for c in old_replay["commits"] if c["index"] not in paired_old]
    trailers = []
    for c in new_replay["commits"]:
        body = git("log", "-1", "--format=%B", c["replayed"])
        for m in _SOURCE.finditer(body):
            sha = m.group(1)
            hit = [i for s, i in old_by_sha.items() if s.startswith(sha)]
            trailers.append({"new_index": c["index"], "cites": sha,
                             "resolves_to_old_index": hit[0] if len(hit) == 1 else None})
    cited_new = {t["new_index"] for t in trailers}
    ported = [p for p in pairs if p["old_index"] and p["new_index"]]
    return {
        "old_commits": len(old_replay["commits"]),
        "new_commits": len(new_replay["commits"]),
        "paired": len(ported),
        "unported_old_indices": unported,
        "new_only": [p["new_index"] for p in pairs if not p["old_index"]],
        "trailers": trailers,
        "ported_with_trailer": sum(1 for p in ported if p["new_index"] in cited_new),
        "trailers_unresolved": [t for t in trailers if t["resolves_to_old_index"] is None],
        "trailers_disagree_with_pairing": [
            t for t in trailers if t["resolves_to_old_index"] is not None and not any(
                p["new_index"] == t["new_index"] and p["old_index"] == t["resolves_to_old_index"]
                for p in ported)],
    }
