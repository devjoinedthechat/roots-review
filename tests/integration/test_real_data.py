"""Golden checks against the real built data (run `roots-review build` first)."""

import hashlib
import json
import os
import unittest

from roots_review import OUT

R3, R4, C30 = "v29.4-roots.3", "v29.4-roots.4", "roots-30.3-candidate"


def load(release, name):
    with open(os.path.join(OUT, release, f"{name}.json")) as f:
        return json.load(f)


@unittest.skipUnless(os.path.exists(os.path.join(OUT, R4, "manifest.json")), "run `roots-review build` first")
class Golden(unittest.TestCase):
    def test_integrity(self):
        for r, n in ((R3, 30), (R4, 37)):
            rp = load(r, "replay")
            self.assertTrue(rp["sha512_matches"])
            self.assertTrue(rp["replay_reproduces_target"])
            self.assertEqual(len(rp["commits"]), n)

    def test_original_shas_recorded(self):
        self.assertEqual(load(R4, "replay")["commits"][2]["original"], "e400ebd938a6b27003109c5c55e8a421cba83167")

    def test_series_index_matches_patch_browser_numbering(self):
        c3 = load(R4, "series")["commits"][2]
        self.assertEqual(c3["files_changed"], 80)
        self.assertEqual(c3["files"][28]["path"], "src/policy/policy.cpp")  # .../commit-3/file-29/
        self.assertTrue(c3["web_url"].endswith("/v29.4-roots.4/commit-3/"))
        c31 = load(R4, "series")["commits"][30]
        self.assertEqual(c31["files"][0]["path"], "src/node/miner.cpp")

    def test_release_delta(self):
        self.assertEqual(load(R4, "delta")["summary"], {"unchanged": 30, "added": 7})
        self.assertEqual(load(R3, "delta")["from"], "v29.4-roots.2")  # derived from the tag name

    @unittest.skipUnless(os.path.exists(os.path.join(OUT, C30, "manifest.json")), "candidate not built")
    def test_port_map(self):
        # roots/30.3 is a moving branch: check the port map's structure, not today's counts.
        p = load(C30, "delta")["port"]
        self.assertEqual(p["old_commits"], 37)  # v29.4-roots.4 is immutable
        self.assertEqual(p["paired"] + len(p["unported_old_indices"]), p["old_commits"])
        self.assertEqual(p["new_commits"], p["paired"] + len(p["new_only"]))
        for t in p["trailers"]:
            self.assertTrue(t["resolves_to_old_index"] is None or 1 <= t["resolves_to_old_index"] <= 37)

    def test_manifest_hashes(self):
        for r in (R3, R4):
            m = load(r, "manifest")
            self.assertEqual(sorted(m["files"]), ["delta.json", "replay.json", "series.json"])
            self.assertTrue(m["release_config"]["derived"])
            for name, digest in m["files"].items():
                with open(os.path.join(OUT, r, name), "rb") as f:
                    self.assertEqual(hashlib.sha256(f.read()).hexdigest(), digest, name)


if __name__ == "__main__":
    unittest.main()
