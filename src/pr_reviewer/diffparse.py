"""Parse a unified diff into files, hunks and commentable line numbers.

Line numbers match the file, which is what the GitHub review API expects:
``RIGHT`` is a line in the new file, ``LEFT`` is a line in the old file.
A line can take a comment when it appears in a hunk (added, removed or context).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class DiffLine:
    kind: str  # add | del | ctx
    text: str
    old_line: int | None
    new_line: int | None


@dataclass
class Hunk:
    old_start: int
    new_start: int
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class FileDiff:
    old_path: str
    new_path: str
    status: str  # added | deleted | modified | renamed
    hunks: list[Hunk] = field(default_factory=list)
    is_binary: bool = False

    @property
    def path(self) -> str:
        """Path to use when posting a review comment."""
        if self.status == "deleted":
            return self.old_path
        return self.new_path


def _strip_ab(path: str) -> str:
    if path in {"/dev/null", "dev/null"}:
        return "/dev/null"
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def parse_diff(text: str) -> list[FileDiff]:
    """Parse ``text`` as a unified diff. Returns one entry per file."""
    files: list[FileDiff] = []
    current: FileDiff | None = None
    hunk: Hunk | None = None
    old_no = 0
    new_no = 0

    def start_file() -> FileDiff:
        nonlocal current, hunk
        current = FileDiff(old_path="", new_path="", status="modified")
        files.append(current)
        hunk = None
        return current

    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            current = start_file()
            rest = raw[len("diff --git "):].strip()
            if rest.startswith("a/") and " b/" in rest:
                left, right = rest[2:].split(" b/", 1)
                current.old_path = left
                current.new_path = right
            continue
        if current is None:
            # A bare unified diff with no git header.
            if raw.startswith("--- "):
                start_file()
            else:
                continue
        if raw.startswith("new file mode"):
            current.status = "added"
            continue
        if raw.startswith("deleted file mode"):
            current.status = "deleted"
            continue
        if raw.startswith("rename from "):
            current.old_path = raw[len("rename from "):].strip()
            current.status = "renamed"
            continue
        if raw.startswith("rename to "):
            current.new_path = raw[len("rename to "):].strip()
            current.status = "renamed"
            continue
        if raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
            current.is_binary = True
            hunk = None
            continue
        if raw.startswith("--- "):
            old = _strip_ab(raw[4:].split("\t", 1)[0].strip())
            current.old_path = "" if old == "/dev/null" else old
            if old == "/dev/null":
                current.status = "added"
            hunk = None
            continue
        if raw.startswith("+++ "):
            new = _strip_ab(raw[4:].split("\t", 1)[0].strip())
            current.new_path = "" if new == "/dev/null" else new
            if new == "/dev/null":
                current.status = "deleted"
            hunk = None
            continue
        match = _HUNK.match(raw)
        if match:
            old_start = int(match.group(1))
            new_start = int(match.group(3))
            hunk = Hunk(old_start=old_start, new_start=new_start)
            current.hunks.append(hunk)
            old_no = old_start
            new_no = new_start
            continue
        if hunk is None:
            continue
        if raw.startswith("\\"):
            # "\ No newline at end of file"
            continue
        if raw.startswith("+"):
            hunk.lines.append(DiffLine("add", raw[1:], None, new_no))
            new_no += 1
        elif raw.startswith("-"):
            hunk.lines.append(DiffLine("del", raw[1:], old_no, None))
            old_no += 1
        else:
            # Context lines start with a space. A completely empty line is also context.
            text_line = raw[1:] if raw.startswith(" ") else raw
            hunk.lines.append(DiffLine("ctx", text_line, old_no, new_no))
            old_no += 1
            new_no += 1

    for item in files:
        if not item.new_path and item.old_path:
            item.new_path = item.old_path
        if not item.old_path and item.new_path and item.status != "added":
            item.old_path = item.new_path
    return [item for item in files if item.path]


def commentable(file: FileDiff) -> dict[tuple[int, str], DiffLine]:
    """Map ``(line, side)`` to the diff line. ``side`` is ``LEFT`` or ``RIGHT``."""
    out: dict[tuple[int, str], DiffLine] = {}
    for hunk in file.hunks:
        for line in hunk.lines:
            if line.new_line is not None and line.kind in {"add", "ctx"}:
                out[(line.new_line, "RIGHT")] = line
            if line.old_line is not None and line.kind in {"del", "ctx"}:
                out[(line.old_line, "LEFT")] = line
    return out


def changed_counts(file: FileDiff) -> tuple[int, int]:
    added = deleted = 0
    for hunk in file.hunks:
        for line in hunk.lines:
            if line.kind == "add":
                added += 1
            elif line.kind == "del":
                deleted += 1
    return added, deleted
