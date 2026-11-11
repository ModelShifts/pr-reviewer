"""Review a unified diff: inline comments on diff lines, plus one summary."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Settings
from .diffparse import FileDiff, changed_counts, commentable, parse_diff
from .jira_link import JiraBridge, deliver_report, prepare_jira
from .llm import LLM, get_llm, parse_json_value
from .rules import Rules, is_ignored

_CATEGORY_ALIASES = {
    "correctness": "correctness",
    "bug": "correctness",
    "logic": "correctness",
    "error": "correctness",
    "security": "security",
    "injection": "security",
    "secret": "security",
    "tests": "tests",
    "test": "tests",
    "testing": "tests",
}

_STRICTNESS_GUIDE = {
    "relaxed": "Report only a definite bug that will crash or return a wrong result. "
               "Skip style, naming, and missing tests. At most one comment.",
    "normal": "Report definite bugs and concrete risks (crashes, wrong results, security holes). "
              "Skip style, naming, and comments whose only point is a missing test.",
    "strict": "Report bugs, security issues, and missing tests for the changed behaviour. "
              "Skip pure naming nits.",
}

_MAX_DIFF_LINES = 160
_MAX_BODY = 1200


@dataclass
class Comment:
    path: str
    line: int
    side: str
    severity: str
    category: str
    body: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "line": self.line,
            "side": self.side,
            "severity": self.severity,
            "category": self.category,
            "body": self.body,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Comment":
        return cls(
            path=str(data["path"]),
            line=int(data["line"]),
            side=str(data["side"]).upper(),
            severity=str(data["severity"]),
            category=str(data["category"]),
            body=str(data["body"]),
        )


@dataclass
class Summary:
    what_changed: str
    risks: list[str]
    suggested_tests: list[str]
    source: str  # model | fallback

    def to_dict(self) -> dict:
        return {
            "what_changed": self.what_changed,
            "risks": list(self.risks),
            "suggested_tests": list(self.suggested_tests),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Summary":
        return cls(
            what_changed=str(data.get("what_changed", "")),
            risks=[str(item) for item in data.get("risks") or []],
            suggested_tests=[str(item) for item in data.get("suggested_tests") or []],
            source=str(data.get("source", "model")),
        )


@dataclass
class Review:
    comments: list[Comment]
    summary: Summary
    model: str
    backend: str
    files_reviewed: list[str] = field(default_factory=list)
    files_ignored: list[str] = field(default_factory=list)
    files_skipped: list[str] = field(default_factory=list)
    dropped: int = 0
    parse_failures: int = 0
    jira: dict = field(default_factory=lambda: {"status": "disabled"})

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "backend": self.backend,
            "comments": [comment.to_dict() for comment in self.comments],
            "summary": self.summary.to_dict(),
            "files_reviewed": list(self.files_reviewed),
            "files_ignored": list(self.files_ignored),
            "files_skipped": list(self.files_skipped),
            "dropped": self.dropped,
            "parse_failures": self.parse_failures,
            "jira": self.jira,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Review":
        return cls(
            comments=[Comment.from_dict(item) for item in data.get("comments") or []],
            summary=Summary.from_dict(data.get("summary") or {}),
            model=str(data.get("model", "")),
            backend=str(data.get("backend", "")),
            files_reviewed=list(data.get("files_reviewed") or []),
            files_ignored=list(data.get("files_ignored") or []),
            files_skipped=list(data.get("files_skipped") or []),
            dropped=int(data.get("dropped") or 0),
            parse_failures=int(data.get("parse_failures") or 0),
            jira=dict(data.get("jira") or {"status": "disabled"}),
        )


def render_comment(comment: Comment) -> str:
    return f"**{comment.category} · {comment.severity}**\n\n{comment.body}"


def render_summary(review: Review, *, pr_url: str = "") -> str:
    """The single pull-request comment: what changed, risks, suggested tests."""
    summary = review.summary
    lines = ["### What changed", "", summary.what_changed, "", "### Risks", ""]
    lines.extend(f"- {item}" for item in summary.risks)
    lines.extend(["", "### Suggested tests", ""])
    lines.extend(f"- {item}" for item in summary.suggested_tests)
    if review.jira.get("status") not in {None, "disabled"}:
        lines.extend(["", "### Jira", "", _jira_line(review.jira)])
    if summary.source == "fallback":
        lines.extend(["", "The summary was assembled from the diff because the model reply was not usable."])
    footer = (
        f"pr-reviewer {_version()} · {review.backend} · {review.model} · "
        f"{len(review.comments)} inline comments"
    )
    lines.extend(["", "---", footer])
    if pr_url:
        lines.append(pr_url)
    return "\n".join(lines).strip() + "\n"


def render_jira_report(review: Review, *, pr_url: str = "") -> str:
    """Text handed to jira-bridge. The bridge adds its own marker."""
    lines = [render_summary(review, pr_url=pr_url).rstrip(), "", "Inline comments:"]
    if not review.comments:
        lines.append("- (none)")
    for comment in review.comments:
        lines.append(f"- {comment.path}:{comment.line} ({comment.side}, {comment.category}) {comment.body}")
    text = "\n".join(lines).strip()
    return text[:24000]


def _version() -> str:
    from . import __version__

    return __version__


def _jira_line(info: dict) -> str:
    issue = info.get("issue") or ""
    status = info.get("status") or ""
    reason = info.get("reason") or ""
    task = info.get("task") or {}
    summary = task.get("summary") if isinstance(task, dict) else ""
    bits = [bit for bit in (issue, summary, status, reason) if bit]
    return " — ".join(bits) if bits else status


def _system_prompt() -> dict[str, str]:
    return {
        "role": "system",
        "content": "You review code diffs. You reply with one JSON object and no other text.",
    }


def _format_file(file: FileDiff) -> str:
    rows: list[str] = []
    used = 0
    for hunk in file.hunks:
        if rows:
            rows.append("-----")
        for line in hunk.lines:
            if used >= _MAX_DIFF_LINES:
                rows.append("... truncated")
                return "\n".join(rows)
            if line.kind == "add":
                rows.append(f"{line.new_line:5d} RIGHT +{line.text}")
            elif line.kind == "del":
                rows.append(f"{line.old_line:5d} LEFT  -{line.text}")
            else:
                rows.append(f"{line.new_line:5d} RIGHT  {line.text}")
            used += 1
    return "\n".join(rows)


def _file_prompt(file: FileDiff, rules: Rules, task: dict | None) -> str:
    categories = ", ".join(rules.focus)
    parts = [
        f"Strictness: {rules.strictness}. {_STRICTNESS_GUIDE[rules.strictness]}",
        f"Categories allowed: {categories}.",
        f"File: {file.path} ({file.status})",
    ]
    if task:
        description = (task.get("description") or "").strip()
        if len(description) > 1500:
            description = description[:1500] + "..."
        parts.append(
            f"Jira {task.get('key', '')}: {task.get('summary', '')}\n{description}".rstrip()
        )
    parts.append(_format_file(file))
    parts.append(
        "Return "
        '{"comments":[{"line": <int>, "side": "RIGHT or LEFT", "severity": "error|warning|note", '
        '"category": "<one category>", "body": "one or two sentences"}]}'
    )
    parts.append(f"category is exactly one of: {categories}.")
    parts.append(
        "Use only line numbers and sides from the listing. "
        "severity is error for a definite bug, warning for a concrete risk, note otherwise. "
        'If nothing is wrong, return {"comments":[]}.'
    )
    return "\n\n".join(parts)


def _summary_prompt(files: list[FileDiff], comments: list[Comment]) -> str:
    stats = []
    for file in files:
        added, deleted = changed_counts(file)
        stats.append(f"- {file.path} ({file.status}, +{added} -{deleted})")
    findings = [
        f"- {comment.path}:{comment.line} {comment.category}: {comment.body}" for comment in comments
    ] or ["- (none)"]
    return "\n".join([
        "Write a pull-request summary from the notes below. Do not invent findings.",
        "Files:",
        *stats,
        "Findings:",
        *findings,
        'Return {"what_changed":"one sentence","risks":["short point"],"suggested_tests":["short point"]}',
        "risks and suggested_tests have at most 4 items each. "
        "If there are no findings, say that in risks.",
    ])


def _complete_json(llm: LLM, messages: list[dict[str, str]], max_new_tokens: int):
    reply = llm.complete(messages, max_new_tokens)
    try:
        return parse_json_value(reply)
    except ValueError:
        retry = messages + [
            {"role": "assistant", "content": reply[:1500]},
            {"role": "user", "content": "That was not valid JSON. Reply with one JSON object only."},
        ]
        return parse_json_value(llm.complete(retry, max_new_tokens))


def _clean_body(text: str) -> str:
    body = " ".join(str(text).split())
    if len(body) > _MAX_BODY:
        body = body[: _MAX_BODY - 3] + "..."
    return body


def _category(value: str, rules: Rules) -> str | None:
    key = str(value or "").strip().lower()
    mapped = _CATEGORY_ALIASES.get(key, key)
    if mapped not in rules.focus:
        return None
    if rules.strictness != "strict" and mapped == "tests":
        return None
    return mapped


def _accept(raw: dict, file: FileDiff, rules: Rules) -> Comment | None:
    if not isinstance(raw, dict):
        return None
    try:
        line = int(raw.get("line"))
    except (TypeError, ValueError):
        return None
    side = str(raw.get("side", "")).strip().upper()
    if side not in {"LEFT", "RIGHT"}:
        return None
    if (line, side) not in commentable(file):
        return None
    category = _category(str(raw.get("category", "")), rules)
    if category is None:
        return None
    severity = str(raw.get("severity", "warning")).strip().lower()
    if severity not in {"error", "warning", "note"}:
        severity = "warning"
    if not rules.allows_severity(severity):
        return None
    body = _clean_body(raw.get("body", ""))
    if not body:
        return None
    return Comment(path=file.path, line=line, side=side, severity=severity, category=category, body=body)


_SEVERITY_RANK = {"error": 0, "warning": 1, "note": 2}


def _cap(comments: list[Comment], rules: Rules) -> list[Comment]:
    comments = sorted(comments, key=lambda c: (_SEVERITY_RANK.get(c.severity, 9), c.path, c.line))
    kept: list[Comment] = []
    seen: set[tuple] = set()
    per_file: dict[str, int] = {}
    cap = rules.per_file_cap()
    for comment in comments:
        key = (comment.path, comment.line, comment.side)
        if key in seen:
            continue
        if cap is not None and per_file.get(comment.path, 0) >= cap:
            continue
        if len(kept) >= rules.max_comments:
            break
        seen.add(key)
        per_file[comment.path] = per_file.get(comment.path, 0) + 1
        kept.append(comment)
    return kept


def _as_str_list(value, limit: int = 4) -> list[str]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        text = _clean_body(item)
        if text:
            items.append(text[:500])
        if len(items) >= limit:
            break
    return items


def _summary_from_model(payload: object) -> Summary:
    if not isinstance(payload, dict):
        raise ValueError("summary is not an object")
    what = _clean_body(payload.get("what_changed", ""))
    if not what:
        raise ValueError("summary has no what_changed")
    risks = _as_str_list(payload.get("risks"))
    tests = _as_str_list(payload.get("suggested_tests"))
    if not risks:
        risks = ["No issues were reported on the reviewed lines."]
    if not tests:
        tests = ["No test was suggested."]
    return Summary(what_changed=what, risks=risks, suggested_tests=tests, source="model")


def _fallback_summary(files: list[FileDiff], comments: list[Comment], ignored: list[str]) -> Summary:
    if files:
        bits = []
        for file in files:
            added, deleted = changed_counts(file)
            bits.append(f"{file.path} ({file.status}, +{added} -{deleted})")
        what = "Changed " + "; ".join(bits) + "."
    elif ignored:
        what = "No reviewed files. Every changed file was ignored by the rules or had no text diff."
    else:
        what = "The diff is empty."
    if comments:
        risks = [f"{c.path}:{c.line} ({c.category}) {c.body}" for c in comments[:4]]
    else:
        risks = ["No issues were reported on the reviewed lines."]
    tests = [f"Add a test that runs the changed lines in {file.path}." for file in files[:4]]
    if not tests:
        tests = ["No file was reviewed, so there is no test to suggest."]
    return Summary(what_changed=what, risks=risks, suggested_tests=tests, source="fallback")


def _comments_from_payload(payload: object) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        comments = payload.get("comments", [])
        return comments if isinstance(comments, list) else []
    return []


def review_diff(
    diff_text: str,
    settings: Settings,
    rules: Rules,
    *,
    llm: LLM | None = None,
    pr_title: str = "",
    pr_body: str = "",
    head_ref: str = "",
    pr_url: str = "",
    jira_client: JiraBridge | None = None,
    jira_send: bool | None = None,
) -> Review:
    """Review ``diff_text`` and return inline comments plus a summary.

    ``llm`` is injected by tests. Otherwise the configured backend is used.
    """
    settings.validate()
    files = parse_diff(diff_text)
    ignored: list[str] = []
    skipped: list[str] = []
    reviewable: list[FileDiff] = []
    for file in files:
        if file.is_binary or not file.hunks:
            skipped.append(file.path)
        elif is_ignored(file.path, rules.ignore):
            ignored.append(file.path)
        else:
            reviewable.append(file)

    jira_ctx = prepare_jira(
        enabled=rules.jira.enabled,
        title=pr_title,
        body=pr_body,
        head_ref=head_ref,
        client=jira_client,
    )
    task = jira_ctx.task

    comments: list[Comment] = []
    dropped = 0
    parse_failures = 0
    model_name = settings.model_name
    model = llm
    if reviewable and model is None:
        model = get_llm(settings)
    if reviewable and model is not None:
        model_name = getattr(model, "name", None) or model_name
        budget = min(settings.max_new_tokens, 700)
        for file in reviewable:
            messages = [_system_prompt(), {"role": "user", "content": _file_prompt(file, rules, task)}]
            try:
                payload = _complete_json(model, messages, budget)
            except ValueError:
                parse_failures += 1
                continue
            raw_comments = _comments_from_payload(payload)
            for raw in raw_comments:
                accepted = _accept(raw, file, rules)
                if accepted is None:
                    dropped += 1
                else:
                    comments.append(accepted)
        before_cap = len(comments)
        comments = _cap(comments, rules)
        dropped += before_cap - len(comments)

    summary: Summary
    if reviewable and model is not None:
        messages = [_system_prompt(), {"role": "user", "content": _summary_prompt(reviewable, comments)}]
        try:
            summary = _summary_from_model(_complete_json(model, messages, min(settings.max_new_tokens, 500)))
        except ValueError:
            parse_failures += 1
            summary = _fallback_summary(reviewable, comments, ignored)
    else:
        summary = _fallback_summary(reviewable, comments, ignored)

    review = Review(
        comments=comments,
        summary=summary,
        model=model_name,
        backend=settings.backend,
        files_reviewed=[file.path for file in reviewable],
        files_ignored=ignored,
        files_skipped=skipped,
        dropped=dropped,
        parse_failures=parse_failures,
        jira=jira_ctx.public(),
    )
    if rules.jira.enabled:
        send = rules.jira.send if jira_send is None else jira_send
        review.jira = deliver_report(jira_ctx, render_jira_report(review, pr_url=pr_url), send=send)
    return review
