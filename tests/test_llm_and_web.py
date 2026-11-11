import json

import pytest

from pr_reviewer.llm import parse_json_value
from pr_reviewer.review import Comment
from pr_reviewer.webapp import diff_html, list_samples, load_sample, summary_markdown
from pr_reviewer.review import Review, Summary


def test_parse_json_value_accepts_fences_and_trailing_commas():
    text = "Sure.\n```json\n{\"comments\": [{\"line\": 2,}],}\n```"
    assert parse_json_value(text) == {"comments": [{"line": 2}]}


def test_parse_json_value_rejects_prose():
    with pytest.raises(ValueError):
        parse_json_value("no json here")


def test_diff_html_escapes_and_places_the_comment():
    diff = """\
diff --git a/picker.py b/picker.py
new file mode 100644
--- /dev/null
+++ b/picker.py
@@ -0,0 +1,2 @@
+def pick(bins, index):
+    return bins[index] <script>
"""
    html = diff_html(diff, [Comment("picker.py", 2, "RIGHT", "error", "correctness", "unchecked <index>")], [])
    assert "ms-comment" in html
    assert "unchecked &lt;index&gt;" in html
    assert "<script>" not in html
    assert "picker.py" in html


def test_samples_match_their_needles(samples):
    from pr_reviewer.diffparse import parse_diff
    from pr_reviewer.rules import Rules, is_ignored

    names = list_samples()
    assert "picker-index" in names
    assert "docs-only" in names
    rules = Rules()
    for name in names:
        diff, title = load_sample(name)
        truth = json.loads((samples / f"{name}.truth.json").read_text(encoding="utf-8"))
        if truth.get("pr_title"):
            assert title == truth["pr_title"]
        files = {file.path: file for file in parse_diff(diff)}
        if truth.get("ignored"):
            assert all(is_ignored(path, rules.ignore) for path in files)
            assert truth["expected"] == []
            continue
        for finding in truth["expected"]:
            file = files[finding["path"]]
            hits = [
                line for hunk in file.hunks for line in hunk.lines
                if line.new_line == finding["line"] and finding["needle"] in line.text
            ]
            assert hits, finding


def test_summary_markdown_lists_the_three_sections():
    review = Review(
        comments=[],
        summary=Summary("Adds a helper.", ["None reported."], ["Cover the new function."], "model"),
        model="m",
        backend="hf",
    )
    text = summary_markdown(review)
    assert "What changed" in text
    assert "Adds a helper." in text
    assert "Cover the new function." in text


def test_web_app_builds():
    pytest.importorskip("gradio")
    from pr_reviewer.config import Settings
    from pr_reviewer.webapp import build_app

    demo = build_app(Settings(backend="hf", hf_model="Qwen/Qwen2.5-Coder-1.5B-Instruct"))
    assert demo is not None
