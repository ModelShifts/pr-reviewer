import json

import httpx

from pr_reviewer.github import fetch_pull, post_review
from pr_reviewer.review import Comment, Review, Summary

DIFF = """\
diff --git a/picker.py b/picker.py
--- /dev/null
+++ b/picker.py
@@ -0,0 +1,2 @@
+def pick(bins, index):
+    return bins[index]
"""


def _review() -> Review:
    return Review(
        comments=[Comment("picker.py", 2, "RIGHT", "error", "correctness", "Index is not checked.")],
        summary=Summary("Adds pick.", ["The index is unchecked."], ["Pass an in-range index."], "model"),
        model="fake-model",
        backend="hf",
    )


def test_fetch_and_post_batch():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/repos/example/repo/pulls/3":
            if request.headers["accept"].startswith("application/vnd.github.diff"):
                return httpx.Response(200, text=DIFF)
            return httpx.Response(200, json={
                "title": "KAN-4 Fix the picker",
                "body": "",
                "html_url": "https://github.com/example/repo/pull/3",
                "head": {"sha": "abc123", "ref": "feature/KAN-4-picker"},
                "base": {"ref": "main"},
            })
        if request.method == "POST" and request.url.path.endswith("/reviews"):
            seen["body"] = json.loads(request.content)
            return httpx.Response(201, json={"id": 9, "html_url": "https://github.com/example/repo/pull/3#pullrequestreview-9"})
        return httpx.Response(404, json={"message": "missing"})

    client = httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler))
    pull = fetch_pull("example/repo", 3, "token", client=client)
    assert pull.head_sha == "abc123"
    assert pull.head_ref == "feature/KAN-4-picker"
    assert "def pick" in pull.diff
    posted = post_review(pull, _review(), "token", client=client)
    assert posted["mode"] == "batch"
    assert posted["inline_count"] == 1
    comment = seen["body"]["comments"][0]
    assert comment == {
        "path": "picker.py",
        "body": "**correctness · error**\n\nIndex is not checked.",
        "line": 2,
        "side": "RIGHT",
    }
    assert seen["body"]["commit_id"] == "abc123"
    assert seen["body"]["event"] == "COMMENT"
    assert "What changed" in seen["body"]["body"]
    assert "Adds pick." in seen["body"]["body"]


def test_post_falls_back_when_the_batch_is_rejected():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/reviews"):
            payload = json.loads(request.content)
            calls.append(("review", payload))
            if payload.get("comments"):
                return httpx.Response(422, json={"message": "Validation Failed"})
            return httpx.Response(201, json={"id": 11, "html_url": "https://github.com/example/repo/pull/3#pullrequestreview-11"})
        if request.url.path.endswith("/comments"):
            calls.append(("comment", json.loads(request.content)))
            return httpx.Response(201, json={"id": 4})
        return httpx.Response(404, json={"message": "missing"})

    client = httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler))
    from pr_reviewer.github import PullRequest

    pull = PullRequest("example/repo", 3, "title", "", "abc123", "branch", "main",
                       "https://github.com/example/repo/pull/3", DIFF)
    posted = post_review(pull, _review(), "token", client=client)
    assert posted["mode"] == "individual"
    assert posted["inline_count"] == 1
    assert calls[1][0] == "comment"
    assert calls[1][1]["line"] == 2
    assert calls[2][0] == "review"
    assert "comments" not in calls[2][1]
