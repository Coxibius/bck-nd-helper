"""Incremental, pathname-aware ``.gitignore`` matching with legacy helpers."""

import os
import re
import stat
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Pattern, Sequence, Set, Tuple, Union

from bck_nd_hlpr.core.sanitizer import sanitize_text


_MAX_PATTERN_CHARS = 4096
_MAX_RULES_PER_FILE = 10_000
_READ_CHUNK_CHARS = 8192

_POLICY_MESSAGES = {
    "GITIGNORE_POLICY_LIMIT": (
        "Ignore policy exceeded supported safety limits; scope excluded."
    ),
    "GITIGNORE_SOURCE_UNSAFE": (
        "Ignore policy source is not a verified regular file; scope excluded."
    ),
    "GITIGNORE_SOURCE_READ_ERROR": (
        "Ignore policy could not be read completely; scope excluded."
    ),
}


@dataclass(frozen=True)
class GitIgnoreDiagnostic:
    """Stable, path-neutral diagnostic for one blocked ignore-policy scope."""

    code: str
    scope: str
    message: str


class GitIgnorePolicyError(RuntimeError):
    """A direct ignore-policy read could not produce a complete policy."""

    def __init__(self, code: str, scope: str = ".") -> None:
        self.code = code
        self.scope = scope
        self.message = _POLICY_MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True)
class _GitIgnoreRule:
    base_parts: Tuple[str, ...]
    pattern: str
    expression: Pattern[str]
    negated: bool
    directory_only: bool
    pathname: bool


def _stat_is_link_or_reparse(path_stat: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(path_stat.st_mode) or bool(
        getattr(path_stat, "st_file_attributes", 0) & reparse_flag
    )


def _is_link_or_reparse(path: Path) -> bool:
    try:
        return _stat_is_link_or_reparse(path.lstat())
    except OSError:
        return True


def _source_state(path_stat: os.stat_result) -> Tuple[int, int, int, int, int]:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        stat.S_IFMT(path_stat.st_mode),
        path_stat.st_size,
        path_stat.st_mtime_ns,
    )


def _pattern_has_effect(line: str) -> bool:
    text = line
    escaped_leading = text.startswith("\\!") or text.startswith("\\#")
    if escaped_leading:
        text = text[1:]
    elif text.startswith("#"):
        return False
    elif text.startswith("!"):
        text = text[1:]
    if text.endswith("/") and not text.endswith("\\/"):
        text = text[:-1]
    if text.startswith("/"):
        text = text[1:]
    return bool(text)


def _normalize_trailing_spaces(line: str) -> str:
    """Remove only unescaped trailing spaces while retaining Git escapes."""
    space_start = len(line)
    while space_start > 0 and line[space_start - 1] == " ":
        space_start -= 1
    if space_start == len(line):
        return line
    slash_count = 0
    slash_index = space_start - 1
    while slash_index >= 0 and line[slash_index] == "\\":
        slash_count += 1
        slash_index -= 1
    if slash_count % 2:
        return line[:space_start] + " "
    return line[:space_start]


def _finish_streamed_line(
    characters: List[str],
    pending_spaces: int,
    comment: bool,
) -> Optional[str]:
    if comment:
        return None
    if pending_spaces:
        slash_count = 0
        slash_index = len(characters) - 1
        while slash_index >= 0 and characters[slash_index] == "\\":
            slash_count += 1
            slash_index -= 1
        if slash_count % 2:
            if len(characters) >= _MAX_PATTERN_CHARS:
                raise GitIgnorePolicyError("GITIGNORE_POLICY_LIMIT")
            characters.append(" ")
    line = "".join(characters)
    if not _pattern_has_effect(line):
        return None
    return line


def _iter_actionable_patterns(handle) -> Iterable[str]:
    """Yield normalized rules while keeping memory bounded by the rule limit."""
    characters: List[str] = []
    pending_spaces = 0
    comment = False
    started = False

    while True:
        chunk = handle.read(_READ_CHUNK_CHARS)
        if not chunk:
            if started:
                line = _finish_streamed_line(
                    characters,
                    pending_spaces,
                    comment,
                )
                if line is not None:
                    yield line
            return

        for character in chunk:
            if character == "\n":
                line = _finish_streamed_line(
                    characters,
                    pending_spaces,
                    comment,
                )
                if line is not None:
                    yield line
                characters = []
                pending_spaces = 0
                comment = False
                started = False
                continue

            if not started:
                started = True
                if character == "#":
                    comment = True
                    continue
            if comment:
                continue
            if character == " ":
                pending_spaces += 1
                continue
            if pending_spaces:
                if len(characters) + pending_spaces > _MAX_PATTERN_CHARS:
                    raise GitIgnorePolicyError("GITIGNORE_POLICY_LIMIT")
                characters.extend(" " for _ in range(pending_spaces))
                pending_spaces = 0
            if len(characters) >= _MAX_PATTERN_CHARS:
                raise GitIgnorePolicyError("GITIGNORE_POLICY_LIMIT")
            characters.append(character)


def _read_patterns(gitignore_path: Path) -> List[str]:
    """Read one complete, bounded and verified ignore policy."""
    gitignore_path = Path(gitignore_path)
    try:
        path_stat = gitignore_path.lstat()
    except FileNotFoundError:
        return []
    except OSError:
        raise GitIgnorePolicyError("GITIGNORE_SOURCE_READ_ERROR") from None
    if _is_link_or_reparse(gitignore_path) or not stat.S_ISREG(path_stat.st_mode):
        raise GitIgnorePolicyError("GITIGNORE_SOURCE_UNSAFE")

    initial_state = _source_state(path_stat)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = None
    try:
        descriptor = os.open(str(gitignore_path), flags)
        opened_stat = os.fstat(descriptor)
        if (
            _stat_is_link_or_reparse(opened_stat)
            or not stat.S_ISREG(opened_stat.st_mode)
            or _source_state(opened_stat) != initial_state
        ):
            raise GitIgnorePolicyError("GITIGNORE_SOURCE_UNSAFE")

        patterns: List[str] = []
        with os.fdopen(
            descriptor,
            "r",
            encoding="utf-8",
            errors="strict",
            newline=None,
        ) as handle:
            descriptor = None
            for line in _iter_actionable_patterns(handle):
                if len(patterns) >= _MAX_RULES_PER_FILE:
                    raise GitIgnorePolicyError("GITIGNORE_POLICY_LIMIT")
                patterns.append(line)
            final_descriptor_stat = os.fstat(handle.fileno())

        final_path_stat = gitignore_path.lstat()
        if (
            _stat_is_link_or_reparse(final_path_stat)
            or not stat.S_ISREG(final_path_stat.st_mode)
            or _source_state(final_descriptor_stat) != initial_state
            or _source_state(final_path_stat) != initial_state
        ):
            raise GitIgnorePolicyError("GITIGNORE_SOURCE_READ_ERROR")
        return patterns
    except GitIgnorePolicyError:
        raise
    except (OSError, UnicodeError):
        raise GitIgnorePolicyError("GITIGNORE_SOURCE_READ_ERROR") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def parse_gitignore(root: Path) -> List[str]:
    """Return root ``.gitignore`` rules, retaining negation for compatibility."""
    return _read_patterns(Path(root) / ".gitignore")


def _class_expression(
    tokens: List[Tuple[str, bool]],
    negated: bool,
) -> Optional[str]:
    """Compile one valid Git character class without allowing path separators."""
    pieces: List[str] = []
    for index, (character, escaped) in enumerate(tokens):
        if character == "-" and not escaped:
            if index == 0 or index == len(tokens) - 1:
                pieces.append(r"\-")
            else:
                pieces.append("-")
        else:
            pieces.append(re.escape(character))
    if not pieces:
        return None
    content = "".join(pieces)
    expression = f"[^/{content}]" if negated else f"(?!/)[{content}]"
    try:
        re.compile(expression)
    except re.error:
        return None
    return expression


def _parse_character_class(
    pattern: str,
    start: int,
) -> Optional[Tuple[str, int]]:
    cursor = start + 1
    if cursor >= len(pattern):
        return None
    negated = pattern[cursor] in {"!", "^"}
    if negated:
        cursor += 1
    tokens: List[Tuple[str, bool]] = []
    if cursor < len(pattern) and pattern[cursor] == "]":
        tokens.append(("]", False))
        cursor += 1
    while cursor < len(pattern):
        character = pattern[cursor]
        if character == "]" and tokens:
            expression = _class_expression(tokens, negated)
            if expression is None:
                return None
            return expression, cursor
        if character == "\\" and cursor + 1 < len(pattern):
            cursor += 1
            tokens.append((pattern[cursor], True))
        else:
            tokens.append((character, False))
        cursor += 1
    return None


@lru_cache(maxsize=8192)
def _compile_expression(pattern: str) -> Pattern[str]:
    """Translate the supported Git wildmatch subset into a linear regex."""
    pieces: List[str] = ["^"]
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                while index < len(pattern) and pattern[index] == "*":
                    index += 1
                if index < len(pattern) and pattern[index] == "/":
                    pieces.append("(?:[^/]+/)*")
                    index += 1
                else:
                    pieces.append(".*")
                continue
            pieces.append("[^/]*")
        elif character == "?":
            pieces.append("[^/]")
        elif character == "[":
            compiled_class = _parse_character_class(pattern, index)
            if compiled_class is None:
                pieces.append(re.escape(character))
            else:
                class_expression, closing = compiled_class
                pieces.append(class_expression)
                index = closing
        elif character == "\\" and index + 1 < len(pattern):
            index += 1
            pieces.append(re.escape(pattern[index]))
        else:
            pieces.append(re.escape(character))
        index += 1
    pieces.append("$")
    try:
        return re.compile("".join(pieces))
    except re.error:
        return re.compile(f"^{re.escape(pattern)}$")


def _compile_rules(
    patterns: Iterable[str],
    base_parts: Tuple[str, ...],
) -> List[_GitIgnoreRule]:
    rules: List[_GitIgnoreRule] = []
    for raw_pattern in patterns:
        text = _normalize_trailing_spaces(str(raw_pattern).rstrip("\r\n"))
        if not _pattern_has_effect(text):
            continue
        if len(text) > _MAX_PATTERN_CHARS:
            raise GitIgnorePolicyError("GITIGNORE_POLICY_LIMIT")
        escaped_leading = text.startswith("\\!") or text.startswith("\\#")
        if escaped_leading:
            text = text[1:]
        elif text.startswith("#"):
            continue
        negated = not escaped_leading and text.startswith("!")
        if negated:
            text = text[1:]
        directory_only = text.endswith("/") and not text.endswith("\\/")
        if directory_only:
            text = text[:-1]
        anchored = text.startswith("/")
        if anchored:
            text = text[1:]
        if not text:
            continue
        pathname = anchored or "/" in text
        rules.append(
            _GitIgnoreRule(
                base_parts=base_parts,
                pattern=text,
                expression=_compile_expression(text),
                negated=negated,
                directory_only=directory_only,
                pathname=pathname,
            )
        )
    return rules


def _rule_matches(
    rule: _GitIgnoreRule,
    rel_parts: Tuple[str, ...],
    is_dir: bool,
) -> bool:
    if (
        len(rel_parts) < len(rule.base_parts)
        or rel_parts[: len(rule.base_parts)] != rule.base_parts
    ):
        return False
    local_parts = rel_parts[len(rule.base_parts) :]
    if not local_parts:
        return False

    if not rule.pathname:
        for index, part in enumerate(local_parts):
            if rule.expression.fullmatch(part) is None:
                continue
            part_is_dir = index < len(local_parts) - 1 or is_dir
            if not rule.directory_only or part_is_dir:
                return True
        return False

    for length in range(1, len(local_parts) + 1):
        local = "/".join(local_parts[:length])
        if rule.expression.fullmatch(local) is None:
            continue
        matched_is_dir = length < len(local_parts) or is_dir
        if not rule.directory_only or matched_is_dir:
            return True
    return False


class GitIgnoreMatcher:
    """Load root and nested ignore rules only as traversal reaches them."""

    def __init__(self, root: Union[str, Path]) -> None:
        self.root = Path(root).resolve()
        self._rules_by_base: Dict[Tuple[str, ...], Tuple[_GitIgnoreRule, ...]] = {}
        self._inspected_bases: Set[Tuple[str, ...]] = set()
        self._blocked_scopes: Set[Tuple[str, ...]] = set()
        self._diagnostics: List[GitIgnoreDiagnostic] = []
        self._diagnostic_keys: Set[Tuple[Tuple[str, ...], str]] = set()
        self.load_directory(self.root)

    @property
    def diagnostics(self) -> Tuple[GitIgnoreDiagnostic, ...]:
        """Return deterministic diagnostics for scopes excluded fail-closed."""
        return tuple(self._diagnostics)

    def _record_blocked_scope(
        self,
        base_parts: Tuple[str, ...],
        code: str,
    ) -> None:
        self._blocked_scopes.add(base_parts)
        key = (base_parts, code)
        if key in self._diagnostic_keys:
            return
        self._diagnostic_keys.add(key)
        relative_scope = "/".join(base_parts) if base_parts else "."
        self._diagnostics.append(
            GitIgnoreDiagnostic(
                code=code,
                scope=sanitize_text(relative_scope),
                message=_POLICY_MESSAGES[code],
            )
        )

    def _scope_is_blocked(self, rel_parts: Tuple[str, ...]) -> bool:
        return any(
            len(rel_parts) > len(scope)
            and rel_parts[: len(scope)] == scope
            for scope in self._blocked_scopes
        )

    def _relative_parts(self, path: Union[str, Path]) -> Optional[Tuple[str, ...]]:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        try:
            return tuple(candidate.relative_to(self.root).parts)
        except ValueError:
            return None

    def load_directory(self, current_directory: Union[str, Path]) -> None:
        """Inspect exactly one directory's ``.gitignore`` and cache the result."""
        base_parts = self._relative_parts(current_directory)
        if base_parts is None or base_parts in self._inspected_bases:
            return
        self._inspected_bases.add(base_parts)
        directory = self.root.joinpath(*base_parts)
        try:
            patterns = _read_patterns(directory / ".gitignore")
            rules = _compile_rules(patterns, base_parts)
        except GitIgnorePolicyError as error:
            self._rules_by_base[base_parts] = ()
            self._record_blocked_scope(base_parts, error.code)
            return
        self._rules_by_base[base_parts] = tuple(rules)

    def _evaluate(
        self,
        rel_parts: Tuple[str, ...],
        *,
        is_dir: bool,
    ) -> bool:
        if self._scope_is_blocked(rel_parts):
            return True
        ignored = False
        for length in range(0, len(rel_parts) + 1):
            base = rel_parts[:length]
            for rule in self._rules_by_base.get(base, ()):
                if _rule_matches(rule, rel_parts, is_dir):
                    ignored = not rule.negated
        return ignored

    def _ignored_parent(self, rel_parts: Tuple[str, ...]) -> bool:
        for length in range(1, len(rel_parts)):
            if self._evaluate(rel_parts[:length], is_dir=True):
                return True
        return False

    def _load_parent_chain(
        self,
        rel_parts: Tuple[str, ...],
        *,
        is_dir: bool,
    ) -> bool:
        directory_length = len(rel_parts) if is_dir else max(0, len(rel_parts) - 1)
        for length in range(0, directory_length + 1):
            base = rel_parts[:length]
            if base and self._evaluate(base, is_dir=True):
                return False
            self.load_directory(self.root.joinpath(*base))
            if self._scope_is_blocked(rel_parts):
                return False
        return True

    def matches(
        self,
        path: Union[str, Path],
        *,
        is_dir: Optional[bool] = None,
        load_parents: bool = True,
    ) -> bool:
        candidate = Path(path)
        rel_parts = self._relative_parts(candidate)
        if rel_parts is None or not rel_parts:
            return False
        directory = candidate.is_dir() if is_dir is None else is_dir
        if load_parents and not self._load_parent_chain(
            rel_parts,
            is_dir=directory,
        ):
            return True
        if self._ignored_parent(rel_parts):
            return True
        return self._evaluate(rel_parts, is_dir=directory)


def matches_gitignore(
    path: Path,
    root: Path,
    patterns: Union[Sequence[str], GitIgnoreMatcher],
) -> bool:
    """Compatibility adapter for callers that still pass root rule strings."""
    if isinstance(patterns, GitIgnoreMatcher):
        return patterns.matches(path)
    candidate = Path(path)
    try:
        rel_parts = tuple(candidate.relative_to(Path(root)).parts)
    except ValueError:
        return False
    ignored = False
    is_dir = candidate.is_dir()
    rules = _compile_rules(patterns, ())
    for length in range(1, len(rel_parts)):
        parent = rel_parts[:length]
        parent_ignored = False
        for rule in rules:
            if _rule_matches(rule, parent, True):
                parent_ignored = not rule.negated
        if parent_ignored:
            return True
    for rule in rules:
        if _rule_matches(rule, rel_parts, is_dir):
            ignored = not rule.negated
    return ignored


__all__ = [
    "GitIgnoreDiagnostic",
    "GitIgnoreMatcher",
    "GitIgnorePolicyError",
    "matches_gitignore",
    "parse_gitignore",
]
