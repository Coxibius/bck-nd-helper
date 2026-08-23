"""Safe lexical helpers shared by the Go and Rust UML fallbacks.

The helpers deliberately avoid native parser calls.  They mask comments and
string literals while preserving source offsets, then locate balanced blocks
and parameter lists in ordinary Python.  Language-specific parsers can merge
this deterministic fallback with optional Tree-sitter visitor results.
"""
from __future__ import annotations

import re
from typing import Iterator, Pattern, Tuple


def _blank_range(chars: list[str], source: str, start: int, end: int) -> None:
    """Replace a lexical range with spaces while preserving line breaks."""
    for index in range(start, min(end, len(chars))):
        if source[index] not in "\r\n":
            chars[index] = " "


def mask_non_code(source: str) -> str:
    """Mask comments and literals without changing source length.

    Supports Go raw strings, Rust raw strings, escaped quoted strings, character
    literals, line comments, and nested block comments.  Keeping offsets stable
    lets regex matches against the masked text slice the original source safely.
    """
    chars = list(source)
    length = len(source)
    index = 0

    while index < length:
        # Line comment.
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            if end < 0:
                end = length
            _blank_range(chars, source, index, end)
            index = end
            continue

        # Nested block comments are valid in Rust; accepting nesting is harmless
        # for Go and prevents braces inside comments from affecting balancing.
        if source.startswith("/*", index):
            depth = 1
            cursor = index + 2
            while cursor < length and depth:
                if source.startswith("/*", cursor):
                    depth += 1
                    cursor += 2
                elif source.startswith("*/", cursor):
                    depth -= 1
                    cursor += 2
                else:
                    cursor += 1
            _blank_range(chars, source, index, cursor)
            index = cursor
            continue

        # Rust raw string: r"...", r#"..."#, r##"..."##, etc.
        if source[index] == "r":
            cursor = index + 1
            while cursor < length and source[cursor] == "#":
                cursor += 1
            if cursor < length and source[cursor] == '"':
                hashes = source[index + 1:cursor]
                terminator = '"' + hashes
                end = source.find(terminator, cursor + 1)
                end = length if end < 0 else end + len(terminator)
                _blank_range(chars, source, index, end)
                index = end
                continue

        # Go raw strings and regular quoted strings.
        if source[index] in {'"', '`'}:
            quote = source[index]
            cursor = index + 1
            while cursor < length:
                if quote == '"' and source[cursor] == "\\":
                    cursor += 2
                    continue
                if source[cursor] == quote:
                    cursor += 1
                    break
                cursor += 1
            _blank_range(chars, source, index, cursor)
            index = cursor
            continue

        # Treat only short, closed single-quoted sequences as character literals;
        # this avoids confusing Rust lifetimes such as `'a` with strings.
        if source[index] == "'":
            cursor = index + 1
            if cursor < length and source[cursor] == "\\":
                cursor += 2
            else:
                cursor += 1
            if cursor < length and source[cursor] == "'":
                cursor += 1
                _blank_range(chars, source, index, cursor)
                index = cursor
                continue

        index += 1

    return "".join(chars)


def find_matching(
    masked_source: str,
    open_index: int,
    open_char: str,
    close_char: str,
) -> int:
    """Return the matching delimiter index, or ``-1`` for malformed input."""
    if open_index < 0 or open_index >= len(masked_source):
        return -1
    if masked_source[open_index] != open_char:
        return -1

    depth = 0
    for index in range(open_index, len(masked_source)):
        char = masked_source[index]
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
    return -1


def iter_balanced_blocks(
    source: str,
    pattern: str | Pattern[str],
    *,
    flags: int = re.MULTILINE,
) -> Iterator[Tuple[re.Match[str], str]]:
    """Yield declaration matches and their balanced ``{...}`` body text."""
    masked = mask_non_code(source)
    regex = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
    consumed_until = -1
    for match in regex.finditer(masked):
        if match.start() < consumed_until:
            continue
        open_index = masked.rfind("{", match.start(), match.end())
        if open_index < 0:
            continue
        close_index = find_matching(masked, open_index, "{", "}")
        if close_index < 0:
            continue
        consumed_until = close_index + 1
        yield match, source[open_index + 1:close_index]


def split_top_level(text: str, separators: str = ",") -> list[str]:
    """Split on separators only when not nested inside delimiters."""
    masked = mask_non_code(text)
    depths = {"(": 0, "[": 0, "{": 0, "<": 0}
    closing = {")": "(", "]": "[", "}": "{", ">": "<"}
    parts: list[str] = []
    start = 0

    for index, char in enumerate(masked):
        if char in depths:
            depths[char] += 1
        elif char in closing:
            opener = closing[char]
            depths[opener] = max(0, depths[opener] - 1)
        elif char in separators and not any(depths.values()):
            part = text[start:index].strip()
            if part:
                parts.append(part)
            start = index + 1

    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def compact(text: str) -> str:
    """Collapse insignificant whitespace while keeping signatures readable."""
    value = " ".join(text.strip().split())
    value = re.sub(r"\s*,\s*", ", ", value)
    value = re.sub(r"\s*:\s*", ": ", value)
    return value
