"""Command-line interface.

    pr-reviewer review --diff samples/diffs/picker-index.diff
    pr-reviewer review --repo OWNER/REPO --pr 123 --post
    pr-reviewer post review.json --repo OWNER/REPO --pr 123
    pr-reviewer serve
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .config import Settings
from .github import GitHubError, PullRequest, fetch_file, fetch_pull, github_token, post_review
from .review import Review, review_diff
from .rules import load_rules, load_rules_text, resolve_rules_path


def _settings() -> Settings:
    settings = Settings.from_env()
    settings.validate()
    return settings


def _rules(path: str | None):
    resolved = resolve_rules_path(path)
    if path and (resolved is None or not resolved.is_file()):
        raise FileNotFoundError(f"rules file not found: {path}")
    return load_rules(resolved) if resolved else load_rules(None)


def _print_human(review: Review) -> None:
    if not review.comments:
        print("No inline comments.")
    for comment in review.comments:
        print(f"{comment.path}:{comment.line}  {comment.side}  {comment.category}  {comment.severity}")
        print(f"  {comment.body}")
        print()
    summary = review.summary
    print("Summary")
    print(f"  What changed: {summary.what_changed}")
    print("  Risks:")
    for item in summary.risks:
        print(f"  - {item}")
    print("  Suggested tests:")
    for item in summary.suggested_tests:
        print(f"  - {item}")
    if summary.source == "fallback":
        print("  (summary assembled from the diff; the model reply was not usable)")
    print()
    print(
        f"{len(review.comments)} inline comments · {review.backend} · {review.model} · "
        f"jira {review.jira.get('status', 'disabled')}"
    )
    if review.files_ignored:
        print("ignored: " + ", ".join(review.files_ignored))
    if review.parse_failures:
        print(f"note: {review.parse_failures} model reply could not be parsed", file=sys.stderr)


def _write_out(review: Review, path: str | None) -> None:
    if not path:
        return
    Path(path).write_text(json.dumps(review.to_dict(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}", file=sys.stderr)


def _review_text(diff: str, rules, settings: Settings, args, *, pull: PullRequest | None = None) -> Review:
    return review_diff(
        diff,
        settings,
        rules,
        pr_title=pull.title if pull else (args.title or ""),
        pr_body=pull.body if pull else "",
        head_ref=pull.head_ref if pull else (args.head_ref or ""),
        pr_url=pull.html_url if pull else "",
    )


def cmd_review(args: argparse.Namespace) -> int:
    settings = _settings()
    rules = _rules(args.config)
    pull = None
    if args.repo or args.pr:
        if not (args.repo and args.pr):
            raise ValueError("pass both --repo OWNER/REPO and --pr NUMBER")
        pull = fetch_pull(args.repo, args.pr, github_token())
        diff = pull.diff
    else:
        if not args.diff:
            raise ValueError("pass --diff FILE or --repo OWNER/REPO --pr NUMBER")
        diff = sys.stdin.read() if args.diff == "-" else Path(args.diff).read_text(encoding="utf-8")
    review = _review_text(diff, rules, settings, args, pull=pull)
    _write_out(review, args.out)
    if args.json:
        print(json.dumps(review.to_dict(), indent=2))
    else:
        _print_human(review)
    if args.post:
        if pull is None:
            raise ValueError("--post needs --repo and --pr")
        posted = post_review(pull, review, github_token())
        print(f"posted review: {posted.get('html_url')} ({posted.get('inline_count')} inline, {posted.get('mode')})")
        failed = posted.get("failed") or []
        for item in failed:
            print(f"not posted: {item}", file=sys.stderr)
    return 0


def cmd_post(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    review = Review.from_dict(data)
    pull = fetch_pull(args.repo, args.pr, github_token())
    posted = post_review(pull, review, github_token())
    print(f"posted review: {posted.get('html_url')} ({posted.get('inline_count')} inline, {posted.get('mode')})")
    for item in posted.get("failed") or []:
        print(f"not posted: {item}", file=sys.stderr)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .webapp import launch

    launch(host=args.host, port=args.port, share=False)
    return 0


def cmd_action() -> int:
    """Entry point used by the composite GitHub Action (no CLI arguments)."""
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if event_name not in {"pull_request", "pull_request_target"}:
        print(f"pr-reviewer: event is {event_name or 'unset'}, skipping")
        return 0
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        raise ValueError("GITHUB_EVENT_PATH is not set")
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pr = event.get("pull_request") or {}
    number = pr.get("number")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo or not number:
        raise ValueError("the event has no pull request number")
    token = github_token()
    pull = fetch_pull(repo, int(number), token)
    config_name = os.environ.get("PR_REVIEWER_CONFIG", ".github/pr-reviewer.yml")
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", "."))
    local = workspace / config_name
    if local.is_file():
        rules = load_rules(local)
    else:
        text = fetch_file(repo, config_name, pull.head_sha, token)
        rules = load_rules_text(text) if text is not None else load_rules(None)
        if text is None:
            print(f"pr-reviewer: {config_name} not found, using built-in rules", file=sys.stderr)
    if os.environ.get("PR_REVIEWER_DRY_RUN", "").lower() in {"1", "true", "yes"}:
        rules.jira.send = False
    settings = _settings()
    review = review_diff(
        pull.diff,
        settings,
        rules,
        pr_title=pull.title,
        pr_body=pull.body,
        head_ref=pull.head_ref,
        pr_url=pull.html_url,
        jira_send=False if os.environ.get("PR_REVIEWER_DRY_RUN", "").lower() in {"1", "true", "yes"} else None,
    )
    print(render_text(review))
    if os.environ.get("PR_REVIEWER_DRY_RUN", "").lower() in {"1", "true", "yes"}:
        print("pr-reviewer: dry run, review was not posted")
        return 0
    posted = post_review(pull, review, token)
    print(f"posted review: {posted.get('html_url')} ({posted.get('inline_count')} inline, {posted.get('mode')})")
    return 0


def render_text(review: Review) -> str:
    """Plain-text form of a review, used by the action log."""
    lines = []
    for comment in review.comments:
        lines.append(f"{comment.path}:{comment.line} {comment.side} {comment.category}: {comment.body}")
    lines.append(review.summary.what_changed)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pr-reviewer",
        description="A GitHub Action that reviews pull requests and leaves comments on the diff.",
    )
    parser.add_argument("--version", action="version", version=f"pr-reviewer {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    review = sub.add_parser("review", help="review a diff or a pull request")
    review.add_argument("--diff", help="unified diff file, or - for stdin")
    review.add_argument("--repo", help="OWNER/REPO, used with --pr")
    review.add_argument("--pr", type=int, help="pull request number")
    review.add_argument("--config", help="rules file (default: .github/pr-reviewer.yml)")
    review.add_argument("--title", help="pull request title, used to find a Jira issue key")
    review.add_argument("--head-ref", help="head branch name, used to find a Jira issue key")
    review.add_argument("--out", help="write the review JSON here")
    review.add_argument("--json", action="store_true", help="print the review as JSON")
    review.add_argument("--post", action="store_true", help="post the review on the pull request")
    review.set_defaults(func=cmd_review)

    post = sub.add_parser("post", help="post a review JSON file on a pull request")
    post.add_argument("file", help="review JSON from `pr-reviewer review --out`")
    post.add_argument("--repo", required=True, help="OWNER/REPO")
    post.add_argument("--pr", type=int, required=True, help="pull request number")
    post.set_defaults(func=cmd_post)

    serve = sub.add_parser("serve", help="start the local web demo (Gradio)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=7860)
    serve.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv and os.environ.get("GITHUB_ACTIONS") == "true":
        try:
            return cmd_action()
        except (GitHubError, ValueError, RuntimeError, FileNotFoundError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1 if isinstance(exc, GitHubError) else 2
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except GitHubError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (ValueError, RuntimeError, FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
