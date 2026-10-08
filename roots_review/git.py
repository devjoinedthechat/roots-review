"""Hermetic git runner.

The replay repository applies patches written by other people, so git runs
with no user or system config, no hooks, no credential helpers, https only,
and a fixed identity and timezone. That also makes replayed commit IDs
reproducible across machines.
"""

import os
import subprocess
import sys
import time

from . import REPO, ReviewError

_ENV = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "HOME": os.environ.get("HOME", "/nonexistent"),
    "LC_ALL": "C",
    "TZ": "UTC",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "/usr/bin/false",
    "SSH_ASKPASS": "/usr/bin/false",
    "GIT_PAGER": "cat",
    "GIT_AUTHOR_NAME": "roots-review replay",
    "GIT_AUTHOR_EMAIL": "replay@invalid",
    "GIT_COMMITTER_NAME": "roots-review replay",
    "GIT_COMMITTER_EMAIL": "replay@invalid",
}
_CONFIG = [
    "core.hooksPath=" + os.devnull,
    "core.fsmonitor=false",
    "core.quotepath=off",
    "core.autocrlf=false",
    "credential.helper=",
    "protocol.allow=never",
    "protocol.https.allow=always",
    "advice.detachedHead=false",
    "gc.auto=0",
    "maintenance.auto=false",
    "commit.gpgsign=false",
    "init.defaultBranch=replay",
    "diff.renames=true",
    "diff.algorithm=myers",
]
_ARGS = [a for kv in _CONFIG for a in ("-c", kv)]
DEFAULT_TIMEOUT = 600


def _run(args, cwd, input, timeout, env):
    try:
        return subprocess.run(
            ["git", *_ARGS, *args], cwd=cwd, env=dict(_ENV, **(env or {})),
            input=input.encode() if isinstance(input, str) else input,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise ReviewError(f"git {' '.join(args[:3])} timed out after {timeout}s")
    except FileNotFoundError:
        raise ReviewError("git not found on PATH")


def git(*args, cwd=REPO, check=True, env=None, input=None, timeout=DEFAULT_TIMEOUT):
    """Run git and return stdout as text (UTF-8, undecodable bytes replaced)."""
    proc = _run(args, cwd, input, timeout, env)
    if check and proc.returncode != 0:
        raise ReviewError(
            f"git {' '.join(args)} failed ({proc.returncode}):\n"
            + proc.stderr.decode("utf-8", "replace").strip()
        )
    return proc.stdout.decode("utf-8", "replace")


def ok(*args, cwd=REPO):
    return _run(args, cwd, None, DEFAULT_TIMEOUT, None).returncode == 0


def fetch(url, refspec, depth, retries=3):
    """Shallow fetch of one refspec, retried with backoff on network errors."""
    if not url.startswith("https://"):
        raise ReviewError(f"refusing non-https remote {url}")
    last = None
    for attempt in range(retries):
        try:
            git("fetch", "--quiet", "--no-tags", "--no-write-fetch-head", f"--depth={depth}",
                url, refspec)
            return
        except ReviewError as e:
            last = e
            print(f"  fetch failed (attempt {attempt + 1}/{retries}), retrying", file=sys.stderr)
            time.sleep(2 ** attempt)
    raise last


def rev(ref):
    return git("rev-parse", "--verify", "--quiet", ref + "^{commit}").strip()


def has_ref(ref):
    return ok("rev-parse", "--verify", "--quiet", ref)
