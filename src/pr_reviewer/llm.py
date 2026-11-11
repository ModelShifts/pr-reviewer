"""Chat model backends.

``api``: any OpenAI-compatible ``/v1/chat/completions`` endpoint.
``hf``:  a local ``transformers`` causal LM (default Qwen/Qwen2.5-Coder-7B-Instruct).

Both expose ``complete(messages) -> str``. Decoding is greedy (temperature 0).
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from .config import Settings

Message = dict[str, str]


class LLM(Protocol):
    name: str

    def complete(self, messages: list[Message], max_new_tokens: int | None = None) -> str: ...


def _redact(text: str, secret: str) -> str:
    if secret and secret in text:
        text = text.replace(secret, "***")
    return text[:400]


class APIChat:
    def __init__(self, settings: Settings):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("MS_BACKEND=api needs the 'api' extra: pip install -e '.[api]'") from exc
        self._secret = settings.api_key
        self.client = OpenAI(base_url=settings.api_base, api_key=settings.api_key or "not-needed", timeout=300)
        self.name = settings.model
        self.max_new_tokens = settings.max_new_tokens

    def complete(self, messages: list[Message], max_new_tokens: int | None = None) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.name,
                messages=messages,
                temperature=0,
                max_tokens=max_new_tokens or self.max_new_tokens,
            )
        except Exception as exc:
            raise RuntimeError(f"the API backend request failed: {_redact(str(exc), self._secret)}") from exc
        return response.choices[0].message.content or ""


class HFChat:
    """Local transformers model.

    Loaded in bfloat16. Qwen2.5-Coder-7B-Instruct needs a GPU or a lot of memory.
    On a CPU, set ``MS_HF_MODEL`` to ``Qwen/Qwen2.5-Coder-1.5B-Instruct``.
    """

    def __init__(self, settings: Settings):
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("MS_BACKEND=hf needs the 'hf' extra: pip install -e '.[hf]'") from exc
        self._torch = torch
        self.name = settings.hf_model
        self.max_new_tokens = settings.max_new_tokens
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16
        self.tokenizer = AutoTokenizer.from_pretrained(self.name)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.name, dtype=dtype, low_cpu_mem_usage=True
        ).eval()
        if self.device == "cuda":
            self.model.to(self.device)

    def complete(self, messages: list[Message], max_new_tokens: int | None = None) -> str:
        prompt = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        with self._torch.no_grad():
            out = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens or self.max_new_tokens,
                do_sample=False,
                temperature=None,
                top_p=None,
                top_k=None,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        return self.tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)


_CACHE: dict[tuple, Any] = {}


def get_llm(settings: Settings) -> LLM:
    """Build (and memoise) the chat model for the configured backend."""
    settings.validate()
    key = ("llm", settings.backend, settings.model_name, settings.api_base)
    if key not in _CACHE:
        _CACHE[key] = APIChat(settings) if settings.backend == "api" else HFChat(settings)
    return _CACHE[key]


def clear_llm_cache() -> None:
    _CACHE.clear()


def _loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
        return json.loads(cleaned)


def _slice_value(text: str, start: int) -> str:
    opener = text[start]
    if opener not in "{[":
        raise ValueError("not a JSON start")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise ValueError("unterminated JSON value")


def parse_json_value(text: str) -> Any:
    """Pull the first JSON object or array out of a model reply.

    Tolerates Markdown fences, leading prose and trailing commas.
    """
    cleaned = text.replace("```json", "").replace("```", "")
    for i, ch in enumerate(cleaned):
        if ch not in "{[":
            continue
        try:
            return _loads(_slice_value(cleaned, i))
        except (ValueError, json.JSONDecodeError):
            continue
    raise ValueError(f"model reply has no JSON value: {text[:200]!r}")
