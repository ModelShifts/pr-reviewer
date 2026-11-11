import json
import os
from pathlib import Path

from pr_reviewer.cli import main
from pr_reviewer.github import PullRequest

DIFF = """\
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

FILE_REPLY = json.dumps({"comments": [
    {"line": 2, "side": "RIGHT", "severity": "error", "category": "correctness",
     "body": "index <= len(bins) is past the end."}
]})
SUMMARY = json.dumps({
    "what_changed": "Adds pick.",
    "risks": ["IndexError on the last index."],
    "suggested_tests": ["Call pick at len(bins)."],
})


def test_review_diff_writes_json(tmp_path, monkeypatch, capsys, fake_llm):
    diff = tmp_path / "change.diff"
    diff.write_text(DIFF, encoding="utf-8")
    out = tmp_path / "review.json"
    llm = fake_llm([FILE_REPLY, SUMMARY])
    monkeypatch.setattr("pr_reviewer.review.get_llm", lambda settings: llm)
    monkeypatch.setenv("MS_BACKEND", "hf")
    code = main(["review", "--diff", str(diff), "--out", str(out), "--json", "--config", str(_rules(tmp_path))])
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["comments"][0]["line"] == 2
    assert "Adds pick." in capsys.readouterr().out


def test_missing_api_settings_exit_2(tmp_path, monkeypatch, capsys):
    diff = tmp_path / "change.diff"
    diff.write_text(DIFF, encoding="utf-8")
    monkeypatch.setenv("MS_BACKEND", "api")
    monkeypatch.delenv("MS_API_BASE", raising=False)
    monkeypatch.delenv("MS_MODEL", raising=False)
    # A developer .env must not satisfy this test.
    monkeypatch.setattr("pr_reviewer.config.load_dotenv_if_present", lambda path=None: None)
    code = main(["review", "--diff", str(diff)])
    assert code == 2
    assert "MS_API_BASE" in capsys.readouterr().err


def test_action_posts_the_review(tmp_path, monkeypatch, capsys, fake_llm):
    event = {
        "pull_request": {
            "number": 7,
            "title": "Fix the picker",
            "body": "",
        }
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    rules = _rules(tmp_path)
    pull = PullRequest(
        repo="acme/widgets", number=7, title="Fix the picker", body="",
        head_sha="abc", head_ref="fix", base_ref="main",
        html_url="https://github.com/acme/widgets/pull/7", diff=DIFF,
    )
    posted = {}

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/widgets")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("PR_REVIEWER_CONFIG", rules.name)
    monkeypatch.setenv("MS_BACKEND", "hf")
    monkeypatch.setattr("pr_reviewer.cli.fetch_pull", lambda repo, number, token: pull)
    monkeypatch.setattr("pr_reviewer.review.get_llm", lambda settings: fake_llm([FILE_REPLY, SUMMARY]))

    def capture(pull, review, token, client=None):
        posted["review"] = review
        posted["sha"] = pull.head_sha
        return {"id": 1, "html_url": pull.html_url + "#review", "inline_count": len(review.comments), "mode": "batch"}

    monkeypatch.setattr("pr_reviewer.cli.post_review", capture)
    code = main([])
    assert code == 0
    assert posted["sha"] == "abc"
    assert posted["review"].comments[0].path == "picker.py"
    assert "posted review" in capsys.readouterr().out


def test_version(capsys):
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    assert "pr-reviewer" in capsys.readouterr().out


def _rules(directory: Path) -> Path:
    path = directory / "rules.yml"
    path.write_text(
        "strictness: normal\nfocus: [correctness, security, tests]\nignore: ['docs/**']\nmax_comments: 20\n"
        "jira:\n  enabled: false\n  send: false\n",
        encoding="utf-8",
    )
    # Keep the name stable for the action test, which joins workspace / config name.
    os.environ.pop("PR_REVIEWER_CONFIG", None)
    return path
