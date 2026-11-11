"""Fetch a pull request diff and post inline review comments.

Uses the GitHub REST API. Inline comments are sent as one pull request review
so they sit on the diff. If GitHub rejects the batch, each comment is posted
on its own and the summary is sent as the review body.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

import httpx

from .review import Review, render_comment, render_summary

API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


@dataclass
class PullRequest:
    repo: str
    number: int
    title: str
    body: str
    head_sha: str
    head_ref: str
    base_ref: str
    html_url: str
    diff: str


def github_token() -> str:
    """Token from the environment, or from ``gh auth token`` when that works."""
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=False)
    except OSError:
        result = None
    if result is not None and result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    raise GitHubError("Set GITHUB_TOKEN to read the pull request and post review comments.")


def github_client(token: str) -> httpx.Client:
    return httpx.Client(
        base_url=API,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "pr-reviewer",
        },
        timeout=60,
    )


def _message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return ""
    if isinstance(payload, dict):
        return str(payload.get("message") or "")[:300]
    return ""


def _check(response: httpx.Response) -> httpx.Response:
    if response.status_code >= 400:
        detail = _message(response)
        extra = f" {detail}" if detail else ""
        raise GitHubError(f"GitHub HTTP {response.status_code}.{extra}")
    return response


def fetch_pull(repo: str, number: int, token: str, client: httpx.Client | None = None) -> PullRequest:
    own = client is None
    client = client or github_client(token)
    try:
        meta = _check(client.get(f"/repos/{repo}/pulls/{number}"))
        data = meta.json()
        diff = _check(client.get(
            f"/repos/{repo}/pulls/{number}",
            headers={"Accept": "application/vnd.github.diff"},
        ))
        head = data.get("head") or {}
        return PullRequest(
            repo=repo,
            number=number,
            title=str(data.get("title") or ""),
            body=str(data.get("body") or ""),
            head_sha=str(head.get("sha") or ""),
            head_ref=str(head.get("ref") or ""),
            base_ref=str((data.get("base") or {}).get("ref") or ""),
            html_url=str(data.get("html_url") or ""),
            diff=diff.text,
        )
    finally:
        if own:
            client.close()


def fetch_file(repo: str, path: str, ref: str, token: str, client: httpx.Client | None = None) -> str | None:
    """Return a file from the repository, or None when it is absent."""
    own = client is None
    client = client or github_client(token)
    try:
        response = client.get(
            f"/repos/{repo}/contents/{path}",
            params={"ref": ref},
            headers={"Accept": "application/vnd.github.raw"},
        )
        if response.status_code == 404:
            return None
        _check(response)
        return response.text
    finally:
        if own:
            client.close()


def _comment_payload(review: Review) -> list[dict]:
    return [
        {
            "path": comment.path,
            "body": render_comment(comment),
            "line": comment.line,
            "side": comment.side,
        }
        for comment in review.comments
    ]


def post_review(
    pull: PullRequest,
    review: Review,
    token: str,
    *,
    client: httpx.Client | None = None,
) -> dict:
    """Post ``review`` on ``pull``. Returns the GitHub review payload plus how it was sent."""
    if not pull.head_sha:
        raise GitHubError("the pull request has no head SHA, so inline comments cannot be posted")
    own = client is None
    client = client or github_client(token)
    summary = render_summary(review, pr_url=pull.html_url).rstrip()
    try:
        batch = {
            "commit_id": pull.head_sha,
            "body": summary,
            "event": "COMMENT",
        }
        inline = _comment_payload(review)
        if inline:
            batch["comments"] = inline
        response = client.post(f"/repos/{pull.repo}/pulls/{pull.number}/reviews", json=batch)
        if response.status_code < 400:
            payload = response.json()
            return {
                "id": payload.get("id"),
                "html_url": payload.get("html_url") or pull.html_url,
                "inline_count": len(inline),
                "mode": "batch",
            }
        if response.status_code != 422 or not inline:
            _check(response)
        posted = 0
        failed: list[str] = []
        for comment in review.comments:
            one = client.post(
                f"/repos/{pull.repo}/pulls/{pull.number}/comments",
                json={
                    "body": render_comment(comment),
                    "commit_id": pull.head_sha,
                    "path": comment.path,
                    "line": comment.line,
                    "side": comment.side,
                },
            )
            if one.status_code < 400:
                posted += 1
            else:
                failed.append(f"{comment.path}:{comment.line} HTTP {one.status_code}")
        summary_response = _check(client.post(
            f"/repos/{pull.repo}/pulls/{pull.number}/reviews",
            json={"commit_id": pull.head_sha, "body": summary, "event": "COMMENT"},
        ))
        payload = summary_response.json()
        return {
            "id": payload.get("id"),
            "html_url": payload.get("html_url") or pull.html_url,
            "inline_count": posted,
            "mode": "individual",
            "failed": failed,
        }
    finally:
        if own:
            client.close()
