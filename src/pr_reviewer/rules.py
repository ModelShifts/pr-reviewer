"""Load ``.github/pr-reviewer.yml`` and decide which files are in scope."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

STRICTNESS = ("relaxed", "normal", "strict")
SEVERITIES = {
    "relaxed": frozenset({"error"}),
    "normal": frozenset({"error", "warning"}),
    "strict": frozenset({"error", "warning", "note"}),
}
DEFAULT_FOCUS = ("correctness", "security", "tests")


@dataclass
class JiraRules:
    enabled: bool = False
    send: bool = False


@dataclass
class Rules:
    strictness: str = "normal"
    focus: list[str] = field(default_factory=lambda: list(DEFAULT_FOCUS))
    ignore: list[str] = field(default_factory=lambda: ["**/*.lock", "docs/**"])
    max_comments: int = 20
    jira: JiraRules = field(default_factory=JiraRules)

    def allows_severity(self, severity: str) -> bool:
        return severity in SEVERITIES[self.strictness]

    def per_file_cap(self) -> int | None:
        """Relaxed reviews keep a single comment per file."""
        return 1 if self.strictness == "relaxed" else None


def _as_bool(value, name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{name} must be true or false")


def _as_str_list(value, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{name} must be a list of strings")
    return [item.strip() for item in value]


def rules_from_mapping(data: dict | None) -> Rules:
    data = data or {}
    if not isinstance(data, dict):
        raise ValueError("the rules file must be a YAML mapping")
    strictness = str(data.get("strictness", "normal")).strip().lower()
    if strictness not in STRICTNESS:
        raise ValueError(f"strictness must be one of {', '.join(STRICTNESS)}")
    focus = _as_str_list(data.get("focus", list(DEFAULT_FOCUS)), "focus")
    ignore = _as_str_list(data.get("ignore", ["**/*.lock", "docs/**"]), "ignore")
    max_comments = data.get("max_comments", 20)
    if isinstance(max_comments, bool) or not isinstance(max_comments, int) or max_comments < 1:
        raise ValueError("max_comments must be a positive integer")
    jira_raw = data.get("jira") or {}
    if not isinstance(jira_raw, dict):
        raise ValueError("jira must be a mapping")
    jira = JiraRules(
        enabled=_as_bool(jira_raw.get("enabled", False), "jira.enabled"),
        send=_as_bool(jira_raw.get("send", False), "jira.send"),
    )
    return Rules(strictness=strictness, focus=focus, ignore=ignore, max_comments=max_comments, jira=jira)


def load_rules_text(text: str) -> Rules:
    import yaml

    loaded = yaml.safe_load(text)
    return rules_from_mapping(loaded or {})


def load_rules(path: str | Path | None) -> Rules:
    """Load rules from ``path``. A missing default file uses the built-in rules."""
    if path is None:
        return Rules()
    file = Path(path)
    if not file.is_file():
        raise FileNotFoundError(f"rules file not found: {file}")
    return load_rules_text(file.read_text(encoding="utf-8"))


def resolve_rules_path(explicit: str | None) -> Path | None:
    """Find the rules file. An explicit path is returned even when it is missing."""
    if explicit:
        return Path(explicit)
    for candidate in (Path(".github/pr-reviewer.yml"), Path("examples/pr-reviewer.yml")):
        if candidate.is_file():
            return candidate
    return None


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    pattern = pattern.replace("\\", "/").lstrip("/")
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            parts.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            parts.append(".*")
            i += 2
        elif pattern[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(parts) + "$")


def is_ignored(path: str, patterns: list[str]) -> bool:
    """Return True when ``path`` matches one of the gitignore-like patterns."""
    normalized = path.replace("\\", "/").lstrip("./")
    name = normalized.rsplit("/", 1)[-1]
    for pattern in patterns:
        pattern = pattern.strip()
        if not pattern:
            continue
        if _glob_to_regex(pattern).match(normalized):
            return True
        # A pattern with no slash matches the file name in any directory, as gitignore does.
        if "/" not in pattern and _glob_to_regex(pattern).match(name):
            return True
    return False
