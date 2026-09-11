"""Git parity and fail-closed policy tests for the incremental ignore matcher."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import bck_nd_hlpr.core.utils.gitignore_parser as gitignore_module
from bck_nd_hlpr.core.context_dumper import ContextDumper
from bck_nd_hlpr.core.scanner import ProjectScanner
from bck_nd_hlpr.core.tree_generator import generate_project_tree
from bck_nd_hlpr.core.utils.gitignore_parser import (
    GitIgnoreMatcher,
    GitIgnorePolicyError,
    parse_gitignore,
)
from bck_nd_hlpr.core.utils.indexer import FileSystemIndexer


def _write(root: Path, relative: str, content: str = "fixture") -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _relative_files(index, root: Path) -> list[str]:
    return [path.relative_to(root).as_posix() for path in index.all_files]


def test_trailing_spaces_are_normalized_without_losing_escaped_spaces(tmp_path):
    (tmp_path / ".gitignore").write_bytes(
        b"secret.py   \nliteral\\ \nname\\  \n\\#file\n\\!file\n"
    )

    patterns = parse_gitignore(tmp_path)

    assert patterns == [
        "secret.py",
        "literal\\ ",
        "name\\ ",
        "\\#file",
        "\\!file",
    ]
    assert gitignore_module._compile_expression(patterns[1]).fullmatch("literal ")
    assert gitignore_module._compile_expression(patterns[2]).fullmatch("name ")


@pytest.mark.parametrize(
    ("pattern", "matches", "misses"),
    [
        ("[a-z].pem", "b.pem", "B.pem"),
        ("[0-9].log", "7.log", "x.log"),
        ("[!a-c].pem", "d.pem", "b.pem"),
        ("[^a-c].cfg", "z.cfg", "a.cfg"),
        ("[-a].dash", "-.dash", "b.dash"),
        ("[a-].tail", "-.tail", "b.tail"),
        ("[]a].bracket", "].bracket", "b.bracket"),
        (r"[\-].escaped", "-.escaped", "a.escaped"),
    ],
)
def test_character_classes_preserve_ranges_and_literals(pattern, matches, misses):
    expression = gitignore_module._compile_expression(pattern)

    assert expression.fullmatch(matches)
    assert expression.fullmatch(misses) is None
    assert expression.fullmatch(f"dir/{matches}") is None


def test_unclosed_or_invalid_classes_are_literal_and_never_raise():
    unclosed = gitignore_module._compile_expression("[abc.pem")
    invalid_range = gitignore_module._compile_expression("[z-a].pem")

    assert unclosed.fullmatch("[abc.pem")
    assert invalid_range.fullmatch("z.pem") is None


def test_git_check_ignore_matches_representative_pathname_patterns(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git executable unavailable")

    patterns = (
        "[a-z].pem\n[0-9].log\n[!a-c].crt\n[^m-o].cfg\n"
        "[-a].dash\n[a-].tail\n[]a].bracket\n"
        "src/*/token.txt\nsrc/**/deep.txt\n"
    )
    (tmp_path / ".gitignore").write_text(patterns, encoding="utf-8")
    subprocess.run(
        ["git", "init", "-q"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "core.ignorecase", "false"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    cases = {
        "b.pem": True,
        "B.pem": False,
        "7.log": True,
        "x.log": False,
        "d.crt": True,
        "b.crt": False,
        "z.cfg": True,
        "n.cfg": False,
        "-.dash": True,
        "-.tail": True,
        "].bracket": True,
        "src/one/token.txt": True,
        "src/one/two/token.txt": False,
        "src/one/two/deep.txt": True,
    }
    for relative in cases:
        _write(tmp_path, relative)

    matcher = GitIgnoreMatcher(tmp_path)
    for relative, expected in cases.items():
        git_result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", "--", relative],
            cwd=tmp_path,
            check=False,
            capture_output=True,
        )
        assert git_result.returncode in {0, 1}
        assert (git_result.returncode == 0) is expected
        assert matcher.matches(tmp_path / relative, is_dir=False) is expected


def test_exact_rule_limit_is_valid_and_next_rule_blocks_root(tmp_path, monkeypatch):
    monkeypatch.setattr(gitignore_module, "_MAX_RULES_PER_FILE", 2)
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("first.py\n# comment\n\nsecond.py\n", encoding="utf-8")

    valid = GitIgnoreMatcher(tmp_path)

    assert valid.diagnostics == ()
    assert valid.matches(tmp_path / "first.py", is_dir=False) is True
    assert valid.matches(tmp_path / "visible.py", is_dir=False) is False

    gitignore.write_text("first.py\nsecond.py\n!first.py\n", encoding="utf-8")
    blocked = GitIgnoreMatcher(tmp_path)

    assert blocked.matches(tmp_path / "first.py", is_dir=False) is True
    assert blocked.matches(tmp_path / "visible.py", is_dir=False) is True
    assert blocked.diagnostics[0].code == "GITIGNORE_POLICY_LIMIT"
    assert blocked.diagnostics[0].scope == "."
    assert len(blocked.diagnostics) == 1
    assert blocked._rules_by_base[()] == ()
    with pytest.raises(GitIgnorePolicyError) as error:
        parse_gitignore(tmp_path)
    assert error.value.code == "GITIGNORE_POLICY_LIMIT"


def test_exact_pattern_limit_is_valid_and_larger_pattern_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(gitignore_module, "_MAX_PATTERN_CHARS", 4)
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("a*bc\n", encoding="utf-8")

    valid = GitIgnoreMatcher(tmp_path)

    assert valid.diagnostics == ()
    assert valid.matches(tmp_path / "axbc", is_dir=False) is True

    gitignore.write_text("abcde\n", encoding="utf-8")
    blocked = GitIgnoreMatcher(tmp_path)

    assert blocked.matches(tmp_path / "anything.py", is_dir=False) is True
    assert blocked.diagnostics[0].code == "GITIGNORE_POLICY_LIMIT"


def test_real_pattern_limit_blocks_without_exposing_pattern(tmp_path):
    secret_pattern = "SENSITIVE_" + (
        "x" * (gitignore_module._MAX_PATTERN_CHARS + 1)
    )
    (tmp_path / ".gitignore").write_text(secret_pattern + "\n", encoding="utf-8")

    matcher = GitIgnoreMatcher(tmp_path)
    serialized = json.dumps(
        [diagnostic.__dict__ for diagnostic in matcher.diagnostics]
    )

    assert matcher.matches(tmp_path / "visible.py", is_dir=False) is True
    assert matcher.diagnostics[0].code == "GITIGNORE_POLICY_LIMIT"
    assert "SENSITIVE_" not in serialized
    assert str(tmp_path) not in serialized


def test_nested_overflow_blocks_only_its_scope_across_consumers(tmp_path, monkeypatch):
    monkeypatch.setattr(gitignore_module, "_MAX_RULES_PER_FILE", 1)
    _write(tmp_path, "frontend/.gitignore", "*.tmp\n!keep.tmp\n")
    _write(tmp_path, "frontend/secret.py", "class FrontendSecret:\n    pass\n")
    _write(tmp_path, "backend/main.py", "class VisibleBackend:\n    pass\n")

    first_index = FileSystemIndexer(str(tmp_path), max_depth=5).build()
    second_index = FileSystemIndexer(str(tmp_path), max_depth=5).build()
    first_paths = _relative_files(first_index, tmp_path)
    second_paths = _relative_files(second_index, tmp_path)
    tree_first = generate_project_tree(str(tmp_path), depth=5)
    tree_second = generate_project_tree(str(tmp_path), depth=5)
    core_paths = [
        item["path"]
        for item in ContextDumper(
            path=str(tmp_path), depth=5, include_prd=False
        ).get_core_files()
    ]
    uml = ProjectScanner().scan_uml(str(tmp_path), max_depth=5)

    assert first_paths == second_paths
    assert "backend/main.py" in first_paths
    assert not any(path.startswith("frontend/") for path in first_paths)
    assert tree_first == tree_second
    assert "frontend/" in tree_first
    assert "secret.py" not in tree_first
    assert "backend/main.py" in core_paths
    assert not any(path.startswith("frontend/") for path in core_paths)
    assert "VisibleBackend" in uml
    assert "FrontendSecret" not in uml


def test_root_overflow_blocks_all_descendants_and_cannot_be_negated(tmp_path, monkeypatch):
    monkeypatch.setattr(gitignore_module, "_MAX_RULES_PER_FILE", 1)
    _write(tmp_path, ".gitignore", "secret.py\n!secret.py\n")
    _write(tmp_path, "secret.py", "class RootSecret:\n    pass\n")
    _write(tmp_path, "src/visible.py", "class AlsoBlocked:\n    pass\n")

    matcher = GitIgnoreMatcher(tmp_path)
    index = FileSystemIndexer(str(tmp_path), max_depth=5).build()
    tree = generate_project_tree(str(tmp_path), depth=5)
    core = ContextDumper(
        path=str(tmp_path), depth=5, include_prd=False
    ).get_core_files()
    uml = ProjectScanner().scan_uml(str(tmp_path), max_depth=5)

    assert matcher.matches(tmp_path / "secret.py", is_dir=False) is True
    assert matcher.matches(tmp_path / "src" / "visible.py", is_dir=False) is True
    assert index.all_files == []
    assert "secret.py" not in tree
    assert "visible.py" not in tree
    assert core == []
    assert "RootSecret" not in uml
    assert "AlsoBlocked" not in uml


def test_invalid_utf8_blocks_scope_with_neutral_single_diagnostic(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / ".gitignore").write_bytes(b"*.tmp\n\xff\n")

    matcher = GitIgnoreMatcher(tmp_path)
    target = frontend / "anything.py"

    assert matcher.matches(target, is_dir=False) is True
    assert matcher.matches(target, is_dir=False) is True
    assert len(matcher.diagnostics) == 1
    diagnostic = matcher.diagnostics[0]
    assert diagnostic.code == "GITIGNORE_SOURCE_READ_ERROR"
    assert diagnostic.scope == "frontend"
    assert str(tmp_path) not in diagnostic.message
    assert "anything.py" not in diagnostic.message
