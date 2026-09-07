"""Regressions for provider and narrator trust boundaries."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import bck_nd_hlpr.cli.cli as cli_module
import bck_nd_hlpr.core.ai_providers as providers_module
import bck_nd_hlpr.core.context_dumper as context_dumper_module
from bck_nd_hlpr.cli.cli import app
from bck_nd_hlpr.core.ai_providers import (
    AI_PROVIDER_ERROR,
    AnthropicProvider,
    GeminiProvider,
    OllamaProvider,
    OpenAIProvider,
    OpenRouterProvider,
)
from bck_nd_hlpr.core.narrator import Narrator
from bck_nd_hlpr.core.sanitizer import REDACTION_MARKER


SECRET = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
runner = CliRunner()


def _write_chat_business_context(project: Path) -> None:
    product_dir = project / ".bck-nd" / "product"
    product_dir.mkdir(parents=True, exist_ok=True)
    (product_dir / "PRD-CHAT.md").write_text(
        """---
schema_version: 1
id: PRD-CHAT
title: Chat product intent
status: DRAFT
owner: Product Team
target_release: 2.5.0
applies_to:
  - .
requirement_ids:
  - HU-CHAT
---

## Problem Statement
Students need the chat to preserve product intent.

## Target Users
Students and maintainers.

## Goals
Keep business context ahead of architecture.

## Non-Goals
Do not invent product rules.

## Success Metrics
The linked story is visible.

## Scope
Local interactive chat.

## Risks
Context could be omitted.

## Rollout Plan
Verify with simulated providers.

## Open Questions
- None.
""",
        encoding="utf-8",
    )
    requirements = project / ".bck-nd" / "requirements"
    requirements.mkdir(parents=True, exist_ok=True)
    (requirements / "HU-CHAT.json").write_text(
        json.dumps(
            {
                "story": {
                    "id": "HU-CHAT",
                    "status": "TODO",
                    "title": "Business-aware chat",
                    "role": "student",
                    "want": "consult the project with its rules",
                    "benefit": "avoid invented behavior",
                },
                "business_rules": [
                    {"id": "BR-CHAT", "description": "Respect approved scope"}
                ],
                "acceptance_criteria": [
                    {
                        "id": "AC-CHAT",
                        "given": "product and requirements exist",
                        "when": "chat starts",
                        "then": "business context precedes architecture",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _install_chat_fakes(monkeypatch, captured_contexts):
    class FakeScanner:
        def detect_architecture(self, _path):
            return {
                "framework": "FastAPI",
                "architecture": "Layered",
                "features": ["API"],
            }

        def scan(self, _path, max_depth=None):
            return "ARCHITECTURE-FLOW"

        def scan_uml(self, _path, max_depth=None):
            return ""

        def get_docs_content(self, _path):
            return "DOCUMENTATION-CONTENT"

    class FakeNarrator:
        def __init__(self, force_provider=None):
            self.provider = object()

        def chat_turn(self, system_context, history_text, style="pro"):
            captured_contexts.append(system_context)
            return "Simulated response"

    monkeypatch.setattr(cli_module, "ProjectScanner", FakeScanner)
    monkeypatch.setattr(cli_module, "Narrator", FakeNarrator)
    monkeypatch.setattr(cli_module, "parse_infra", lambda _path: None)
    monkeypatch.setattr(
        cli_module,
        "parse_project_routes",
        lambda _path, max_depth=None: [],
    )
    monkeypatch.setattr(
        cli_module,
        "parse_project_for_er",
        lambda _path, max_depth=None: [],
    )


def test_chat_includes_canonical_business_context_before_architecture(tmp_path, monkeypatch):
    _write_chat_business_context(tmp_path)
    nested = tmp_path / "nested"
    requirements = nested / ".bck-nd" / "requirements"
    requirements.mkdir(parents=True)
    (requirements / "HU-NESTED.json").write_text(
        json.dumps({"story": {"id": "HU-NESTED", "status": "TODO"}}),
        encoding="utf-8",
    )
    contexts = []
    _install_chat_fakes(monkeypatch, contexts)

    result = runner.invoke(app, ["chat", str(tmp_path)], input="Inspect scope\nexit\n")

    assert result.exit_code == 0, result.exception
    assert len(contexts) == 1
    context = contexts[0]
    assert "<product_context" in context
    assert "<requirements_scope>" in context
    assert "<requirements_context>" in context
    assert "BR-CHAT" in context
    assert "Respect approved scope" in context
    assert "AC-CHAT" in context
    assert context.index("<product_context") < context.index("<requirements_scope>")
    assert context.index("<requirements_scope>") < context.index("<requirements_context>")
    assert context.index("<requirements_context>") < context.index("ARCHITECTURE-FLOW")
    assert context.index("ARCHITECTURE-FLOW") < context.index("DOCUMENTATION-CONTENT")


def test_chat_business_context_flags_are_independent_and_empty_safe(tmp_path, monkeypatch):
    project = tmp_path / "business"
    empty = tmp_path / "empty"
    empty.mkdir()
    _write_chat_business_context(project)
    contexts = []
    _install_chat_fakes(monkeypatch, contexts)
    real_product = context_dumper_module.build_product_context
    real_discover = context_dumper_module.discover_requirements_locations
    product_calls = []
    discovery_calls = []

    def counted_product(*args, **kwargs):
        product_calls.append(args[0] if args else kwargs.get("project_path"))
        return real_product(*args, **kwargs)

    def counted_discovery(*args, **kwargs):
        discovery_calls.append(args[0] if args else kwargs.get("project_path"))
        return real_discover(*args, **kwargs)

    monkeypatch.setattr(context_dumper_module, "build_product_context", counted_product)
    monkeypatch.setattr(
        context_dumper_module,
        "discover_requirements_locations",
        counted_discovery,
    )

    no_prd = runner.invoke(
        app,
        ["chat", str(project), "--no-prd"],
        input="Inspect\nexit\n",
    )
    assert no_prd.exit_code == 0, no_prd.exception
    assert "<product_context" not in contexts[-1]
    assert "<requirements_context>" in contexts[-1]
    assert product_calls == []
    assert len(discovery_calls) == 1

    no_req = runner.invoke(
        app,
        ["chat", str(project), "--no-req"],
        input="Inspect\nexit\n",
    )
    assert no_req.exit_code == 0, no_req.exception
    assert "<product_context" in contexts[-1]
    assert "<requirements_scope>" not in contexts[-1]
    assert "<requirements_context>" not in contexts[-1]
    assert len(product_calls) == 1
    assert len(discovery_calls) == 1

    both_off = runner.invoke(
        app,
        ["chat", str(project), "--no-prd", "--no-req"],
        input="Inspect\nexit\n",
    )
    assert both_off.exit_code == 0, both_off.exception
    assert "<product_context" not in contexts[-1]
    assert "<requirements_scope>" not in contexts[-1]
    assert "<requirements_context>" not in contexts[-1]
    assert len(product_calls) == 1
    assert len(discovery_calls) == 1

    no_business_files = runner.invoke(
        app,
        ["chat", str(empty)],
        input="Inspect\nexit\n",
    )
    assert no_business_files.exit_code == 0, no_business_files.exception
    assert "<product_context" not in contexts[-1]
    assert "<requirements_scope>" not in contexts[-1]
    assert "<requirements_context>" not in contexts[-1]
    assert "ARCHITECTURE-FLOW" in contexts[-1]


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.mark.parametrize(
    ("provider", "response_payload"),
    [
        (
            OpenAIProvider("provider-key"),
            {"choices": [{"message": {"content": f"token = {SECRET}"}}]},
        ),
        (
            OpenRouterProvider("provider-key"),
            {"choices": [{"message": {"content": f"token = {SECRET}"}}]},
        ),
        (
            AnthropicProvider("provider-key"),
            {"content": [{"text": f"token = {SECRET}"}]},
        ),
        (
            GeminiProvider("provider-key"),
            {
                "candidates": [
                    {"content": {"parts": [{"text": f"token = {SECRET}"}]}}
                ]
            },
        ),
        (
            OllamaProvider(),
            {"message": {"content": f"token = {SECRET}"}},
        ),
    ],
)
def test_all_ai_providers_sanitize_payload_response_and_errors(
    monkeypatch,
    provider,
    response_payload,
):
    calls = []

    def successful_post(*args, **kwargs):
        calls.append((args, kwargs))
        return _Response(response_payload)

    system_prompt = f"System api_key = {SECRET}"
    user_prompt = f"User token = {SECRET}"
    monkeypatch.setattr(providers_module.requests, "post", successful_post)

    result = provider.generate(system_prompt, user_prompt)
    serialized_payload = json.dumps(calls[0][1]["json"])

    assert SECRET not in serialized_payload
    assert REDACTION_MARKER in serialized_payload
    assert SECRET not in result
    assert REDACTION_MARKER in result
    assert system_prompt.endswith(SECRET)
    assert user_prompt.endswith(SECRET)

    def failing_post(*_args, **_kwargs):
        raise RuntimeError(
            f"https://provider.invalid/?key={SECRET} response-body {SECRET}"
        )

    monkeypatch.setattr(providers_module.requests, "post", failing_post)

    assert provider.generate(system_prompt, user_prompt) == AI_PROVIDER_ERROR


def test_narrator_sanitizes_explain_chat_history_responses_and_errors():
    calls = []

    class Provider:
        def generate(self, system_prompt, user_prompt):
            calls.append((system_prompt, user_prompt))
            return f"token = {SECRET}"

    narrator = Narrator.__new__(Narrator)
    narrator.provider = Provider()

    explained = narrator.explain(
        f"Topology api_key = {SECRET}",
        use_ai=True,
    )
    chatted = narrator.chat_turn(
        f"Context token = {SECRET}",
        f"History password = {SECRET}",
    )

    assert len(calls) == 2
    assert all(SECRET not in system + user for system, user in calls)
    assert all(REDACTION_MARKER in system + user for system, user in calls)
    assert SECRET not in explained + chatted
    assert REDACTION_MARKER in explained + chatted

    class FailingProvider:
        def generate(self, *_args, **_kwargs):
            raise RuntimeError(f"secret URL https://invalid/?key={SECRET}")

    narrator.provider = FailingProvider()
    assert narrator.explain("safe", use_ai=True) == AI_PROVIDER_ERROR
    assert narrator.chat_turn("safe", "safe") == AI_PROVIDER_ERROR
