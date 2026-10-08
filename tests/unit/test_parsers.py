import unittest

from roots_review import diffparse
from roots_review.delta import parse_range_diff

DIFF = """diff --git a/src/node/miner.cpp b/src/node/miner.cpp
index 1111111..2222222 100644
--- a/src/node/miner.cpp
+++ b/src/node/miner.cpp
@@ -296,6 +296,8 @@ void BlockAssembler::SortForBlock(const CTxMemPool::setEntries& package)
     CTxMemPool::setEntries failedTx;
+    // Start by adding all descendants of previously added txs to mapModifiedTx
+    nDescendantsUpdated += UpdatePackagesForAdded(mempool, inBlock, mapModifiedTx);
     int64_t nConsecutiveFailed = 0;
-    old();
 }
diff --git a/doc/new.md b/doc/new.md
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/doc/new.md
@@ -0,0 +1,2 @@
+# Title
+text
diff --git a/a.bin b/a.bin
index 1..2 100644
Binary files a/a.bin and b/a.bin differ
diff --git a/old/name.h b/new/name.h
similarity index 90%
rename from old/name.h
rename to new/name.h
"""


class DiffParse(unittest.TestCase):
    def test_files_and_hunks(self):
        files = diffparse.parse(DIFF)
        self.assertEqual([f.path for f in files], ["src/node/miner.cpp", "doc/new.md", "a.bin", "new/name.h"])
        miner = files[0]
        self.assertEqual((miner.additions, miner.deletions), (2, 1))
        h = miner.hunks[0]
        self.assertEqual((h.old_start, h.old_len, h.new_start, h.new_len), (296, 6, 296, 8))
        self.assertTrue(h.context.startswith("void BlockAssembler::SortForBlock"))
        self.assertEqual(files[1].status, "A")
        self.assertTrue(files[2].binary)
        self.assertEqual((files[3].status, files[3].old_path), ("R", "old/name.h"))


RANGE_DIFF = """ 1:  fa2ecc9 !  1:  5c210e1 build: port platform and dependency support
    @@ Metadata
     ## Commit message ##
 2:  a2cb72f =  2:  85257a0 runtime: preserve shared operator controls
 3:  825a24d <  -:  ------- dropped: something
 -:  ------- >  3:  1b73fe3 test: new follow-up
"""


class RangeDiff(unittest.TestCase):
    def test_pairs(self):
        p = parse_range_diff(RANGE_DIFF)
        self.assertEqual([x["status"] for x in p], ["modified", "unchanged", "removed", "added"])
        self.assertEqual((p[0]["old_index"], p[0]["new_index"]), (1, 1))
        self.assertEqual(p[0]["interdiff_lines"], 2)
        self.assertIsNone(p[2]["new_index"])
        self.assertIsNone(p[3]["old_index"])


if __name__ == "__main__":
    unittest.main()
