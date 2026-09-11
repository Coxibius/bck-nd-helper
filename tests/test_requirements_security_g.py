"""Security Closure G regressions for bounded Requirements handling."""

import inspect
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import bck_nd_hlpr.core.requirements.parser as parser_module
import bck_nd_hlpr.core.requirements.renderer as renderer_module
from bck_nd_hlpr.cli.mcp_server import get_requirements_summary
from bck_nd_hlpr.core.context_dumper import ContextDumper
from bck_nd_hlpr.core.requirements import (
    MAX_REQUIREMENT_FILES,
    MAX_REQUIREMENT_JSON_DEPTH,
    MAX_REQUIREMENT_JSON_NODES,
    MAX_REQUIREMENT_SOURCE_BYTES,
    MAX_REQUIREMENTS_DIRECTORY_ENTRIES,
    MAX_REQUIREMENTS_CONTEXT_CHARS,
    MAX_REQUIREMENTS_TOTAL_BYTES,
    RequirementSpecification,
    RequirementsLoadResult,
    RequirementsParser,
    UserStory,
)
from bck_nd_hlpr.core.requirements.renderer import (
    REQUIREMENTS_COLLECTION_REJECTED,
    REQUIREMENTS_TRUNCATION_MARKER,
    build_requirements_context,
    build_requirements_summary,
)
from bck_nd_hlpr.core.sanitizer import REDACTION_MARKER


def _requirements_dir(root: Path) -> Path:
    target = root / ".bck-nd" / "requirements"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _story_bytes(story_id: str, *, title: str = "Title") -> bytes:
    return json.dumps(
        {"story": {"id": story_id, "title": title, "status": "TODO"}},
        separators=(",", ":"),
    ).encode("utf-8")


def _write_json(root: Path, story_id: str, *, title: str = "Title") -> Path:
    target = _requirements_dir(root) / f"{story_id}.json"
    target.write_bytes(_story_bytes(story_id, title=title))
    return target


def test_canonical_requirements_limits_are_public():
    assert MAX_REQUIREMENT_FILES == 512
    assert MAX_REQUIREMENT_SOURCE_BYTES == 1024 * 1024
    assert MAX_REQUIREMENTS_DIRECTORY_ENTRIES == 4096
    assert MAX_REQUIREMENTS_TOTAL_BYTES == 8 * 1024 * 1024
    assert MAX_REQUIREMENT_JSON_DEPTH == 64
    assert MAX_REQUIREMENT_JSON_NODES == 10_000
    assert MAX_REQUIREMENTS_CONTEXT_CHARS == 12_000


def test_collection_accepts_exact_file_limit_and_rejects_next(tmp_path, monkeypatch):
    reduced_limit = 4
    monkeypatch.setattr(parser_module, "MAX_REQUIREMENT_FILES", reduced_limit)
    req_dir = _requirements_dir(tmp_path)
    for index in range(reduced_limit):
        (req_dir / f"US-{index:04d}.md").write_text(
            f"# US{index:04d} [TODO] - Story\n", encoding="utf-8"
        )

    accepted = RequirementsParser.load_collection(tmp_path)
    assert accepted.rejected is False
    assert len(accepted.specifications) == reduced_limit

    (req_dir / "US-OVER.md").write_text("# US9999 [TODO] - Over\n", encoding="utf-8")
    rejected = RequirementsParser.load_collection(tmp_path)
    assert rejected.rejected is True
    assert rejected.error_code == "REQUIREMENTS_COLLECTION_LIMIT"
    assert RequirementsParser.load_from_directory(tmp_path) == []


def test_collection_accepts_exact_total_bytes_and_rejects_next(tmp_path, monkeypatch):
    req_dir = _requirements_dir(tmp_path)
    sources = [_story_bytes("US-001"), _story_bytes("US-002")]
    reduced_limit = sum(map(len, sources))
    monkeypatch.setattr(parser_module, "MAX_REQUIREMENTS_TOTAL_BYTES", reduced_limit)
    for index, content in enumerate(sources, 1):
        (req_dir / f"US-{index:03d}.json").write_bytes(content)

    accepted = RequirementsParser.load_collection(tmp_path)
    assert accepted.rejected is False
    assert len(accepted.specifications) == len(sources)

    (req_dir / "OVER.md").write_bytes(b"x")
    rejected = RequirementsParser.load_collection(tmp_path)
    assert rejected.rejected is True
    assert rejected.error_code == "REQUIREMENTS_COLLECTION_LIMIT"
    assert rejected.specifications == ()


def test_collection_enumeration_is_deterministic_and_counts_only_supported_files(
    tmp_path,
):
    req_dir = _requirements_dir(tmp_path)
    for filename, story_id in (
        ("z-last.md", "US0003"),
        ("A-first.json", "US-001"),
        ("m-middle.markdown", "US0002"),
    ):
        if filename.endswith(".json"):
            (req_dir / filename).write_bytes(_story_bytes(story_id))
        else:
            (req_dir / filename).write_text(
                f"# {story_id} [TODO] - Story\n", encoding="utf-8"
            )
    (req_dir / "ignored.txt").write_text("not a requirement", encoding="utf-8")

    first = RequirementsParser.load_collection(tmp_path)
    second = RequirementsParser.load_collection(tmp_path)

    assert [spec.story.id for spec in first.specifications] == [
        "US-001",
        "US0002",
        "US0003",
    ]
    assert first == second


def test_collection_checks_actual_accumulated_bytes_without_partial_results(
    tmp_path, monkeypatch
):
    first = _write_json(tmp_path, "US-001")
    second = _write_json(tmp_path, "US-002")
    actual_total = len(first.read_bytes()) + len(second.read_bytes())
    monkeypatch.setattr(parser_module, "MAX_REQUIREMENTS_TOTAL_BYTES", actual_total - 1)
    monkeypatch.setattr(
        RequirementsParser,
        "_safe_requirement_files",
        classmethod(
            lambda _cls, _root: (
                [first, second],
                first.parent,
                tmp_path,
                (),
            )
        ),
    )

    result = RequirementsParser.load_collection(tmp_path)

    assert result.rejected is True
    assert result.specifications == ()


def test_requirement_source_accepts_exact_limit_and_rejects_next(tmp_path):
    req_dir = _requirements_dir(tmp_path)
    exact = req_dir / "US-EXACT.md"
    prefix = "# US0001 [TODO] - "
    exact.write_bytes((prefix + "x" * (MAX_REQUIREMENT_SOURCE_BYTES - len(prefix))).encode())
    assert RequirementsParser.parse_file(exact) is not None

    over = req_dir / "US-OVER.md"
    over.write_bytes(b"x" * (MAX_REQUIREMENT_SOURCE_BYTES + 1))
    assert RequirementsParser.parse_file(over) is None


def _nested_json(depth: int) -> bytes:
    return (
        '{"story":{"id":"US-DEPTH"},"extra":'
        + ("[" * depth)
        + "0"
        + ("]" * depth)
        + "}"
    ).encode()


def test_json_depth_exact_limit_and_next_are_controlled(tmp_path):
    req_dir = _requirements_dir(tmp_path)
    exact = req_dir / "US-DEPTH.json"
    exact.write_bytes(_nested_json(MAX_REQUIREMENT_JSON_DEPTH - 1))
    assert RequirementsParser.parse_file(exact) is not None

    exact.write_bytes(_nested_json(MAX_REQUIREMENT_JSON_DEPTH))
    assert RequirementsParser.parse_file(exact) is None
    exact.write_bytes(_nested_json(2000))
    assert RequirementsParser.parse_file(exact) is None


def test_json_node_limit_exact_and_next_are_controlled(tmp_path):
    req_dir = _requirements_dir(tmp_path)
    target = req_dir / "US-NODES.json"
    # root(1), two root keys(2), story subtree(3), list(1), items(N)
    exact_items = MAX_REQUIREMENT_JSON_NODES - 7
    payload = {"story": {"id": "US-NODES"}, "extra": [0] * exact_items}
    target.write_text(json.dumps(payload), encoding="utf-8")
    assert RequirementsParser.parse_file(target) is not None

    payload["extra"].append(0)
    target.write_text(json.dumps(payload), encoding="utf-8")
    assert RequirementsParser.parse_file(target) is None


def test_json_depth_scanner_ignores_brackets_and_escapes_inside_strings(tmp_path):
    target = _write_json(tmp_path, "US-STR", title='literal [{]} \\" still text')
    assert RequirementsParser.parse_file(target) is not None


def test_complex_json_fails_closed_across_public_read_and_update_apis(tmp_path):
    target = _requirements_dir(tmp_path) / "US-COMPLEX.json"
    original = _nested_json(MAX_REQUIREMENT_JSON_DEPTH)
    target.write_bytes(original)

    assert RequirementsParser.parse_file(target) is None
    assert RequirementsParser.get_story_status(tmp_path, "US-COMPLEX") is None
    assert RequirementsParser.update_story_status(tmp_path, "US-COMPLEX", "DONE") is False
    assert target.read_bytes() == original
    assert not list(target.parent.glob(".*.tmp"))


def test_invalid_individual_json_rejects_collection_without_partial_results(tmp_path):
    _write_json(tmp_path, "US-GOOD")
    bad = _requirements_dir(tmp_path) / "US-BAD.json"
    bad.write_bytes(_nested_json(MAX_REQUIREMENT_JSON_DEPTH))

    result = RequirementsParser.load_collection(tmp_path)

    assert result.rejected is True
    assert result.specifications == ()
    assert [item.code for item in result.diagnostics] == [
        "REQUIREMENT_JSON_INVALID"
    ]


def test_requirement_renderers_are_bounded_deterministic_and_prioritize_headers(
    tmp_path, monkeypatch
):
    for index in range(40):
        _write_json(
            tmp_path,
            f"US-{index:03d}",
            title=f"Story {index} " + ("supporting narrative " * 80),
        )
    monkeypatch.setattr(renderer_module, "MAX_REQUIREMENTS_CONTEXT_CHARS", 1200)

    context_one = build_requirements_context(tmp_path)
    context_two = build_requirements_context(tmp_path)
    summary = build_requirements_summary(tmp_path)

    assert context_one == context_two
    assert context_one is not None
    assert len(context_one) <= 1200
    assert len(summary) <= 1200
    assert REQUIREMENTS_TRUNCATION_MARKER in context_one
    assert REQUIREMENTS_TRUNCATION_MARKER in summary
    assert context_one.index("US-001") < context_one.find("As a:") or "As a:" not in context_one


def test_context_dumper_full_and_focused_keep_bounded_closed_tags(
    tmp_path, monkeypatch
):
    _write_json(tmp_path, "US-HUGE", title="x" * 20_000)
    monkeypatch.setattr(renderer_module, "MAX_REQUIREMENTS_CONTEXT_CHARS", 700)
    dumper = ContextDumper(path=str(tmp_path), include_prd=False)

    for output in (
        dumper.build(),
        dumper.build_focused(include_requirements=True),
    ):
        start = output.index("<requirements_context>") + len("<requirements_context>")
        end = output.index("</requirements_context>")
        inner = output[start:end].strip("\n")
        assert len(inner) <= 700
        assert REQUIREMENTS_TRUNCATION_MARKER in inner
        assert output.count("<requirements_context>") == 1
        assert output.count("</requirements_context>") == 1


def test_mcp_summary_is_bounded_and_keeps_public_signature(tmp_path, monkeypatch):
    monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(tmp_path))
    _write_json(tmp_path, "US-HUGE", title="x" * 30_000)

    result = get_requirements_summary()

    assert len(result) <= MAX_REQUIREMENTS_CONTEXT_CHARS
    assert REQUIREMENTS_TRUNCATION_MARKER in result
    assert tuple(inspect.signature(get_requirements_summary).parameters) == (
        "project_path",
    )


def test_secret_near_budget_boundary_is_redacted_before_measurement(
    tmp_path, monkeypatch
):
    secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    source = _requirements_dir(tmp_path) / "US-SECRET.json"
    source.write_text(
        json.dumps(
            {
                "story": {
                    "id": "US-SECRET",
                    "title": f"Checkout {secret}",
                    "status": "TODO",
                    "role": "buyer",
                    "want": "safe " * 200,
                }
            }
        ),
        encoding="utf-8",
    )
    original = source.read_bytes()
    monkeypatch.setattr(renderer_module, "MAX_REQUIREMENTS_CONTEXT_CHARS", 500)

    outputs = (
        build_requirements_context(tmp_path),
        build_requirements_summary(tmp_path),
    )

    for output in outputs:
        assert output is not None
        assert secret not in output
        assert REDACTION_MARKER in output
        assert len(output) <= 500
    assert source.read_bytes() == original


def test_small_requirements_context_preserves_existing_format(tmp_path):
    _write_json(tmp_path, "US-001", title="Checkout")

    assert build_requirements_context(tmp_path) == (
        "<!-- User Stories & Acceptance Criteria -->\n"
        "US-001 [TODO] - Checkout"
    )
    assert build_requirements_summary(tmp_path) == (
        "# Requirements Summary\n\n"
        "**Total Stories**: 1 (TODO: 1, IN_PROGRESS: 0, TESTING: 0, DONE: 0, "
        "BLOCKED: 0, OTHER: 0)\n\n"
        "### US-001 [TODO] - Checkout"
    )


def test_empty_and_rejected_collections_are_distinct_and_neutral(tmp_path, monkeypatch):
    assert build_requirements_context(tmp_path) is None
    assert build_requirements_summary(tmp_path).startswith("No requirements found")

    rejected = RequirementsLoadResult(
        rejected=True, error_code="REQUIREMENTS_COLLECTION_LIMIT"
    )
    monkeypatch.setattr(
        RequirementsParser,
        "load_collection",
        classmethod(lambda _cls, _root: rejected),
    )
    context = build_requirements_context(tmp_path)
    summary = build_requirements_summary(tmp_path)
    assert context is not None and REQUIREMENTS_COLLECTION_REJECTED in context
    assert REQUIREMENTS_COLLECTION_REJECTED in summary
    assert str(tmp_path) not in context + summary


@pytest.mark.parametrize(
    "invalid_story",
    [None, 1, "story", []],
    ids=["null", "scalar", "string", "list"],
)
def test_malformed_json_story_shape_is_rejected(tmp_path, invalid_story):
    target = _requirements_dir(tmp_path) / "US-BAD.json"
    target.write_text(json.dumps({"story": invalid_story}), encoding="utf-8")

    assert RequirementsParser.parse_file(target) is None


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        (field, value)
        for field in (
            "business_rules",
            "acceptance_criteria",
            "required_data",
            "validations",
            "exceptions",
            "open_questions",
        )
        for value in (None, 1, "invalid", {})
    ],
)
def test_malformed_json_collection_field_shape_is_rejected(
    tmp_path, field, invalid_value
):
    target = _requirements_dir(tmp_path) / "US-BAD.json"
    target.write_text(
        json.dumps({"story": {"id": "US-BAD"}, field: invalid_value}),
        encoding="utf-8",
    )

    assert RequirementsParser.parse_file(target) is None


@pytest.mark.parametrize(
    ("field", "invalid_item"),
    [
        ("business_rules", 1),
        ("acceptance_criteria", None),
        ("required_data", "field"),
        ("validations", []),
        ("exceptions", 1),
        ("open_questions", {}),
    ],
)
def test_malformed_json_collection_item_shape_is_rejected(
    tmp_path, field, invalid_item
):
    target = _requirements_dir(tmp_path) / "US-BAD.json"
    target.write_text(
        json.dumps({"story": {"id": "US-BAD"}, field: [invalid_item]}),
        encoding="utf-8",
    )

    assert RequirementsParser.parse_file(target) is None


def test_malformed_json_fails_closed_across_public_apis_and_preserves_bytes(tmp_path):
    target = _requirements_dir(tmp_path) / "US-BAD.json"
    original = b'{"story":{"id":"US-BAD","status":"TODO"},"business_rules":1}\n'
    target.write_bytes(original)

    assert RequirementsParser.parse_file(target) is None
    assert RequirementsParser.get_story_status(tmp_path, "US-BAD") is None
    assert RequirementsParser.update_story_status(tmp_path, "US-BAD", "DONE") is False
    assert target.read_bytes() == original
    assert not list(target.parent.glob(".*.tmp"))


def test_mixed_collection_rejects_malformed_schema_without_partial_source(tmp_path):
    _write_json(tmp_path, "US-GOOD")
    malformed = _requirements_dir(tmp_path) / "US-BAD.json"
    malformed.write_text(
        json.dumps(
            {"story": {"id": "US-BAD"}, "acceptance_criteria": "invalid"}
        ),
        encoding="utf-8",
    )

    result = RequirementsParser.load_collection(tmp_path)

    assert result.rejected is True
    assert result.specifications == ()
    assert [item.code for item in result.diagnostics] == [
        "REQUIREMENT_SCHEMA_INVALID"
    ]


def test_every_repository_controlled_line_is_safely_truncated(tmp_path, monkeypatch):
    secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"

    def hostile(label):
        return (
            f"{label} Useful Unicode áéí 🚀 <scope> & details "
            + secret
            + " supporting-text" * 1_000
        )

    expected_labels = (
        "TITLE-LINE",
        "ROLE-LINE",
        "WANT-LINE",
        "BENEFIT-LINE",
        "BUSINESS-RULE-LINE",
        "ACCEPTANCE-LINE",
        "REQUIRED-DATA-LINE",
        "VALIDATION-LINE",
        "EXCEPTION-LINE",
        "OPEN-QUESTION-LINE",
    )
    source = _requirements_dir(tmp_path) / "US-LINES.json"
    source.write_text(
        json.dumps(
            {
                "story": {
                    "id": "US-LINES",
                    "title": hostile("TITLE-LINE"),
                    "status": "TODO",
                    "role": hostile("ROLE-LINE"),
                    "want": hostile("WANT-LINE"),
                    "benefit": hostile("BENEFIT-LINE"),
                },
                "business_rules": [
                    {"id": "BR-1", "description": hostile("BUSINESS-RULE-LINE")}
                ],
                "acceptance_criteria": [
                    {
                        "id": "AC-1",
                        "given": hostile("ACCEPTANCE-LINE"),
                        "when": "safe condition",
                        "then": "safe result",
                    }
                ],
                "required_data": [{"field": hostile("REQUIRED-DATA-LINE")}],
                "validations": [{"rule": hostile("VALIDATION-LINE")}],
                "exceptions": [{"condition": hostile("EXCEPTION-LINE")}],
                "open_questions": [hostile("OPEN-QUESTION-LINE")],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    original = source.read_bytes()
    monkeypatch.setattr(renderer_module, "MAX_REQUIREMENTS_CONTEXT_CHARS", 4_000)

    context_first = build_requirements_context(tmp_path)
    context_second = build_requirements_context(tmp_path)
    summary = build_requirements_summary(tmp_path)

    assert context_first == context_second
    assert context_first is not None
    for rendered in (context_first, summary):
        assert len(rendered) <= 4_000
        assert secret not in rendered
        assert REDACTION_MARKER in rendered
        assert "Useful Unicode áéí 🚀" in rendered
        assert "&lt;scope&gt; &amp; details" in rendered
        assert rendered.count("… [TRUNCATED]") >= len(expected_labels)
        assert REQUIREMENTS_TRUNCATION_MARKER in rendered
        assert not rendered.endswith(("&", "&a", "&am", "&amp", "&l", "&lt", "&g", "&gt"))
        for label in expected_labels:
            assert label in rendered
    ET.fromstring(f"<requirements_context>{context_first}</requirements_context>")
    assert source.read_bytes() == original


def test_fitting_project_with_long_line_preserves_exact_content(tmp_path):
    role = "architect-" * 40
    source = _requirements_dir(tmp_path) / "US-FITS.json"
    source.write_text(
        json.dumps(
            {
                "story": {
                    "id": "US-FITS",
                    "title": "Small project",
                    "status": "TODO",
                    "role": role,
                }
            }
        ),
        encoding="utf-8",
    )

    context = build_requirements_context(tmp_path)
    summary = build_requirements_summary(tmp_path)

    assert context is not None
    assert f"  As a: {role}" in context
    assert f"- **As a**: {role}" in summary
    assert "[TRUNCATED]" not in context + summary


@pytest.mark.parametrize(
    "raw_json",
    [
        b'{"story":{"id":"US-DUP"},"story":{"id":"US-OTHER"}}',
        b'{"story":{"id":"US-DUP","status":"TODO","status":"DONE"}}',
        b'{"story":{"id":"US-DUP"},"required_data":[{"field":"a","field":"b"}]}',
    ],
    ids=["root", "story", "nested-list"],
)
def test_exact_duplicate_json_keys_are_rejected_everywhere(tmp_path, raw_json):
    target = _requirements_dir(tmp_path) / "US-DUP.json"
    target.write_bytes(raw_json)
    original = target.read_bytes()

    assert RequirementsParser.parse_file(target) is None
    assert RequirementsParser.get_story_status(tmp_path, "US-DUP") is None
    assert RequirementsParser.update_story_status(tmp_path, "US-DUP", "DONE") is False
    assert target.read_bytes() == original
    assert not list(target.parent.glob(".*.tmp"))


def test_json_keys_that_differ_only_by_case_remain_distinct(tmp_path):
    target = _requirements_dir(tmp_path) / "US-CASE.json"
    target.write_bytes(
        b'{"story":{"id":"US-CASE","Status":"metadata","status":"TODO"}}'
    )

    spec = RequirementsParser.parse_file(target)

    assert spec is not None
    assert spec.story.status == "TODO"


def test_valid_and_duplicate_sources_reject_collection_and_all_context_consumers(
    tmp_path, monkeypatch
):
    _write_json(tmp_path, "US-GOOD", title="PARTIAL-NARRATIVE-MUST-NOT-APPEAR")
    duplicate = _requirements_dir(tmp_path) / "US-DUP.json"
    duplicate.write_bytes(
        b'{"story":{"id":"US-DUP","status":"TODO","status":"DONE"}}'
    )
    monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(tmp_path))

    result = RequirementsParser.load_collection(tmp_path)
    context = build_requirements_context(tmp_path)
    summary = build_requirements_summary(tmp_path)
    mcp_summary = get_requirements_summary()
    dumper_context = ContextDumper(
        path=str(tmp_path), include_prd=False
    ).get_requirements_context()

    assert result.rejected is True
    assert result.specifications == ()
    assert [item.code for item in result.diagnostics] == [
        "REQUIREMENT_JSON_DUPLICATE_KEY"
    ]
    for rendered in (context, summary, mcp_summary, dumper_context):
        assert rendered is not None
        assert "REQUIREMENT_JSON_DUPLICATE_KEY" in rendered
        assert "PARTIAL-NARRATIVE-MUST-NOT-APPEAR" not in rendered


def test_invalid_utf8_json_and_unsafe_source_have_neutral_diagnostics(
    tmp_path, monkeypatch
):
    req_dir = _requirements_dir(tmp_path)
    (req_dir / "invalid.json").write_bytes(b'{"story":')
    (req_dir / "utf8.json").write_bytes(b"\xff\xfe")
    secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    unsafe = req_dir / f"{secret}.md"
    unsafe.write_text("# US-UNSAFE [TODO] - secret content\n", encoding="utf-8")
    unsafe_size = unsafe.stat().st_size
    original = RequirementsParser._is_link_or_reparse
    monkeypatch.setattr(
        RequirementsParser,
        "_is_link_or_reparse",
        staticmethod(
            lambda value: (
                value.st_size == unsafe_size and value.st_ino == unsafe.stat().st_ino
            )
            or original(value)
        ),
    )

    result = RequirementsParser.load_collection(tmp_path)
    serialized = repr(result)

    assert result.rejected is True
    assert result.specifications == ()
    assert [item.code for item in result.diagnostics] == [
        "REQUIREMENT_SOURCE_UNSAFE",
        "REQUIREMENT_JSON_INVALID",
        "REQUIREMENT_SOURCE_INVALID_UTF8",
    ]
    assert secret not in serialized
    assert str(tmp_path) not in serialized
    assert "secret content" not in serialized


def test_total_directory_entry_limit_counts_unsupported_and_stops_early(
    tmp_path, monkeypatch
):
    req_dir = _requirements_dir(tmp_path)
    for index in range(5):
        (req_dir / f"ignored-{index}.txt").write_text("ignored", encoding="utf-8")
    real_scandir = parser_module.os.scandir
    entries = list(real_scandir(req_dir))
    consumed = {"count": 0}

    class BoundedIterator:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return self

        def __next__(self):
            consumed["count"] += 1
            if consumed["count"] > 3:
                raise AssertionError("enumerated beyond the first overflowing entry")
            return entries[consumed["count"] - 1]

    monkeypatch.setattr(parser_module, "MAX_REQUIREMENTS_DIRECTORY_ENTRIES", 2, raising=False)
    monkeypatch.setattr(parser_module.os, "scandir", lambda _path: BoundedIterator())

    result = RequirementsParser.load_collection(tmp_path)

    assert result.rejected is True
    assert result.specifications == ()
    assert result.error_code == "REQUIREMENTS_DIRECTORY_ENTRY_LIMIT"
    assert consumed["count"] == 3


def test_directory_entry_limit_exact_boundary_and_supported_limit_are_independent(
    tmp_path, monkeypatch
):
    req_dir = _requirements_dir(tmp_path)
    monkeypatch.setattr(parser_module, "MAX_REQUIREMENTS_DIRECTORY_ENTRIES", 3, raising=False)
    monkeypatch.setattr(parser_module, "MAX_REQUIREMENT_FILES", 1)
    (req_dir / "ignored-a.txt").write_text("ignored", encoding="utf-8")
    (req_dir / "ignored-b.txt").write_text("ignored", encoding="utf-8")
    (req_dir / "US-OK.json").write_bytes(_story_bytes("US-OK"))

    accepted = RequirementsParser.load_collection(tmp_path)
    assert accepted.rejected is False
    assert [item.story.id for item in accepted.specifications] == ["US-OK"]

    (req_dir / "ignored-over.txt").write_text("ignored", encoding="utf-8")
    rejected = RequirementsParser.load_collection(tmp_path)
    assert rejected.rejected is True
    assert rejected.error_code == "REQUIREMENTS_DIRECTORY_ENTRY_LIMIT"


def test_blocked_and_unknown_statuses_are_counted_in_summary(tmp_path):
    _write_json(tmp_path, "US-BLOCKED")
    _write_json(tmp_path, "US-UNKNOWN")
    blocked = _requirements_dir(tmp_path) / "US-BLOCKED.json"
    unknown = _requirements_dir(tmp_path) / "US-UNKNOWN.json"
    blocked.write_bytes(
        json.dumps({"story": {"id": "US-BLOCKED", "status": "BLOCKED"}}).encode()
    )
    unknown.write_bytes(
        json.dumps({"story": {"id": "US-UNKNOWN", "status": "CUSTOM"}}).encode()
    )

    summary = build_requirements_summary(tmp_path)

    assert "Total Stories**: 2" in summary
    assert "BLOCKED: 1" in summary
    assert "OTHER: 1" in summary


@pytest.mark.parametrize(
    ("budget", "exception_type"),
    [(-1, ValueError), (True, TypeError), (1.5, TypeError), ("10", TypeError)],
)
def test_requirements_renderer_rejects_invalid_budgets(tmp_path, budget, exception_type):
    with pytest.raises(exception_type):
        build_requirements_context(tmp_path, max_chars=budget)
    with pytest.raises(exception_type):
        build_requirements_summary(tmp_path, max_chars=budget)


def test_requirements_renderer_zero_and_positive_budgets(tmp_path):
    _write_json(tmp_path, "US-BUDGET")

    assert build_requirements_context(tmp_path, max_chars=0) == ""
    assert build_requirements_summary(tmp_path, max_chars=0) == ""
    assert len(build_requirements_context(tmp_path, max_chars=80)) <= 80
    assert len(build_requirements_summary(tmp_path, max_chars=80)) <= 80
