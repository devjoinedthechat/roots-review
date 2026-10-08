"""Minimal unified-diff parser for `git diff`/`git show` output."""

import re

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")


class Hunk:
    __slots__ = ("old_start", "old_len", "new_start", "new_len", "context",
                 "lines")

    def __init__(self, old_start, old_len, new_start, new_len, context):
        self.old_start, self.old_len = old_start, old_len
        self.new_start, self.new_len = new_start, new_len
        self.context = context
        self.lines = []  # (tag, text) with tag in ' ', '+', '-'

    @property
    def added(self):
        return [t for tag, t in self.lines if tag == "+"]

    @property
    def removed(self):
        return [t for tag, t in self.lines if tag == "-"]

    def header(self):
        return (f"@@ -{self.old_start},{self.old_len} +{self.new_start},{self.new_len} @@"
                + (f" {self.context}" if self.context else ""))

    def text(self):
        return "\n".join([self.header()] + [tag + t for tag, t in self.lines])


class FileDiff:
    __slots__ = ("old_path", "new_path", "status", "binary", "hunks")

    def __init__(self, old_path, new_path):
        self.old_path, self.new_path = old_path, new_path
        self.status = "M"
        self.binary = False
        self.hunks = []

    @property
    def path(self):
        return self.new_path if self.new_path != "/dev/null" else self.old_path

    @property
    def additions(self):
        return sum(len(h.added) for h in self.hunks)

    @property
    def deletions(self):
        return sum(len(h.removed) for h in self.hunks)


def parse(text):
    files = []
    cur = None
    hunk = None
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            m = re.match(r"^diff --git a/(.*) b/(.*)$", line)
            cur = FileDiff(m.group(1), m.group(2)) if m else FileDiff("?", "?")
            files.append(cur)
            hunk = None
            continue
        if cur is None:
            continue
        if hunk is None or not line[:1] in (" ", "+", "-", "\\"):
            if line.startswith("new file mode"):
                cur.status = "A"
            elif line.startswith("deleted file mode"):
                cur.status = "D"
            elif line.startswith("rename from "):
                cur.status = "R"
                cur.old_path = line[len("rename from "):]
            elif line.startswith("rename to "):
                cur.new_path = line[len("rename to "):]
            elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
                cur.binary = True
            elif line.startswith("--- ") or line.startswith("+++ "):
                pass
            m = _HUNK.match(line)
            if m:
                hunk = Hunk(int(m.group(1)), int(m.group(2) or 1),
                            int(m.group(3)), int(m.group(4) or 1), m.group(5))
                cur.hunks.append(hunk)
            continue
        if line.startswith("\\"):
            continue
        hunk.lines.append((line[0], line[1:]))
    return files
