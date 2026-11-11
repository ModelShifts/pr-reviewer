"""Local web demo (Gradio): pick a synthetic diff, review it, read inline comments."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path

from . import __version__
from .config import Settings
from .diffparse import FileDiff, parse_diff
from .review import Comment, Review, review_diff
from .rules import JiraRules, Rules, load_rules, resolve_rules_path

FIELD_NOTE = "Loaded a saved result for this diff, computed earlier by"


def samples_dir() -> Path:
    for directory in (Path.cwd() / "samples" / "diffs", Path(__file__).resolve().parents[2] / "samples" / "diffs"):
        if directory.is_dir():
            return directory
    return Path.cwd() / "samples" / "diffs"


def list_samples() -> list[str]:
    return sorted(path.name[: -len(".diff")] for path in samples_dir().glob("*.diff"))


def load_sample(name: str) -> tuple[str, str]:
    """Return ``(diff, suggested pull request title)``."""
    diff_path = samples_dir() / f"{name}.diff"
    diff = diff_path.read_text(encoding="utf-8")
    truth_path = samples_dir() / f"{name}.truth.json"
    title = ""
    if truth_path.is_file():
        title = str(json.loads(truth_path.read_text(encoding="utf-8")).get("pr_title") or "")
    return diff, title


def base_rules() -> Rules:
    path = resolve_rules_path(None)
    return load_rules(path) if path else Rules()


class ResultCache:
    def __init__(self, directory: str):
        self.directory = Path(directory)

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> dict | None:
        path = self._path(key)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def put(self, key: str, data: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path(key).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def cache_key(diff: str, rules: Rules, settings: Settings, title: str) -> str:
    payload = json.dumps(
        {
            "diff": diff,
            "strictness": rules.strictness,
            "focus": rules.focus,
            "ignore": rules.ignore,
            "max_comments": rules.max_comments,
            "jira": rules.jira.enabled,
            "title": title,
            "model": settings.model_name,
            "backend": settings.backend,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def diff_html(diff_text: str, comments: list[Comment], ignored: list[str]) -> str:
    """Render a diff with review comments under the lines they refer to."""
    by_line: dict[tuple[str, int, str], list[Comment]] = {}
    for comment in comments:
        by_line.setdefault((comment.path, comment.line, comment.side), []).append(comment)
    ignored_set = set(ignored)
    files = parse_diff(diff_text)
    if not files:
        return "<p class='ms-muted'>The diff is empty.</p>"
    parts = ["<div class='ms-diff'>"]
    for file in files:
        parts.append(_file_html(file, by_line, file.path in ignored_set))
    parts.append("</div>")
    return "\n".join(parts)


def _file_html(file: FileDiff, by_line: dict, ignored: bool) -> str:
    badge = "ignored by rules" if ignored else file.status
    parts = [
        "<section class='ms-file'>",
        f"<header><span class='ms-path'>{html.escape(file.path)}</span>"
        f"<span class='ms-badge'>{html.escape(badge)}</span></header>",
    ]
    if file.is_binary or not file.hunks:
        parts.append("<p class='ms-muted'>No text hunks in this file.</p></section>")
        return "\n".join(parts)
    for hunk in file.hunks:
        for line in hunk.lines:
            kind = line.kind
            number = line.new_line if kind != "del" else line.old_line
            prefix = {"add": "+", "del": "-", "ctx": " "}[kind]
            parts.append(
                f"<div class='ms-line {kind}'><span class='ln'>{number or ''}</span>"
                f"<code>{prefix}{html.escape(line.text)}</code></div>"
            )
            if ignored:
                continue
            attached: list[Comment] = []
            if kind == "del" and line.old_line is not None:
                attached = by_line.get((file.path, line.old_line, "LEFT"), [])
            elif line.new_line is not None:
                attached = by_line.get((file.path, line.new_line, "RIGHT"), [])
                if kind == "ctx" and line.old_line is not None:
                    attached = attached + by_line.get((file.path, line.old_line, "LEFT"), [])
            for comment in attached:
                parts.append(
                    "<aside class='ms-comment'>"
                    f"<b>{html.escape(comment.category)} · {html.escape(comment.severity)}</b>"
                    f"<p>{html.escape(comment.body)}</p></aside>"
                )
    parts.append("</section>")
    return "\n".join(parts)


def summary_markdown(review: Review) -> str:
    summary = review.summary
    lines = [
        f"**What changed.** {summary.what_changed}",
        "",
        "**Risks**",
    ]
    lines.extend(f"- {item}" for item in summary.risks)
    lines.extend(["", "**Suggested tests**"])
    lines.extend(f"- {item}" for item in summary.suggested_tests)
    return "\n".join(lines)


def jira_markdown(review: Review) -> str:
    info = review.jira or {}
    status = info.get("status", "disabled")
    if status == "disabled":
        return "Jira linking is off. Turn it on to preview a jira-bridge report for an issue key in the title."
    issue = info.get("issue") or "(no issue key in the title or branch)"
    reason = info.get("reason") or ""
    task = info.get("task") or {}
    bits = [f"**{issue}**", f"status: {status}"]
    if isinstance(task, dict) and task.get("summary"):
        bits.append(str(task["summary"]))
    if reason:
        bits.append(reason)
    text = " · ".join(bits)
    report = info.get("report")
    if report:
        text += "\n\nThe web demo previews the report and does not send it.\n\n```\n" + str(report)[:1200] + "\n```"
    return text


CSS = """
:root, .gradio-container { --ms-ink:#1c1a17; --ms-rust:#8a3a24; --ms-paper:#f3efe6; --ms-cream:#faf7f0; }
.gradio-container { background: var(--ms-cream) !important; font-family: Georgia, 'Times New Roman', serif !important; max-width: 1240px !important; }
.ms-header { border-bottom: 1px solid var(--ms-ink); padding: 10px 4px 12px; margin-bottom: 4px; }
.ms-brand { letter-spacing: .22em; font-size: 12px; color: var(--ms-rust); font-weight: 700; }
.ms-header h1 { font-family: Georgia, serif; font-weight: 400; font-size: 30px; margin: 2px 0 2px; color: var(--ms-ink); }
.ms-header p { margin: 0; color: #4a463f; font-style: italic; }
.ms-meta { margin-top: 8px; font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: #6b665e; }
.ms-muted { color: #6b665e; font-size: 12px; }
.ms-section-title { font-size: 12px; letter-spacing: .14em; text-transform: uppercase; color: var(--ms-rust); margin: 2px 0; }
.ms-status, .ms-answer { font-size: 14px; }
.ms-secondary, button.ms-secondary { background: #fff !important; color: var(--ms-rust) !important; border: 1px solid var(--ms-rust) !important; }
button.primary, .ms-primary button { background: var(--ms-rust) !important; border-color: var(--ms-rust) !important; color: #fff !important; }
footer { display: none !important; }
.ms-diff { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12.5px; background: #fff; border: 1px solid #1c1a17; }
.ms-file header { display: flex; justify-content: space-between; gap: 12px; padding: 8px 10px; background: #f3efe6; border-bottom: 1px solid #1c1a17; }
.ms-path { color: #1c1a17; font-weight: 700; }
.ms-badge { color: #8a3a24; letter-spacing: .08em; text-transform: uppercase; font-size: 11px; }
.ms-line { display: flex; gap: 10px; padding: 0 10px; white-space: pre; }
.ms-line.add { background: #f6efe8; }
.ms-line.del { background: #efeae4; }
.ms-line .ln { width: 2.6em; text-align: right; color: #8a8175; flex: none; }
.ms-comment { margin: 4px 10px 8px 48px; padding: 8px 10px; background: #fff; border-left: 3px solid #8a3a24; }
.ms-comment b { color: #8a3a24; font-family: Georgia, serif; font-size: 13px; }
.ms-comment p { margin: 4px 0 0; color: #1c1a17; font-family: Georgia, serif; font-size: 14px; white-space: normal; }
"""


def build_app(settings: Settings | None = None):
    import gradio as gr

    settings = settings or Settings.from_env()
    cache = ResultCache(settings.cache_dir)
    samples = list_samples()
    rules0 = base_rules()

    def pick_sample(name):
        if not name:
            return gr.update(), gr.update()
        diff, title = load_sample(name)
        return diff, title

    def do_review(diff, strictness, focus, max_comments, title, link_jira):
        diff = diff or ""
        if not diff.strip():
            return "Paste a unified diff or pick a synthetic sample.", "", "", "<p class='ms-muted'>No diff yet.</p>"
        rules = Rules(
            strictness=strictness or rules0.strictness,
            focus=list(focus or rules0.focus),
            ignore=list(rules0.ignore),
            max_comments=max(1, int(max_comments or rules0.max_comments)),
            jira=JiraRules(enabled=bool(link_jira), send=False),
        )
        key = cache_key(diff, rules, settings, title or "")
        cached = cache.get(key)
        try:
            if cached:
                review = Review.from_dict(cached)
                note = f"{FIELD_NOTE} `{review.model}`."
            else:
                review = review_diff(
                    diff, settings, rules, pr_title=title or "", jira_send=False,
                )
                cache.put(key, review.to_dict())
                note = f"Reviewed with `{review.model}` ({settings.backend} backend)."
        except (ValueError, RuntimeError, OSError) as exc:
            return f"Could not review this diff: {exc}", "", "", diff_html(diff, [], [])
        dropped = f" {review.dropped} suggestions were dropped because they were not on a diff line, outside the rules, or over the comment cap." if review.dropped else ""
        status = (
            f"{note} {len(review.comments)} inline comments on "
            f"{len(review.files_reviewed)} file(s).{dropped}"
        )
        return status, summary_markdown(review), jira_markdown(review), diff_html(diff, review.comments, review.files_ignored)

    with gr.Blocks(title="pr-reviewer · Modelshifts") as demo:
        gr.HTML(
            "<div class='ms-header'><div class='ms-brand'>MODELSHIFTS</div><h1>pr-reviewer</h1>"
            "<p>A GitHub Action that reviews pull requests and leaves comments on the diff.</p>"
            f"<div class='ms-meta'>backend: {html.escape(settings.backend)} · "
            f"model: {html.escape(settings.model_name or '(not set)')} · v{__version__}</div></div>"
        )
        with gr.Row(equal_height=False):
            with gr.Column(scale=4, min_width=360):
                gr.HTML("<div class='ms-section-title'>1 · Diff</div>")
                sample = gr.Dropdown(samples, value=None, label="Synthetic sample", interactive=True)
                diff_box = gr.Textbox(label="Unified diff", lines=12, max_lines=18)
                gr.HTML("<div class='ms-section-title'>2 · Rules</div>")
                strictness = gr.Radio(["relaxed", "normal", "strict"], value=rules0.strictness, label="Strictness")
                focus = gr.CheckboxGroup(
                    ["correctness", "security", "tests"],
                    value=rules0.focus,
                    label="Focus",
                )
                max_comments = gr.Slider(1, 20, value=min(rules0.max_comments, 20), step=1, label="Max comments")
                title = gr.Textbox(label="Pull request title (optional, for a Jira issue key)", value="")
                link_jira = gr.Checkbox(value=False, label="Link the review to a Jira issue (preview only)")
                button = gr.Button("Review diff", variant="primary", elem_classes="ms-primary")
                status = gr.Markdown("Pick a synthetic sample or paste a diff.", elem_classes="ms-status")
                gr.HTML("<div class='ms-section-title'>3 · Summary</div>")
                summary = gr.Markdown("", elem_classes="ms-answer")
                gr.HTML("<div class='ms-section-title'>4 · Jira</div>")
                jira = gr.Markdown("Jira linking is off.", elem_classes="ms-answer")
            with gr.Column(scale=7, min_width=480):
                gr.HTML("<div class='ms-section-title'>Diff · comments sit on the line they refer to</div>")
                view = gr.HTML("<p class='ms-muted'>The reviewed diff will appear here.</p>")
        gr.HTML("<p class='ms-muted'>Samples are synthetic. A saved result is reused for the same diff, rules and model. "
                "The demo never sends a Jira comment.</p>")

        sample.change(pick_sample, [sample], [diff_box, title])
        button.click(
            do_review,
            [diff_box, strictness, focus, max_comments, title, link_jira],
            [status, summary, jira, view],
        )
    return demo


def theme():
    import gradio as gr

    return gr.themes.Base(
        primary_hue=gr.themes.colors.orange,
        neutral_hue=gr.themes.colors.stone,
        font=[gr.themes.Font("Georgia"), gr.themes.Font("Times New Roman"), gr.themes.Font("serif")],
        font_mono=[gr.themes.Font("ui-monospace"), gr.themes.Font("Menlo"), gr.themes.Font("monospace")],
        radius_size=gr.themes.sizes.radius_md,
    )


def launch(host: str = "127.0.0.1", port: int = 7860, share: bool = False) -> None:
    demo = build_app()
    demo.queue().launch(server_name=host, server_port=port, share=share, theme=theme(), css=CSS)
