"""Link a review to a Jira issue through ModelShifts/jira-bridge.

The bridge is optional. When ``jira.enabled`` is false, or the package and
local config are missing, the review still runs and the result says why the
link was not made. ``jira.send: false`` previews the comment and does not post it.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

ISSUE_RE = re.compile(r"\b([A-Z][A-Z0-9_]*-[1-9][0-9]*)\b")


class JiraBridge(Protocol):
    def fetch(self, key: str) -> dict: ...

    def report(self, key: str, text: str, send: bool = False) -> dict: ...


def find_issue_key(*texts: str) -> str | None:
    """Return the first Jira-style issue key in ``texts``, title before branch before body."""
    for text in texts:
        match = ISSUE_RE.search(text or "")
        if match:
            return match.group(1)
    return None


def load_jira_client() -> tuple[JiraBridge | None, str]:
    """Build a client from the jira-bridge config, or explain why that did not happen."""
    try:
        import jira_bridge
    except ImportError:
        return None, "jira-bridge is not installed"
    config_path = Path(os.environ.get(
        "JIRA_BRIDGE_CONFIG", str(Path.home() / ".config" / "modelshifts" / "jira.json")
    ))
    if not config_path.is_file():
        return None, "jira-bridge config was not found"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        return jira_bridge.JiraClient(config), ""
    except Exception as exc:
        # jira-bridge raises BridgeError without including the token.
        return None, str(exc)


@dataclass
class JiraContext:
    status: str
    issue: str = ""
    reason: str = ""
    task: dict[str, str] | None = None
    client: JiraBridge | None = None

    def public(self) -> dict[str, Any]:
        data: dict[str, Any] = {"status": self.status}
        if self.issue:
            data["issue"] = self.issue
        if self.reason:
            data["reason"] = self.reason
        if self.task:
            data["task"] = self.task
        return data


def prepare_jira(
    *,
    enabled: bool,
    title: str = "",
    body: str = "",
    head_ref: str = "",
    client: JiraBridge | None = None,
) -> JiraContext:
    """Find the issue key and, when a client is available, fetch the task."""
    if not enabled:
        return JiraContext(status="disabled")
    key = find_issue_key(title, head_ref, body)
    if not key:
        return JiraContext(status="no_issue_key")
    if client is None:
        client, reason = load_jira_client()
        if client is None:
            return JiraContext(status="skipped", issue=key, reason=reason)
    try:
        task = client.fetch(key)
    except Exception as exc:
        return JiraContext(status="fetch_failed", issue=key, reason=str(exc), client=client)
    kept = {
        "key": str(task.get("key", key)),
        "summary": str(task.get("summary", "")),
        "status": str(task.get("status", "")),
        "description": str(task.get("description", "")),
        "url": str(task.get("url", "")),
    }
    return JiraContext(status="fetched", issue=key, task=kept, client=client)


def deliver_report(ctx: JiraContext, text: str, *, send: bool) -> dict[str, Any]:
    """Preview or send ``text`` through jira-bridge. Always returns JSON-safe data."""
    result = ctx.public()
    result["report"] = text
    if ctx.client is None or not ctx.issue:
        return result
    try:
        bridge = ctx.client.report(ctx.issue, text, send=send)
    except Exception as exc:
        result["status"] = "error"
        result["reason"] = str(exc)
        return result
    result["status"] = str(bridge.get("status", "preview"))
    result["bridge"] = {k: v for k, v in bridge.items() if k != "comment" or isinstance(v, str)}
    return result
