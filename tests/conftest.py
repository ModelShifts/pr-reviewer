from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples" / "diffs"


class FakeLLM:
    """Stands in for a chat model. Returns canned replies and records prompts."""

    name = "fake-llm"

    def __init__(self, replies):
        self.replies = list(replies) if isinstance(replies, (list, tuple)) else [replies]
        self.prompts = []

    def complete(self, messages, max_new_tokens=None):
        self.prompts.append(messages)
        if not self.replies:
            raise AssertionError("FakeLLM ran out of replies")
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


@pytest.fixture
def samples() -> Path:
    return SAMPLES


@pytest.fixture
def fake_llm():
    return FakeLLM


@pytest.fixture
def settings():
    from pr_reviewer.config import Settings

    return Settings(backend="hf", hf_model="fake-model")
