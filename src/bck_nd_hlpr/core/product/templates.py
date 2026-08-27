"""Canonical, deterministic templates for local PRD authoring."""


def render_product_template(product_id: str) -> str:
    """Return the canonical Markdown PRD template for a validated identifier."""
    return f"""---
schema_version: 1
id: {product_id}
title: Describe the product or feature
status: DRAFT
owner:
target_release:
applies_to:
  - .
requirement_ids: []
---

# {product_id} — Product Requirements Document

## Problem Statement
TODO: Describe the problem without proposing a solution.

## Target Users
TODO: Describe the users and stakeholders based on confirmed information.

## Goals
TODO: List the outcomes this product or feature must achieve.

## Non-Goals
TODO: State what is deliberately outside this scope.

## Success Metrics
TODO: Define how humans will determine whether the outcome succeeded.

## Scope
TODO: Describe the included capabilities and boundaries.

## Risks
TODO: Record known risks and mitigations.

## Rollout Plan
TODO: Describe the reviewed delivery and adoption plan.

## Open Questions
- TODO: Record unresolved decisions; do not ask an AI agent to invent answers.
"""


__all__ = ["render_product_template"]
