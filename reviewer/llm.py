"""LLM providers behind one interface: (system, user) -> LLMReview.

Providers
- anthropic : tool-use forces schema-valid JSON
- gemini    : JSON mode + schema (good free-tier option for a demo)
- mock      : deterministic, no API key; derives scores from static signals only.
              Exists for tests and offline demos -- it is NOT an AI review.
"""
from __future__ import annotations

import json
import os
import time

from pydantic import ValidationError

from .models import DimensionScore, Fix, LLMReview
from .rubric import RUBRIC

DEFAULT_MODELS = {
    "anthropic": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
    "gemini": os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
    "mock": "mock-heuristic",
}


class LLMError(Exception):
    pass


def _validate(raw: dict | str) -> LLMReview:
    return LLMReview.model_validate_json(raw) if isinstance(raw, str) else LLMReview.model_validate(raw)


def _anthropic(system: str, user: str, model: str) -> LLMReview:
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    tool = {
        "name": "submit_review",
        "description": "Submit the structured code review.",
        "input_schema": LLMReview.model_json_schema(),
    }
    messages = [{"role": "user", "content": user}]
    last_err: Exception | None = None
    for _ in range(2):  # one repair attempt
        resp = client.messages.create(
            model=model,
            max_tokens=3000,
            temperature=0,
            system=system,
            messages=messages,
            tools=[tool],
            tool_choice={"type": "tool", "name": "submit_review"},
        )
        block = next((b for b in resp.content if b.type == "tool_use"), None)
        if block is None:
            last_err = LLMError("model returned no tool call")
            continue
        try:
            return _validate(block.input)
        except ValidationError as e:
            last_err = e
            messages += [
                {"role": "assistant", "content": resp.content},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "is_error": True,
                            "content": f"Schema validation failed: {e}. Call submit_review again, fixed.",
                        }
                    ],
                },
            ]
    raise LLMError(f"Anthropic review failed validation: {last_err}")


def _gemini(system: str, user: str, model: str) -> LLMReview:
    from google import genai
    from google.genai import types

    client = genai.Client()  # reads GEMINI_API_KEY / GOOGLE_API_KEY
    schema = LLMReview.model_json_schema()
    shape_hint = (
        "\n\nOUTPUT FORMAT (strict JSON, no markdown):\n"
        '{"summary": str,\n'
        ' "dimensions": [ {"dimension": str, "score": int 0-5, "rationale": str, "evidence": [str]} ],  // ARRAY, one object per dimension\n'
        ' "top_fixes": [ {"priority": "high"|"medium"|"low", "file": str|null, "action": str} ],\n'
        ' "strengths": [str]}\n'
        "dimensions MUST be a JSON array, not an object keyed by name. Each fix MUST have priority and action."
    )
    last_err: Exception | None = None
    prompt = user
    for _ in range(3):
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system + shape_hint,
                response_mime_type="application/json",
                response_json_schema=schema,  # server-side schema enforcement
                temperature=0,
            ),
        )
        try:
            return _validate(resp.text)
        except (ValidationError, ValueError) as e:
            last_err = e
            prompt = (
                user
                + f"\n\nYour previous output failed validation:\n{str(e)[:800]}\n"
                + f"Return corrected JSON matching this schema exactly:\n{json.dumps(schema)}"
            )
    raise LLMError(f"Gemini review failed validation: {last_err}")


def _mock(system: str, user: str, model: str) -> LLMReview:
    """Heuristic stand-in. Reads the static-signal JSON embedded in the prompt."""
    start = user.index("<static_signals>") + len("<static_signals>")
    end = user.index("</static_signals>")
    s = json.loads(user[start:end])

    def clamp(x: float) -> int:
        return max(0, min(5, round(x)))

    tests = 0 if not s["has_tests"] else clamp(2 + 6 * s["test_to_code_ratio"])
    doc = 0 if not s["has_readme"] else clamp(1 + s["readme_chars"] / 600 + s["readme_has_setup"])
    sec = 1 if (s["possible_secrets"] or s["committed_env_files"]) else clamp(
        3 + s["has_gitignore"] + s["has_env_example"] + s["has_dependency_manifest"] - 1
    )
    eng = clamp(s["has_ci"] * 2 + s["has_license"] + s["has_dependency_manifest"] + s["has_gitignore"])
    scores = {
        "code_quality": 3, "architecture": clamp(1 + s["file_count"] / 8),
        "testing": tests, "documentation": doc, "security_hygiene": sec, "engineering_practices": eng,
    }
    fixes = []
    if not s["has_tests"]:
        fixes.append(Fix(priority="high", action="Add a tests/ folder with at least one runnable test."))
    if not s["has_readme"] or s["readme_chars"] < 300:
        fixes.append(Fix(priority="high", file="README.md", action="Write a README: purpose, setup, usage example."))
    if not s["has_ci"]:
        fixes.append(Fix(priority="medium", action="Add a CI workflow that runs the tests on every push."))
    return LLMReview(
        summary="[MOCK MODE] Scores derived from static signals only; no LLM was called.",
        dimensions=[
            DimensionScore(dimension=d, score=scores[d], rationale="Heuristic from static signals (mock mode).", evidence=[])
            for d in RUBRIC
        ],
        top_fixes=fixes or [Fix(priority="low", action="Run with a real provider for a code-level review.")],
        strengths=["Has a README"] if s["has_readme"] else [],
    )


PROVIDERS = {"anthropic": _anthropic, "gemini": _gemini, "mock": _mock}


TRANSIENT_MARKERS = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "overloaded", "529", "timeout", "timed out")
RETRY_DELAYS = (2, 5, 10, 20)  # seconds; total wait up to ~37s before giving up


def run_review(provider: str, system: str, user: str, model: str | None = None) -> tuple[LLMReview, str]:
    if provider not in PROVIDERS:
        raise LLMError(f"Unknown provider '{provider}'. Choose from {list(PROVIDERS)}")
    model = model or DEFAULT_MODELS[provider]
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            return PROVIDERS[provider](system, user, model), model
        except LLMError:
            raise  # schema problems are not fixed by waiting
        except Exception as e:
            transient = any(m.lower() in str(e).lower() for m in TRANSIENT_MARKERS)
            if not transient or attempt == len(RETRY_DELAYS):
                raise
            time.sleep(RETRY_DELAYS[attempt])  # provider overloaded: back off and retry
    raise LLMError("unreachable")