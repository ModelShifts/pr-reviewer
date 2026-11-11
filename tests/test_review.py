import json

from pr_reviewer.jira_link import find_issue_key
from pr_reviewer.review import review_diff
from pr_reviewer.rules import Rules, JiraRules

DIFF = """\
diff --git a/picker.py b/picker.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/picker.py
@@ -0,0 +1,4 @@
+def pick(bins, index):
+    if index <= len(bins):
+        return bins[index]
+    return None
"""

DOCS = """\
diff --git a/docs/guide.md b/docs/guide.md
index 2222222..3333333 100644
--- a/docs/guide.md
+++ b/docs/guide.md
@@ -1,3 +1,3 @@
 # Guide
 
-The picker returns a bin.
+The picker returns the first bin.
"""

FILE_REPLY = json.dumps({
    "comments": [
        {"line": 2, "side": "RIGHT", "severity": "error", "category": "correctness",
         "body": "index <= len(bins) reads past the last bin."},
        {"line": 3, "side": "RIGHT", "severity": "warning", "category": "correctness",
         "body": "This return is only safe when the check is fixed."},
        {"line": 4, "side": "RIGHT", "severity": "note", "category": "tests",
         "body": "Add a test for the last index."},
        {"line": 99, "side": "RIGHT", "severity": "error", "category": "correctness",
         "body": "This line is not in the diff."},
        {"line": 2, "side": "RIGHT", "severity": "error", "category": "style",
         "body": "Rename the function."},
    ]
})

SUMMARY = json.dumps({
    "what_changed": "Adds pick.",
    "risks": ["The index check can raise IndexError."],
    "suggested_tests": ["Call pick with index equal to len(bins)."],
})


def test_comments_land_on_diff_lines_and_follow_rules(settings, fake_llm):
    llm = fake_llm([FILE_REPLY, SUMMARY])
    review = review_diff(DIFF, settings, Rules(), llm=llm)
    assert [(c.line, c.severity) for c in review.comments] == [(2, "error"), (3, "warning")]
    assert review.dropped == 3
    assert review.summary.source == "model"
    assert review.summary.what_changed == "Adds pick."
    assert review.parse_failures == 0
    assert "picker.py" in llm.prompts[0][1]["content"]
    assert "index <=" in llm.prompts[0][1]["content"] or "len(bins)" in llm.prompts[0][1]["content"]


def test_only_side_in_the_diff_is_used(settings, fake_llm):
    reply = json.dumps({"comments": [{
        "line": 2, "side": "LEFT", "severity": "error", "category": "correctness",
        "body": "index <= len(bins) reads past the end.",
    }]})
    review = review_diff(DIFF, settings, Rules(), llm=fake_llm([reply, SUMMARY]))
    assert [(c.line, c.side, c.body[:5]) for c in review.comments] == [(2, "RIGHT", "index")]


def test_replaced_line_is_commented_on_the_new_side(settings, fake_llm, samples):
    diff = (samples / "discount-formula.diff").read_text(encoding="utf-8")
    reply = json.dumps({"comments": [{
        "line": 5, "side": "LEFT", "severity": "error", "category": "correctness",
        "body": "The new code does not correctly apply the discount.",
    }]})
    review = review_diff(diff, settings, Rules(), llm=fake_llm([reply, SUMMARY]))
    assert [(c.line, c.side) for c in review.comments] == [(5, "RIGHT")]


def test_relaxed_keeps_one_error(settings, fake_llm):
    llm = fake_llm([FILE_REPLY, SUMMARY])
    rules = Rules(strictness="relaxed")
    review = review_diff(DIFF, settings, rules, llm=llm)
    assert len(review.comments) == 1
    assert review.comments[0].severity == "error"
    assert review.comments[0].line == 2


def test_strict_keeps_a_test_note(settings, fake_llm):
    llm = fake_llm([FILE_REPLY, SUMMARY])
    review = review_diff(DIFF, settings, Rules(strictness="strict"), llm=llm)
    assert any(comment.category == "tests" for comment in review.comments)


def test_focus_filters_categories(settings, fake_llm):
    llm = fake_llm([FILE_REPLY, SUMMARY])
    review = review_diff(DIFF, settings, Rules(focus=["security"]), llm=llm)
    assert review.comments == []


def test_ignored_files_are_not_sent_to_the_model(settings, fake_llm):
    llm = fake_llm([SUMMARY])
    review = review_diff(DOCS, settings, Rules(), llm=llm)
    assert review.comments == []
    assert review.files_ignored == ["docs/guide.md"]
    assert review.files_reviewed == []
    assert llm.prompts == []
    assert review.summary.source == "fallback"


def test_bad_json_is_retried_then_counted(settings, fake_llm):
    llm = fake_llm(["not json", "still not json", SUMMARY])
    review = review_diff(DIFF, settings, Rules(), llm=llm)
    assert review.comments == []
    assert review.parse_failures == 1
    assert review.summary.source == "model"


def test_max_comments(settings, fake_llm):
    llm = fake_llm([FILE_REPLY, SUMMARY])
    review = review_diff(DIFF, settings, Rules(max_comments=1), llm=llm)
    assert len(review.comments) == 1
    assert review.comments[0].severity == "error"


class FakeJira:
    def __init__(self):
        self.fetched = []
        self.reports = []

    def fetch(self, key):
        self.fetched.append(key)
        return {
            "key": key,
            "summary": "Picker must not read past the end",
            "status": "To Do",
            "description": "The last bin must be readable.",
            "url": "https://example.atlassian.net/browse/" + key,
        }

    def report(self, key, text, send=False):
        self.reports.append((key, text, send))
        return {"status": "reported" if send else "preview", "issue": key, "comment": text}


def test_jira_task_is_in_the_prompt_and_the_report_is_previewed(settings, fake_llm):
    llm = fake_llm([FILE_REPLY, SUMMARY])
    bridge = FakeJira()
    rules = Rules(jira=JiraRules(enabled=True, send=False))
    review = review_diff(
        DIFF, settings, rules, llm=llm,
        pr_title="KAN-4 Fix the picker",
        pr_url="https://github.com/example/repo/pull/4",
        jira_client=bridge,
    )
    assert bridge.fetched == ["KAN-4"]
    assert "Picker must not read past the end" in llm.prompts[0][1]["content"]
    assert review.jira["status"] == "preview"
    assert review.jira["issue"] == "KAN-4"
    key, text, send = bridge.reports[0]
    assert key == "KAN-4" and send is False
    assert "What changed" in text
    assert review.comments


def test_jira_send_flag(settings, fake_llm):
    llm = fake_llm([FILE_REPLY, SUMMARY])
    bridge = FakeJira()
    rules = Rules(jira=JiraRules(enabled=True, send=True))
    review = review_diff(DIFF, settings, rules, llm=llm, head_ref="feature/KAN-4-picker", jira_client=bridge)
    assert bridge.reports[0][2] is True
    assert review.jira["status"] == "reported"


def test_jira_without_a_client_still_reviews(settings, fake_llm, monkeypatch):
    llm = fake_llm([FILE_REPLY, SUMMARY])
    monkeypatch.setattr("pr_reviewer.jira_link.load_jira_client", lambda: (None, "jira-bridge is not installed"))
    rules = Rules(jira=JiraRules(enabled=True, send=False))
    review = review_diff(DIFF, settings, rules, llm=llm, pr_title="KAN-4 Fix the picker")
    assert review.comments
    assert review.jira["status"] == "skipped"
    assert "not installed" in review.jira["reason"]
    assert "KAN-4" == review.jira["issue"]


def test_issue_key_order():
    assert find_issue_key("no key", "feature/ABC-12-name", "body ZZ-9") == "ABC-12"
    assert find_issue_key("", "", "") is None
