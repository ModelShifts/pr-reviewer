from pr_reviewer.diffparse import commentable, parse_diff

NEW_FILE = """\
diff --git a/picker.py b/picker.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/picker.py
@@ -0,0 +1,3 @@
+def pick(bins, index):
+    if index <= len(bins):
+        return bins[index]
"""

EDIT = "\n".join([
    "diff --git a/billing.py b/billing.py",
    "index 2222222..3333333 100644",
    "--- a/billing.py",
    "+++ b/billing.py",
    "@@ -3,3 +3,3 @@ def apply_discount(price, percent):",
    "     if percent < 0:",
    "-        return price * (100 - percent) / 100",
    "+        return price - price / percent",
    "     return price",
]) + "\n"


def test_new_file_line_numbers():
    files = parse_diff(NEW_FILE)
    assert len(files) == 1
    file = files[0]
    assert file.path == "picker.py"
    assert file.status == "added"
    lines = [line for hunk in file.hunks for line in hunk.lines]
    assert [(line.new_line, line.text) for line in lines] == [
        (1, "def pick(bins, index):"),
        (2, "    if index <= len(bins):"),
        (3, "        return bins[index]"),
    ]
    assert (2, "RIGHT") in commentable(file)
    assert (2, "LEFT") not in commentable(file)


def test_edit_tracks_both_sides():
    file = parse_diff(EDIT)[0]
    assert file.status == "modified"
    indexed = commentable(file)
    deleted = indexed[(4, "LEFT")]
    added = indexed[(4, "RIGHT")]
    assert deleted.kind == "del"
    assert "100 - percent" in deleted.text
    assert added.kind == "add"
    assert "/" in added.text
    # The context line under the change keeps both numbers.
    assert indexed[(5, "RIGHT")].kind == "ctx"
    assert indexed[(5, "LEFT")].text == "    return price"


def test_rename_binary_and_dev_null():
    text = """\
diff --git a/old.py b/new.py
similarity index 90%
rename from old.py
rename to new.py
--- a/old.py
+++ b/new.py
@@ -1 +1 @@
-print(1)
+print(2)
diff --git a/pic.bin b/pic.bin
new file mode 100644
index 0000000..1111111
Binary files /dev/null and b/pic.bin differ
"""
    files = parse_diff(text)
    assert [file.path for file in files] == ["new.py", "pic.bin"]
    assert files[0].status == "renamed"
    assert files[0].old_path == "old.py"
    assert files[1].is_binary
    assert commentable(files[1]) == {}
