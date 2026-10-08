import json
import os
import sys
import unittest

from roots_review.config import patch_browser_url, release_cfg, validate


def _cfg():
    with open("config.json") as f:
        return json.load(f)


class Config(unittest.TestCase):
    def test_rejects_non_https_remote(self):
        cfg = _cfg()
        cfg["remotes"]["core"] = "http://example.invalid/x.git"
        with self.assertRaises(Exception):
            validate(cfg)

    def test_release_derived_from_tag(self):
        cfg = _cfg()
        rel = release_cfg(cfg, "v29.4-roots.7")
        self.assertEqual((rel["kind"], rel["core_base"], rel["reference"], rel["previous"]),
                         ("published", "v29.4", "knots-29.3", "v29.4-roots.6"))
        self.assertIn("v29.4-roots.6", cfg["releases"])
        self.assertEqual(patch_browser_url(cfg, "v29.4-roots.7", 3, 29),
                         "https://plan-b.foundation/bitcoin-roots/patches/v29.4-roots.7/commit-3/file-29/")
        self.assertIsNone(patch_browser_url(cfg, "roots-30.3-candidate"))
        with self.assertRaises(Exception):
            release_cfg(cfg, "v30.3-roots.1")  # no reference_by_core entry for 30.3


class Pager(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, os.getcwd())
        import mcp_server
        self.pages = mcp_server._pages

    def test_pages_break_on_file_and_hunk_boundaries(self):
        f1 = "diff --git a/a b/a\n@@ -1 +1 @@\n" + "+x\n" * 30
        f2 = "diff --git a/b b/b\n@@ -1 +1 @@\n" + "+y\n" * 30 + "@@ -50 +50 @@\n" + "+z\n" * 30
        pages = self.pages(f1 + f2, limit=120)
        import re
        rebuilt = re.sub(r"(?m)^diff --git .*  \(continued\)\n", "", "".join(pages))
        self.assertEqual(rebuilt, f1 + f2)  # nothing lost, nothing duplicated
        for p in pages:
            self.assertTrue(p.startswith(("diff --git", "+")), p[:30])
        self.assertTrue(any("(continued)" in p for p in pages))

    def test_small_diff_is_one_page(self):
        self.assertEqual(len(self.pages("diff --git a/a b/a\n@@ -1 +1 @@\n+x\n")), 1)


if __name__ == "__main__":
    unittest.main()
