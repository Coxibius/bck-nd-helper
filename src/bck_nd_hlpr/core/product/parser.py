"""Safe Markdown/YAML parser and deterministic multi-PRD loader."""

import os
import math
import re
import stat
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

import yaml
from yaml.constructor import ConstructorError
from yaml.events import AliasEvent
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver

from .models import (
    DiagnosticSeverity,
    ProductCollectionResult,
    ProductDiagnostic,
    ProductDiagnosticCode,
    ProductParseResult,
    ProductRequirementDocument,
    ProductStatus,
)


SUPPORTED_SCHEMA_VERSION = 1
SUPPORTED_EXTENSIONS = frozenset({".md", ".markdown"})

CANONICAL_SECTIONS: Dict[str, str] = {
    "problem statement": "problem_statement",
    "target users": "target_users",
    "goals": "goals",
    "non-goals": "non_goals",
    "success metrics": "success_metrics",
    "scope": "scope",
    "risks": "risks",
    "rollout plan": "rollout_plan",
    "open questions": "open_questions",
}

KNOWN_METADATA = frozenset(
    {
        "schema_version",
        "id",
        "title",
        "status",
        "owner",
        "target_release",
        "applies_to",
        "requirement_ids",
    }
)


class _YamlAliasUnsupported(yaml.YAMLError):
    """Internal signal for YAML aliases, which PRD sources do not support."""

    def __init__(self, anchor: str) -> None:
        super().__init__(anchor)
        self.anchor = anchor


class _YamlDuplicateKey(yaml.YAMLError):
    """Internal signal for exact or normalized duplicate mapping keys."""

    def __init__(self, key: str, first_key: str, location: str) -> None:
        super().__init__(key, first_key, location)
        self.key = key
        self.first_key = first_key
        self.location = location


class ProductSourceReadError(Exception):
    """Safe internal failure raised by the shared descriptor-based reader."""

    def __init__(
        self,
        message: str,
        *,
        code: ProductDiagnosticCode = ProductDiagnosticCode.PARSE_ERROR,
        path_error: bool = False,
    ) -> None:
        super().__init__(message)
        self.safe_message = message
        self.code = code
        self.path_error = path_error


class _ProductSafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects aliases before object construction."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            event = self.peek_event()
            anchor = str(getattr(event, "anchor", "") or "<unknown>")
            raise _YamlAliasUnsupported(anchor)
        return super().compose_node(parent, index)


def canonical_metadata_key(value: Any) -> str:
    """Canonicalize YAML keys consistently for lookup and duplicate detection."""
    return str(value).strip().casefold().replace("-", "_").replace(" ", "_")


def _is_non_finite_number(value: Any) -> bool:
    return isinstance(value, float) and not math.isfinite(value)


def _construct_unique_mapping(
    loader: _ProductSafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> Dict[Any, Any]:
    """Construct a mapping only when every normalized key is unique."""
    if not isinstance(node, MappingNode):
        raise ConstructorError(
            None,
            None,
            f"expected a mapping node, but found {node.id}",
            node.start_mark,
        )

    loader.flatten_mapping(node)
    mapping: Dict[Any, Any] = {}
    normalized_keys: Dict[str, str] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            hash(key)
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from exc

        if _is_non_finite_number(key):
            key_text = "<non-finite-number>"
            normalized_key = f"<non-finite-number:{len(mapping)}>"
        else:
            key_text = str(key)
            normalized_key = canonical_metadata_key(key)
        first_key = normalized_keys.get(normalized_key)
        if first_key is not None:
            location = (
                f"line {key_node.start_mark.line + 1}, "
                f"column {key_node.start_mark.column + 1}"
            )
            raise _YamlDuplicateKey(key_text, first_key, location)

        normalized_keys[normalized_key] = key_text
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_ProductSafeLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _source_text(source_path: Union[str, Path, None]) -> str:
    return "" if source_path is None else str(source_path).replace("\\", "/")


def _diagnostic(
    message: str,
    source_path: Union[str, Path, None],
    *,
    code: ProductDiagnosticCode = ProductDiagnosticCode.PARSE_ERROR,
    field: Optional[str] = None,
    section: Optional[str] = None,
    reference: Optional[str] = None,
) -> ProductDiagnostic:
    return ProductDiagnostic(
        code=code,
        severity=DiagnosticSeverity.ERROR,
        message=message,
        source_path=_source_text(source_path),
        field=field,
        section=section,
        reference=reference,
    )


def _normalize_project_path(value: str) -> str:
    """Normalize separators and safe dot segments without hiding root escapes."""
    raw = value.strip().replace("\\", "/")
    if not raw or raw == ".":
        return raw or ""

    is_unc = raw.startswith("//")
    is_absolute = raw.startswith("/") and not is_unc
    parts: List[str] = []
    for part in raw.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            if parts and parts[-1] != ".." and not parts[-1].endswith(":"):
                parts.pop()
            else:
                parts.append(part)
            continue
        parts.append(part)

    normalized = "/".join(parts)
    if is_unc:
        return f"//{normalized}"
    if is_absolute:
        return f"/{normalized}"
    return normalized or "."


class ProductParser:
    """Parse local PRD sources without terminal, MCP, or requirements coupling."""

    @classmethod
    def parse_markdown(
        cls,
        content: str,
        source_path: Union[str, Path, None] = "",
    ) -> ProductParseResult:
        diagnostics: List[ProductDiagnostic] = []
        source = _source_text(source_path)

        if not isinstance(content, str):
            return ProductParseResult(
                diagnostics=[
                    _diagnostic("PRD content must be a Unicode string.", source)
                ]
            )

        text = content.lstrip("\ufeff")
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return ProductParseResult(
                diagnostics=[
                    _diagnostic(
                        "Missing YAML front matter opening delimiter ('---').",
                        source,
                        field="front_matter",
                    )
                ]
            )

        closing_index: Optional[int] = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                closing_index = index
                break
        if closing_index is None:
            return ProductParseResult(
                diagnostics=[
                    _diagnostic(
                        "YAML front matter is not closed with a second '---' delimiter.",
                        source,
                        field="front_matter",
                    )
                ]
            )

        yaml_text = "\n".join(lines[1:closing_index])
        try:
            loaded_metadata = yaml.load(yaml_text, Loader=_ProductSafeLoader)
        except _YamlAliasUnsupported as exc:
            return ProductParseResult(
                diagnostics=[
                    _diagnostic(
                        (
                            "YAML aliases are not supported in PRD front matter "
                            f"(alias '*{exc.anchor}')."
                        ),
                        source,
                        code=ProductDiagnosticCode.YAML_ALIAS_UNSUPPORTED,
                        field="front_matter",
                        reference=exc.anchor,
                    )
                ]
            )
        except _YamlDuplicateKey as exc:
            return ProductParseResult(
                diagnostics=[
                    _diagnostic(
                        (
                            f"Duplicate YAML key '{exc.key}' conflicts with "
                            f"'{exc.first_key}' at {exc.location}."
                        ),
                        source,
                        code=ProductDiagnosticCode.YAML_DUPLICATE_KEY,
                        field="front_matter",
                        reference=exc.key,
                    )
                ]
            )
        except RecursionError:
            return ProductParseResult(
                diagnostics=[
                    _diagnostic(
                        "YAML front matter exceeds the safe nesting depth.",
                        source,
                        field="front_matter",
                    )
                ]
            )
        except yaml.YAMLError as exc:
            return ProductParseResult(
                diagnostics=[
                    _diagnostic(
                        f"Invalid YAML front matter: {exc}",
                        source,
                        field="front_matter",
                    )
                ]
            )

        if not isinstance(loaded_metadata, Mapping):
            return ProductParseResult(
                diagnostics=[
                    _diagnostic(
                        "YAML front matter must contain an object/mapping.",
                        source,
                        field="front_matter",
                    )
                ]
            )

        metadata: Dict[str, Any] = {}
        extra_metadata: Dict[str, Any] = {}
        for original_key, value in loaded_metadata.items():
            if _is_non_finite_number(original_key):
                extra_metadata[original_key] = value
                continue
            normalized_key = canonical_metadata_key(original_key)
            if normalized_key in KNOWN_METADATA:
                metadata[normalized_key] = value
            else:
                extra_metadata[str(original_key)] = value

        body = "\n".join(lines[closing_index + 1 :])
        section_content, extra_sections, present_sections = cls._parse_sections(body)

        schema_version = cls._parse_schema_version(
            metadata.get("schema_version"),
            source,
            diagnostics,
        )
        status = cls._parse_status(metadata.get("status"), source, diagnostics)
        applies_to = cls._parse_string_list(
            metadata.get("applies_to"),
            "applies_to",
            source,
            diagnostics,
            normalize_paths=True,
        )
        requirement_ids = cls._parse_string_list(
            metadata.get("requirement_ids"),
            "requirement_ids",
            source,
            diagnostics,
        )

        document = ProductRequirementDocument(
            schema_version=schema_version,
            id=cls._parse_scalar(metadata.get("id"), "id", source, diagnostics),
            title=cls._parse_scalar(
                metadata.get("title"), "title", source, diagnostics
            ),
            status=status,
            owner=cls._parse_scalar(
                metadata.get("owner"), "owner", source, diagnostics
            ),
            target_release=cls._parse_scalar(
                metadata.get("target_release"),
                "target_release",
                source,
                diagnostics,
            ),
            applies_to=applies_to,
            requirement_ids=requirement_ids,
            problem_statement=section_content.get("problem_statement", ""),
            target_users=section_content.get("target_users", ""),
            goals=section_content.get("goals", ""),
            non_goals=section_content.get("non_goals", ""),
            success_metrics=section_content.get("success_metrics", ""),
            scope=section_content.get("scope", ""),
            risks=section_content.get("risks", ""),
            rollout_plan=section_content.get("rollout_plan", ""),
            open_questions=cls._parse_open_questions(
                section_content.get("open_questions", "")
            ),
            source_path=source,
            extra_metadata=extra_metadata,
            extra_sections=extra_sections,
            _present_metadata=sorted(metadata),
            _present_sections=present_sections,
            _section_markdown=dict(section_content),
        )
        return ProductParseResult(document=document, diagnostics=diagnostics)

    @classmethod
    def parse_file(
        cls,
        file_path: Union[str, Path],
        source_path: Union[str, Path, None] = None,
        *,
        product_directory: Optional[Union[str, Path]] = None,
        project_root: Optional[Union[str, Path]] = None,
    ) -> ProductParseResult:
        path = Path(file_path)
        source = _source_text(source_path if source_path is not None else path)

        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return ProductParseResult(
                diagnostics=[
                    _diagnostic(
                        f"Unsupported PRD source extension: {path.suffix or '<none>'}.",
                        source,
                        field="source_path",
                    )
                ]
            )

        expected_product_dir = Path(product_directory or path.parent)
        expected_project_root = Path(project_root or expected_product_dir)
        try:
            raw_content, _ = cls.read_verified_source(
                path,
                product_directory=expected_product_dir,
                project_root=expected_project_root,
            )
        except ProductSourceReadError as exc:
            return ProductParseResult(
                diagnostics=[
                    _diagnostic(
                        exc.safe_message,
                        source,
                        code=exc.code,
                        field="source_path",
                        reference=(
                            source
                            if exc.code
                            in {
                                ProductDiagnosticCode.SOURCE_SYMLINK,
                                ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT,
                            }
                            else None
                        ),
                    )
                ]
            )

        try:
            content = raw_content.decode("utf-8")
        except UnicodeDecodeError as exc:
            return ProductParseResult(
                diagnostics=[
                    _diagnostic(
                        f"PRD source is not valid UTF-8: {exc}",
                        source,
                        field="source_path",
                    )
                ]
            )
        return cls.parse_markdown(content, source_path=source)

    @classmethod
    def read_verified_source(
        cls,
        file_path: Union[str, Path],
        *,
        product_directory: Union[str, Path],
        project_root: Union[str, Path],
    ) -> Tuple[bytes, os.stat_result]:
        """Read one PRD through a verified descriptor and return stable bytes/stat."""
        path = Path(file_path)
        expected_product_dir = Path(product_directory)
        expected_project_root = Path(project_root)
        directory_stats: List[Tuple[Path, os.stat_result]] = []
        try:
            for component in cls._security_path_components(
                expected_project_root,
                expected_product_dir,
            ):
                component_stat = component.lstat()
                if cls._is_link_or_reparse(component_stat):
                    raise ProductSourceReadError(
                        "PRD source path uses a forbidden link or reparse point.",
                        code=ProductDiagnosticCode.SOURCE_SYMLINK,
                        path_error=True,
                    )
                if not stat.S_ISDIR(component_stat.st_mode):
                    raise ProductSourceReadError(
                        "PRD source directory changed during secure reading.",
                        code=ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT,
                        path_error=True,
                    )
                directory_stats.append((component, component_stat))
            path_stat = path.lstat()
        except ProductSourceReadError:
            raise
        except FileNotFoundError as exc:
            raise ProductSourceReadError(
                "PRD source file does not exist or is not a regular file."
            ) from exc
        except (OSError, RuntimeError) as exc:
            raise ProductSourceReadError(
                "Unable to inspect the PRD source safely.",
                code=ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT,
                path_error=True,
            ) from exc

        if cls._is_link_or_reparse(path_stat):
            raise ProductSourceReadError(
                "PRD source path uses a forbidden link or reparse point.",
                code=ProductDiagnosticCode.SOURCE_SYMLINK,
                path_error=True,
            )
        if not stat.S_ISREG(path_stat.st_mode):
            raise ProductSourceReadError(
                "PRD source file does not exist or is not a regular file."
            )

        try:
            resolved_root = expected_project_root.resolve(strict=True)
            resolved_product_dir = expected_product_dir.resolve(strict=True)
            resolved_path = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProductSourceReadError(
                "Unable to resolve the PRD source safely.",
                code=ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT,
                path_error=True,
            ) from exc

        if not cls._is_path_within(
            resolved_product_dir,
            resolved_root,
        ) or not cls._is_path_within(resolved_path, resolved_product_dir):
            raise ProductSourceReadError(
                "Resolved PRD source leaves the selected project root.",
                code=ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT,
                path_error=True,
            )

        guarded_paths = [component for component, _ in directory_stats] + [path]
        open_flags = os.O_RDONLY
        open_flags |= getattr(os, "O_BINARY", 0)
        open_flags |= getattr(os, "O_CLOEXEC", 0)
        open_flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(str(path), open_flags)
        except OSError as exc:
            raise ProductSourceReadError(
                "PRD source changed during secure reading.",
                code=(
                    ProductDiagnosticCode.SOURCE_SYMLINK
                    if cls._paths_use_link(guarded_paths)
                    else ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT
                ),
                path_error=True,
            ) from exc

        try:
            opened_stat = os.fstat(descriptor)
            if (
                cls._is_link_or_reparse(opened_stat)
                or not stat.S_ISREG(opened_stat.st_mode)
                or cls._descriptor_path_state(opened_stat)
                != cls._descriptor_path_state(path_stat)
            ):
                raise ProductSourceReadError(
                    "PRD source identity changed during secure reading.",
                    code=(
                        ProductDiagnosticCode.SOURCE_SYMLINK
                        if cls._paths_use_link(guarded_paths)
                        else ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT
                    ),
                    path_error=True,
                )

            chunks: List[bytes] = []
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            raw_content = b"".join(chunks)
            verified_descriptor_stat = os.fstat(descriptor)
            if (
                cls._file_state(verified_descriptor_stat)
                != cls._file_state(opened_stat)
                or cls._descriptor_path_state(verified_descriptor_stat)
                != cls._descriptor_path_state(path_stat)
            ):
                raise ProductSourceReadError(
                    "PRD source changed while its descriptor was being read.",
                    code=ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT,
                    path_error=True,
                )

            try:
                for component, expected_stat in directory_stats:
                    current_stat = component.lstat()
                    if (
                        cls._is_link_or_reparse(current_stat)
                        or not stat.S_ISDIR(current_stat.st_mode)
                        or cls._file_state(current_stat)
                        != cls._file_state(expected_stat)
                    ):
                        raise ProductSourceReadError(
                            "PRD source directory changed during secure reading.",
                            code=(
                                ProductDiagnosticCode.SOURCE_SYMLINK
                                if cls._is_link_or_reparse(current_stat)
                                else ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT
                            ),
                            path_error=True,
                        )

                current_path_stat = path.lstat()
                if (
                    cls._is_link_or_reparse(current_path_stat)
                    or cls._file_state(current_path_stat)
                    != cls._file_state(path_stat)
                ):
                    raise ProductSourceReadError(
                        "PRD source identity changed during secure reading.",
                        code=(
                            ProductDiagnosticCode.SOURCE_SYMLINK
                            if cls._is_link_or_reparse(current_path_stat)
                            else ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT
                        ),
                        path_error=True,
                    )

                verified_root = expected_project_root.resolve(strict=True)
                verified_product_dir = expected_product_dir.resolve(strict=True)
                verified_path = path.resolve(strict=True)
            except ProductSourceReadError:
                raise
            except (OSError, RuntimeError) as exc:
                raise ProductSourceReadError(
                    "PRD source changed during final path verification.",
                    code=(
                        ProductDiagnosticCode.SOURCE_SYMLINK
                        if cls._paths_use_link(guarded_paths)
                        else ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT
                    ),
                    path_error=True,
                ) from exc

            if (
                not cls._same_resolved_path(verified_root, resolved_root)
                or not cls._same_resolved_path(
                    verified_product_dir,
                    resolved_product_dir,
                )
                or not cls._same_resolved_path(verified_path, resolved_path)
                or not cls._is_path_within(verified_product_dir, verified_root)
                or not cls._is_path_within(verified_path, verified_product_dir)
            ):
                raise ProductSourceReadError(
                    "PRD source path changed during secure reading.",
                    code=ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT,
                    path_error=True,
                )
        except ProductSourceReadError:
            raise
        except OSError as exc:
            raise ProductSourceReadError(
                "Unable to read the PRD source safely.",
                code=ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT,
                path_error=True,
            ) from exc
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass

        return raw_content, current_path_stat

    @classmethod
    def load_from_directory(
        cls,
        project_path: Union[str, Path],
    ) -> ProductCollectionResult:
        product_dir, project_root = cls._resolve_product_directory(project_path)
        result = ProductCollectionResult(source_directory=product_dir)

        try:
            product_stat = None
            for component in cls._product_path_components(product_dir):
                component_stat = component.lstat()
                if cls._is_link_or_reparse(component_stat):
                    result.diagnostics.append(
                        cls._source_symlink_diagnostic(product_dir, component)
                    )
                    return result
                if component == product_dir:
                    product_stat = component_stat
        except FileNotFoundError:
            return result
        except (OSError, RuntimeError) as exc:
            result.diagnostics.append(
                cls._outside_root_diagnostic(
                    product_dir,
                    f"Unable to inspect the product directory safely: {exc}",
                    product_dir,
                )
            )
            return result

        if product_stat is None or not stat.S_ISDIR(product_stat.st_mode):
            result.diagnostics.append(
                _diagnostic(
                    "Product source path is not a directory.",
                    product_dir,
                    field="source_path",
                )
            )
            return result

        try:
            resolved_root = project_root.resolve(strict=True)
            resolved_product_dir = product_dir.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            result.diagnostics.append(
                cls._outside_root_diagnostic(
                    product_dir,
                    f"Unable to resolve the product directory safely: {exc}",
                    product_dir,
                )
            )
            return result

        if not cls._is_path_within(resolved_product_dir, resolved_root):
            result.diagnostics.append(
                cls._outside_root_diagnostic(
                    product_dir,
                    "Resolved product directory leaves the selected project root.",
                    product_dir,
                )
            )
            return result

        try:
            files = sorted(
                (
                    item
                    for item in product_dir.iterdir()
                    if item.suffix.lower() in SUPPORTED_EXTENSIONS
                ),
                key=lambda item: (item.name.casefold(), item.name),
            )
        except OSError as exc:
            result.diagnostics.append(
                _diagnostic(
                    f"Unable to list product directory: {exc}",
                    product_dir,
                    field="source_path",
                )
            )
            return result

        seen_ids: Dict[str, ProductRequirementDocument] = {}
        for file_path in files:
            source = cls._relative_source(file_path, project_root, product_dir)
            parsed = cls.parse_file(
                file_path,
                source_path=source,
                product_directory=product_dir,
                project_root=project_root,
            )
            result.diagnostics.extend(parsed.diagnostics)
            if parsed.document is None:
                continue

            document = parsed.document
            result.documents.append(document)
            normalized_id = document.id.strip().casefold()
            if not normalized_id:
                continue
            first = seen_ids.get(normalized_id)
            if first is None:
                seen_ids[normalized_id] = document
                continue
            result.diagnostics.append(
                ProductDiagnostic(
                    code=ProductDiagnosticCode.ID_DUPLICATE,
                    severity=DiagnosticSeverity.ERROR,
                    message=(
                        f"Duplicate PRD ID '{document.id}' conflicts with "
                        f"'{first.source_path}'."
                    ),
                    source_path=document.source_path,
                    field="id",
                    reference=first.source_path,
                )
            )

        return result

    @staticmethod
    def _resolve_product_directory(
        project_path: Union[str, Path],
    ) -> Tuple[Path, Path]:
        base = Path(project_path)
        if base.name.casefold() == "product":
            if base.parent.name == ".bck-nd":
                return base, base.parent.parent
            return base, base
        return base / ".bck-nd" / "product", base

    @staticmethod
    def _product_path_components(product_dir: Path) -> List[Path]:
        components = [product_dir]
        if product_dir.parent.name.casefold() == ".bck-nd":
            components.insert(0, product_dir.parent)
        return components

    @classmethod
    def _security_path_components(
        cls,
        project_root: Path,
        product_dir: Path,
    ) -> List[Path]:
        """Return unique directories whose identities guard one PRD read."""
        components = [project_root] + cls._product_path_components(product_dir)
        unique: List[Path] = []
        seen = set()
        for component in components:
            identity = os.path.normcase(os.path.abspath(str(component)))
            if identity not in seen:
                unique.append(component)
                seen.add(identity)
        return unique

    @staticmethod
    def _is_link_or_reparse(path_stat: os.stat_result) -> bool:
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        file_attributes = getattr(path_stat, "st_file_attributes", 0)
        return stat.S_ISLNK(path_stat.st_mode) or bool(
            file_attributes & reparse_flag
        )

    @staticmethod
    def _is_path_within(candidate: Path, directory: Path) -> bool:
        """Return containment without relying on Path.is_relative_to (Python 3.9)."""
        try:
            candidate_text = os.path.normcase(os.path.abspath(str(candidate)))
            directory_text = os.path.normcase(os.path.abspath(str(directory)))
            return os.path.commonpath(
                [directory_text, candidate_text]
            ) == directory_text
        except (OSError, ValueError):
            return False

    @staticmethod
    def _stat_identity(path_stat: os.stat_result) -> Tuple[int, int, int]:
        return (
            path_stat.st_dev,
            path_stat.st_ino,
            stat.S_IFMT(path_stat.st_mode),
        )

    @classmethod
    def _file_state(cls, path_stat: os.stat_result) -> Tuple[int, int, int, int, int, int]:
        return (
            *cls._stat_identity(path_stat),
            path_stat.st_size,
            path_stat.st_mtime_ns,
            path_stat.st_ctime_ns,
        )

    @classmethod
    def _descriptor_path_state(
        cls,
        path_stat: os.stat_result,
    ) -> Tuple[int, int, int, int, int]:
        """Compare fields stable between lstat() and fstat() on all platforms."""
        return (
            *cls._stat_identity(path_stat),
            path_stat.st_size,
            path_stat.st_mtime_ns,
        )

    @staticmethod
    def _same_resolved_path(first: Path, second: Path) -> bool:
        return os.path.normcase(os.path.abspath(str(first))) == os.path.normcase(
            os.path.abspath(str(second))
        )

    @classmethod
    def _paths_use_link(cls, paths: List[Path]) -> bool:
        for candidate in paths:
            try:
                if cls._is_link_or_reparse(candidate.lstat()):
                    return True
            except OSError:
                continue
        return False

    @staticmethod
    def _source_race_diagnostic(
        source_path: Union[str, Path],
        *,
        symlink: bool = False,
    ) -> ProductDiagnostic:
        if symlink:
            return _diagnostic(
                "PRD source changed to a forbidden link during secure reading.",
                source_path,
                code=ProductDiagnosticCode.SOURCE_SYMLINK,
                field="source_path",
                reference=_source_text(source_path),
            )
        return _diagnostic(
            "PRD source identity changed during secure reading; content was discarded.",
            source_path,
            code=ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT,
            field="source_path",
            reference=_source_text(source_path),
        )

    @staticmethod
    def _source_symlink_diagnostic(
        source_path: Union[str, Path],
        unsafe_path: Path,
    ) -> ProductDiagnostic:
        return _diagnostic(
            "PRD sources may not use symbolic links, junctions, or reparse points.",
            source_path,
            code=ProductDiagnosticCode.SOURCE_SYMLINK,
            field="source_path",
            reference=_source_text(unsafe_path),
        )

    @staticmethod
    def _outside_root_diagnostic(
        source_path: Union[str, Path],
        message: str,
        unsafe_path: Path,
    ) -> ProductDiagnostic:
        return _diagnostic(
            message,
            source_path,
            code=ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT,
            field="source_path",
            reference=_source_text(unsafe_path),
        )

    @staticmethod
    def _relative_source(file_path: Path, project_root: Path, product_dir: Path) -> str:
        try:
            return file_path.relative_to(project_root).as_posix()
        except ValueError:
            try:
                return file_path.relative_to(product_dir).as_posix()
            except ValueError:
                return file_path.as_posix()

    @staticmethod
    def _parse_schema_version(
        value: Any,
        source: str,
        diagnostics: List[ProductDiagnostic],
    ) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):
            diagnostics.append(
                _diagnostic(
                    "schema_version must be an integer.",
                    source,
                    field="schema_version",
                )
            )
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        diagnostics.append(
            _diagnostic(
                "schema_version must be an integer.",
                source,
                field="schema_version",
            )
        )
        return None

    @staticmethod
    def _parse_status(
        value: Any,
        source: str,
        diagnostics: List[ProductDiagnostic],
    ) -> Union[ProductStatus, str, None]:
        if value is None:
            return None
        if _is_non_finite_number(value):
            diagnostics.append(
                _diagnostic(
                    "status must not contain a non-finite number.",
                    source,
                    field="status",
                )
            )
            return None
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            diagnostics.append(
                _diagnostic("status must be a scalar value.", source, field="status")
            )
            return None
        normalized = str(value).strip().upper()
        try:
            return ProductStatus(normalized)
        except ValueError:
            return normalized

    @staticmethod
    def _parse_scalar(
        value: Any,
        field_name: str,
        source: str,
        diagnostics: List[ProductDiagnostic],
    ) -> str:
        if value is None:
            return ""
        if _is_non_finite_number(value):
            diagnostics.append(
                _diagnostic(
                    f"{field_name} must not contain a non-finite number.",
                    source,
                    field=field_name,
                )
            )
            return ""
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            return str(value).strip()
        diagnostics.append(
            _diagnostic(
                f"{field_name} must be a scalar value.",
                source,
                field=field_name,
            )
        )
        return ""

    @staticmethod
    def _parse_string_list(
        value: Any,
        field_name: str,
        source: str,
        diagnostics: List[ProductDiagnostic],
        *,
        normalize_paths: bool = False,
    ) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            raw_items = value
        elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
            raw_items = [value]
            diagnostics.append(
                _diagnostic(
                    f"{field_name} should be a YAML list; preserved its scalar value.",
                    source,
                    field=field_name,
                )
            )
        else:
            diagnostics.append(
                _diagnostic(
                    f"{field_name} must be a YAML list of scalar values.",
                    source,
                    field=field_name,
                )
            )
            return []

        parsed: List[str] = []
        for item in raw_items:
            if _is_non_finite_number(item):
                diagnostics.append(
                    _diagnostic(
                        f"{field_name} contains a non-finite number.",
                        source,
                        field=field_name,
                    )
                )
                continue
            if not isinstance(item, (str, int, float)) or isinstance(item, bool):
                diagnostics.append(
                    _diagnostic(
                        f"{field_name} contains a non-scalar value.",
                        source,
                        field=field_name,
                    )
                )
                continue
            normalized = str(item).strip()
            if normalize_paths:
                normalized = _normalize_project_path(normalized)
            if normalized:
                parsed.append(normalized)
        return parsed

    @staticmethod
    def _parse_sections(body: str) -> Tuple[Dict[str, str], Dict[str, str], List[str]]:
        canonical_lines: Dict[str, List[str]] = {}
        extra_lines: Dict[str, List[str]] = {}
        extra_names: Dict[str, str] = {}
        present_sections: List[str] = []
        current_kind: Optional[str] = None
        current_name: Optional[str] = None
        preamble: List[str] = []
        in_fence = False
        fence_marker = ""

        for line in body.splitlines():
            stripped = line.lstrip()
            fence_match = re.match(r"^(```+|~~~+)", stripped)
            if fence_match:
                marker = fence_match.group(1)[0]
                if not in_fence:
                    in_fence = True
                    fence_marker = marker
                elif marker == fence_marker:
                    in_fence = False

            heading_match = None
            if not in_fence:
                heading_match = re.match(r"^\s*##(?!#)\s+(.+?)\s*$", line)
            if heading_match:
                heading = re.sub(r"\s+#+\s*$", "", heading_match.group(1)).strip()
                normalized_heading = re.sub(r"\s+", " ", heading.casefold())
                canonical_name = CANONICAL_SECTIONS.get(normalized_heading)
                if canonical_name is not None:
                    current_kind = "canonical"
                    current_name = canonical_name
                    canonical_lines.setdefault(canonical_name, [])
                    if canonical_name not in present_sections:
                        present_sections.append(canonical_name)
                else:
                    folded = normalized_heading
                    stored_name = extra_names.setdefault(folded, heading)
                    current_kind = "extra"
                    current_name = stored_name
                    extra_lines.setdefault(stored_name, [])
                continue

            if current_kind == "canonical" and current_name is not None:
                canonical_lines[current_name].append(line)
            elif current_kind == "extra" and current_name is not None:
                extra_lines[current_name].append(line)
            else:
                preamble.append(line)

        canonical = {
            name: "\n".join(lines).strip()
            for name, lines in canonical_lines.items()
        }
        extras = {
            name: "\n".join(lines).strip()
            for name, lines in extra_lines.items()
        }
        preamble_text = "\n".join(preamble).strip()
        if preamble_text:
            extras = {"Preamble": preamble_text, **extras}
        return canonical, extras, present_sections

    @staticmethod
    def _parse_open_questions(markdown: str) -> List[str]:
        questions: List[str] = []
        explicit_empty = {"none", "n/a", "na", "no open questions"}
        for line in markdown.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("###"):
                continue
            cleaned = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", stripped)
            cleaned = re.sub(r"^\[[ xX]\]\s*", "", cleaned).strip()
            empty_candidate = cleaned.casefold().rstrip(".!")
            if empty_candidate in explicit_empty:
                continue
            if cleaned:
                questions.append(cleaned)
        return questions
