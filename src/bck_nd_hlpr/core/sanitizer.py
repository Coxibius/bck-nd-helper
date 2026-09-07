"""Deterministic high-confidence redaction for repository-supplied text."""

from typing import Match

from bck_nd_hlpr.core.credential_patterns import (
    BEARER_PATTERN,
    CONNECTION_URI_PATTERN,
    KEY_VALUE_PATTERN,
    MAX_QUOTED_SECRET_CHARS,
    PRIVATE_KEY_PATTERN,
    RAW_CREDENTIAL_PATTERNS,
    REDACTION_MARKER,
)


class Sanitizer:
    """Redact high-confidence credential shapes without changing normal prose."""

    def sanitize(self, text: str) -> str:
        if not text:
            return ""

        output = str(text)
        output = PRIVATE_KEY_PATTERN.sub(REDACTION_MARKER, output)
        output = CONNECTION_URI_PATTERN.sub(
            lambda match: (
                f"{match.group('prefix')}{REDACTION_MARKER}"
                f"{match.group('suffix')}"
            ),
            output,
        )
        output = BEARER_PATTERN.sub(
            lambda match: f"{match.group('prefix')}{REDACTION_MARKER}",
            output,
        )
        output = KEY_VALUE_PATTERN.sub(self._redact_key_value, output)
        for credential in RAW_CREDENTIAL_PATTERNS:
            output = credential.pattern.sub(REDACTION_MARKER, output)
        return output

    @staticmethod
    def _redact_key_value(match: Match[str]) -> str:
        double_value = match.group("double_value")
        single_value = match.group("single_value")
        value = double_value or single_value or match.group("unquoted_value") or ""
        if not value or value == REDACTION_MARKER:
            return match.group(0)
        key_quote = match.group("key_quote") or ""
        quote = '"' if double_value is not None else "'" if single_value is not None else ""
        return (
            f"{key_quote}{match.group('key')}{key_quote}{match.group('separator')}"
            f"{quote}{REDACTION_MARKER}{quote}"
        )


def sanitize_text(text: str) -> str:
    """Return repository text with high-confidence credential values redacted."""
    return Sanitizer().sanitize(text)


__all__ = [
    "MAX_QUOTED_SECRET_CHARS",
    "REDACTION_MARKER",
    "Sanitizer",
    "sanitize_text",
]
