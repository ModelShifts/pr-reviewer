from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_ci_uses_the_current_actions():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "actions/checkout@v5" in text
    assert "actions/setup-python@v6" in text
    assert '"3.11"' in text
    assert '"3.12"' in text


def test_action_maps_inputs_onto_ms_settings():
    text = (ROOT / "action.yml").read_text(encoding="utf-8")
    assert "actions/setup-python@v6" in text
    assert "python -m pr_reviewer" in text
    assert "MS_BACKEND:" in text
    assert "MS_API_BASE:" in text
    assert "MS_API_KEY:" in text
    assert "MS_MODEL:" in text
    assert "MS_HF_MODEL:" in text
