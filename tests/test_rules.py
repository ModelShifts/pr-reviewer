import pytest

from pr_reviewer.rules import is_ignored, load_rules_text

def test_ignore_globs():
    patterns = ["**/*.lock", "docs/**", "*.svg"]
    assert is_ignored("docs/guide.md", patterns)
    assert is_ignored("docs/a/b.md", patterns)
    assert is_ignored("poetry.lock", patterns)
    assert is_ignored("sub/dir/app.lock", patterns)
    assert is_ignored("assets/banner.svg", patterns)
    assert is_ignored("dir/banner.svg", patterns)
    assert not is_ignored("src/app.py", patterns)
    assert not is_ignored("docs", patterns)


def test_rules_file_round_trip():
    rules = load_rules_text("""
strictness: strict
focus:
  - security
ignore:
  - "*.md"
max_comments: 3
jira:
  enabled: true
  send: false
""")
    assert rules.strictness == "strict"
    assert rules.focus == ["security"]
    assert rules.max_comments == 3
    assert rules.jira.enabled is True
    assert rules.jira.send is False
    assert rules.allows_severity("note")
    assert rules.per_file_cap() is None


def test_rules_reject_bad_values():
    with pytest.raises(ValueError):
        load_rules_text("strictness: loud\n")
    with pytest.raises(ValueError):
        load_rules_text("max_comments: 0\n")
    with pytest.raises(ValueError):
        load_rules_text("jira:\n  enabled: sure\n")
