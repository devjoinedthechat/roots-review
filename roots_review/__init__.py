"""Deterministic review data for the Bitcoin Roots patch series.

Read-only with respect to everything upstream: it fetches public tags and
branches, replays published or generated patch series locally, and writes JSON
under out/. Nothing is pushed, posted or published.
"""

import hashlib
import json
import os

__version__ = "0.2.0"
TOOL = f"roots-review {__version__}"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.environ.get("ROOTS_REVIEW_WORK", os.path.join(ROOT, ".work"))
REPO = os.path.join(WORK, "repo")
DOWNLOADS = os.path.join(WORK, "downloads")
OUT = os.environ.get("ROOTS_REVIEW_OUT", os.path.join(ROOT, "out"))
CONFIG = os.environ.get("ROOTS_REVIEW_CONFIG", os.path.join(ROOT, "config.json"))


class ReviewError(Exception):
    """Expected failure with a message meant for the operator."""


class VerificationError(ReviewError):
    """An integrity check failed: the inputs are not what they claim to be."""


def write_json(path, obj):
    """Write JSON atomically (temp file, then rename). Nothing time-dependent is added,
    so identical inputs produce identical bytes."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def read_json(path):
    with open(path) as f:
        return json.load(f)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 16):
            h.update(chunk)
    return h.hexdigest()


from .config import load_config  # noqa: E402,F401  (re-export)
