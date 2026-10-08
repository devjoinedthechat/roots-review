"""Series index: every commit of a replayed series with its files and hunks, as published.

Files are listed in the order the published patch lists them. The project's patch browser
numbers files in the same order, so file i of commit N is .../commit-N/file-i/.
"""

from . import diffparse
from .config import patch_browser_url, release_cfg, series_ref
from .git import git


def _diff(a, b):
    return diffparse.parse(git("diff", "--no-color", "--find-renames", "-U3", a, b))


def _files(files, link):
    out = []
    for f in files:
        hunks = []
        for h in f.hunks:
            end = h.new_start + max(h.new_len, 1) - 1
            hunks.append({"header": h.header(), "function": h.context, "new_lines": [h.new_start, end],
                          "added": len(h.added), "removed": len(h.removed),
                          **({"link": link(f.path, h.new_start, end)} if f.status != "D" else {})})
        out.append({"path": f.path, "old_path": f.old_path, "status": f.status, "binary": f.binary,
                    "additions": f.additions, "deletions": f.deletions, "hunks": hunks})
    return out


def series_index(cfg, release, replay):
    rel = release_cfg(cfg, release)
    repo = cfg["github_repo"]
    commits = []
    for c in replay["commits"]:
        sha, orig = c["replayed"], c["original"]
        author, date, subject = git("log", "-1", "--format=%an <%ae>%n%aI%n%s", sha).split("\n")[:3]
        files = _files(_diff(f"{sha}^", sha),
                       lambda p, a, b, o=orig: f"https://github.com/{repo}/blob/{o}/{p}#L{a}-L{b}")
        commits.append({
            "index": c["index"], "of": len(replay["commits"]), "commit": orig, "replayed": sha,
            "url": f"https://github.com/{repo}/commit/{orig}",
            "web_url": patch_browser_url(cfg, release, c["index"]),
            "subject": subject, "author": author, "date": date,
            "files_changed": len(files),
            "additions": sum(f["additions"] for f in files),
            "deletions": sum(f["deletions"] for f in files),
            "files": files,
        })
    target = replay["target"]["commit"]
    net = _files(_diff(f"refs/tags/core/{rel['core_base']}", series_ref(release)),
                 lambda p, a, b: f"https://github.com/{repo}/blob/{target}/{p}#L{a}-L{b}")
    return {
        "release": release,
        "core_base": rel["core_base"],
        "commits": commits,
        "net": {"files": net, "additions": sum(f["additions"] for f in net),
                "deletions": sum(f["deletions"] for f in net)},
        "verify": [f"git log --reverse --format='%h %s' {rel['core_base']}..{release}",
                   "git show <commit> -- <path>"],
    }
