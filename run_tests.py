#!/usr/bin/env python3
"""Run the test suite: `python3 -I run_tests.py` (unit only) or `--all` (with integration).

Unit tests need nothing but Python. Integration tests read out/ and the replay
repo, so run `python3 -I roots-review build` first; they skip if it is missing.
Set ROOTS_REVIEW_DETERMINISM=1 with --all to also rebuild twice and compare bytes.
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True  # .pyc files embed absolute local paths

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)


def determinism():
    """Two forced builds into separate output dirs must be byte-identical."""
    import hashlib
    dirs = []
    for _ in range(2):
        d = tempfile.mkdtemp(prefix="roots-review-det-")
        env = dict(os.environ, ROOTS_REVIEW_OUT=d)
        subprocess.run([sys.executable, "-I", "roots-review", "build", "--force", "--offline"],
                       env=env, check=True, stderr=subprocess.DEVNULL)
        dirs.append(d)
    digests = []
    for d in dirs:
        h = {}
        for root, _, files in os.walk(d):
            for f in files:
                p = os.path.join(root, f)
                with open(p, "rb") as fh:
                    h[os.path.relpath(p, d)] = hashlib.sha256(fh.read()).hexdigest()
        digests.append(h)
    import shutil
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)
    diff = sorted(k for k in set(digests[0]) | set(digests[1]) if digests[0].get(k) != digests[1].get(k))
    print(f"determinism: {len(digests[0])} files, {len(diff)} differ" + (f": {diff}" if diff else ""))
    return not diff


def main():
    loader = unittest.TestLoader()
    suite = loader.discover("tests/unit", top_level_dir=HERE)
    if "--all" in sys.argv:
        suite.addTests(loader.discover("tests/integration", top_level_dir=HERE))
    ok = unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful()
    if ok and "--all" in sys.argv and os.environ.get("ROOTS_REVIEW_DETERMINISM") == "1":
        ok = determinism()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
