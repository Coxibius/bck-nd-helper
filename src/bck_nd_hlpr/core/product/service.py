"""Reusable application service for the local PRD workflow."""

from __future__ import annotations

import os
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Iterable, List, Optional, Sequence, Tuple, Union

import yaml
from yaml.nodes import MappingNode, ScalarNode

from bck_nd_hlpr.core.requirements import RequirementsParser

from .models import (
    DiagnosticSeverity,
    ProductCollectionResult,
    ProductDiagnostic,
    ProductDiagnosticCode,
    ProductRequirementDocument,
    ProductStatus,
)
from .parser import ProductParser, ProductSourceReadError, canonical_metadata_key
from .templates import render_product_template
from .validator import VALID_PRODUCT_ID, ProductValidator, classify_product_path


DEFAULT_PRODUCT_ID = "PRD"
PRODUCT_SCHEMA_VERSION = 1
_UTF8_BOM = b"\xef\xbb\xbf"
_SECURITY_CODES = {
    ProductDiagnosticCode.SOURCE_SYMLINK,
    ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT,
}


def _sanitize_declared_path(value: Union[str, Path]) -> str:
    """Expose only project-relative path declarations in serialized documents."""
    normalized, has_external_syntax, has_traversal = classify_product_path(value)
    if has_external_syntax or has_traversal:
        return "<outside-project>"
    return normalized


def _expose_path(
    value: Union[str, Path, None],
    project_root: Optional[Path],
) -> str:
    """Expose a safe relative path or a stable outside-project sentinel."""
    if value is None:
        return ""
    normalized, has_external_syntax, has_traversal = classify_product_path(value)
    if has_traversal:
        return "<outside-project>"
    if not has_external_syntax:
        return normalized

    native_path = Path(value)
    if project_root is not None and native_path.is_absolute():
        try:
            resolved = native_path.resolve(strict=False)
            if ProductParser._is_path_within(resolved, project_root):
                return resolved.relative_to(project_root).as_posix()
        except (OSError, RuntimeError, ValueError):
            pass
    return "<outside-project>"


class ProductServiceError(Exception):
    """Base class for controlled PRD workflow failures."""

    def __init__(
        self,
        message: str,
        diagnostics: Optional[Iterable[ProductDiagnostic]] = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = list(diagnostics or [])


class ProductInvalidIdError(ProductServiceError):
    """The supplied product identifier is unsafe or malformed."""


class ProductInvalidStatusError(ProductServiceError):
    """The requested lifecycle status is unsupported."""


class ProductNotFoundError(ProductServiceError):
    """No safely parsed PRD matches the requested identifier."""


class ProductCollisionError(ProductServiceError):
    """A filename or parsed PRD identifier is ambiguous or already exists."""


class ProductPathError(ProductServiceError):
    """A product storage path cannot be used safely."""


class ProductReadError(ProductServiceError):
    """A PRD source could not be read or parsed safely."""


class ProductWriteError(ProductServiceError):
    """A PRD source could not be written atomically."""


class ProductValidationError(ProductServiceError):
    """Candidate PRD data failed domain validation."""


class ProductTransitionBlockedError(ProductValidationError):
    """A lifecycle transition was rejected by domain validation."""


@dataclass
class ProductCreateResult:
    """Successful creation of one canonical PRD source."""

    document: ProductRequirementDocument
    path: Path


@dataclass
class ProductStatusUpdateResult:
    """Result of a lifecycle update, including no-op transitions."""

    document: ProductRequirementDocument
    path: Path
    previous_status: str
    new_status: str
    changed: bool
    diagnostics: List[ProductDiagnostic] = field(default_factory=list)


@dataclass
class ProductValidationReport:
    """Stable validation view shared by human and JSON adapters."""

    documents: List[ProductRequirementDocument] = field(default_factory=list)
    diagnostics: List[ProductDiagnostic] = field(default_factory=list)
    project_root: Optional[Path] = field(default=None, repr=False)

    @property
    def valid(self) -> bool:
        return self.error_count == 0

    @property
    def error_count(self) -> int:
        return self._severity_count(DiagnosticSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return self._severity_count(DiagnosticSeverity.WARNING)

    @property
    def info_count(self) -> int:
        return self._severity_count(DiagnosticSeverity.INFO)

    def _severity_count(self, severity: DiagnosticSeverity) -> int:
        return sum(item.severity is severity for item in self.diagnostics)

    def to_dict(self) -> dict:
        serialized_documents = []
        for document in self.documents:
            serialized = document.to_dict()
            serialized["source_path"] = _expose_path(
                document.source_path,
                self.project_root,
            )
            serialized["applies_to"] = [
                _sanitize_declared_path(path) for path in document.applies_to
            ]
            serialized_documents.append(serialized)
        return {
            "schema_version": PRODUCT_SCHEMA_VERSION,
            "valid": self.valid,
            "summary": {
                "documents": len(self.documents),
                "errors": self.error_count,
                "warnings": self.warning_count,
                "info": self.info_count,
            },
            "documents": serialized_documents,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


class ProductService:
    """Coordinate PRD persistence, validation, requirements, and lifecycle rules."""

    def __init__(self, project_path: Union[str, Path] = ".") -> None:
        self.project_root = self._resolve_project_root(project_path)

    def create_document(self, product_id: Optional[str] = None) -> ProductCreateResult:
        """Create one canonical Markdown PRD without overwriting existing data."""
        normalized_id = self.normalize_product_id(product_id or DEFAULT_PRODUCT_ID)
        product_dir = self._product_directory(create=True)
        target = product_dir / f"{normalized_id}.md"

        self._reject_filename_collision(product_dir, target.name)
        collection = self.load_documents()
        if any(
            document.id.strip().casefold() == normalized_id.casefold()
            for document in collection.documents
        ):
            raise ProductCollisionError(
                f"A PRD with ID '{normalized_id}' already exists."
            )

        content = render_product_template(normalized_id)
        source_path = f".bck-nd/product/{target.name}"
        parsed = ProductParser.parse_markdown(content, source_path=source_path)
        if parsed.document is None or parsed.diagnostics:
            raise ProductValidationError(
                "The canonical PRD template did not pass parsing.",
                parsed.diagnostics,
            )

        self._atomic_create(target, content.encode("utf-8"))
        return ProductCreateResult(document=parsed.document, path=target)

    def load_documents(self) -> ProductCollectionResult:
        """Load the deterministic, security-hardened product collection."""
        return ProductParser.load_from_directory(self.project_root)

    def validate_documents(
        self,
        product_id: Optional[str] = None,
        *,
        collection: Optional[ProductCollectionResult] = None,
    ) -> ProductValidationReport:
        """Validate all PRDs or one case-insensitively selected document."""
        loaded = collection if collection is not None else self.load_documents()
        requirement_ids = self._available_requirement_ids()

        if product_id is None:
            documents = list(loaded.documents)
            diagnostics = ProductValidator.validate_collection(
                loaded,
                project_root=self.project_root,
                available_requirement_ids=requirement_ids,
            )
        else:
            document = self.get_document(product_id, collection=loaded)
            documents = [document]
            diagnostics = [
                item
                for item in loaded.diagnostics
                if item.source_path == document.source_path
            ]
            diagnostics.extend(
                ProductValidator.validate_document(
                    document,
                    project_root=self.project_root,
                    available_requirement_ids=requirement_ids,
                )
            )

        return ProductValidationReport(
            documents=documents,
            diagnostics=self._safe_diagnostics(diagnostics),
            project_root=self.project_root,
        )

    def get_document(
        self,
        product_id: str,
        *,
        collection: Optional[ProductCollectionResult] = None,
    ) -> ProductRequirementDocument:
        """Find exactly one safely parsed PRD by its internal identifier."""
        normalized_id = self.normalize_product_id(product_id)
        loaded = collection if collection is not None else self.load_documents()
        matches = [
            document
            for document in loaded.documents
            if document.id.strip().casefold() == normalized_id.casefold()
        ]
        if len(matches) > 1:
            raise ProductCollisionError(
                f"PRD ID '{normalized_id}' is ambiguous.",
                self._safe_diagnostics(loaded.diagnostics),
            )
        if matches:
            return matches[0]

        matching_source_diagnostics = [
            item
            for item in loaded.diagnostics
            if Path(item.source_path).stem.casefold() == normalized_id.casefold()
        ]
        security_diagnostics = [
            item
            for item in loaded.diagnostics
            if item.code in _SECURITY_CODES
        ]
        if matching_source_diagnostics or (
            security_diagnostics and not loaded.documents
        ):
            relevant = matching_source_diagnostics or security_diagnostics
            if any(item.code in _SECURITY_CODES for item in relevant):
                raise ProductPathError(
                    f"PRD '{normalized_id}' has an unsafe source path.",
                    self._safe_diagnostics(relevant),
                )
            raise ProductReadError(
                f"PRD '{normalized_id}' could not be parsed safely.",
                self._safe_diagnostics(relevant),
            )
        raise ProductNotFoundError(f"PRD not found: {normalized_id}")

    def update_status(
        self,
        product_id: str,
        new_status: Union[str, ProductStatus],
    ) -> ProductStatusUpdateResult:
        """Apply one validated lifecycle transition with a minimal atomic edit."""
        normalized_id = self.normalize_product_id(product_id)
        normalized_status = self.normalize_status(new_status)
        collection = self.load_documents()
        document = self.get_document(normalized_id, collection=collection)
        target, raw_content, original_stat = self._read_document_source(document)
        bom, text = self._decode_source(raw_content)

        current = ProductParser.parse_markdown(text, source_path=document.source_path)
        if current.document is None or current.diagnostics:
            raise ProductReadError(
                f"PRD '{normalized_id}' is not safe to update.",
                self._safe_diagnostics(current.diagnostics),
            )
        if current.document.id.strip().casefold() != normalized_id.casefold():
            raise ProductCollisionError(
                f"PRD '{normalized_id}' changed identity while being updated."
            )

        previous_status = current.document.status_value
        if previous_status == normalized_status:
            return ProductStatusUpdateResult(
                document=current.document,
                path=target,
                previous_status=previous_status,
                new_status=normalized_status,
                changed=False,
            )

        candidate_text = self._replace_front_matter_status(text, normalized_status)
        candidate = ProductParser.parse_markdown(
            candidate_text,
            source_path=document.source_path,
        )
        if candidate.document is None or candidate.diagnostics:
            raise ProductReadError(
                f"PRD '{normalized_id}' cannot be updated without repairing YAML.",
                self._safe_diagnostics(candidate.diagnostics),
            )

        diagnostics = ProductValidator.validate_document(
            candidate.document,
            project_root=self.project_root,
            available_requirement_ids=self._available_requirement_ids(),
        )
        safe_diagnostics = self._safe_diagnostics(diagnostics)
        blocking = [
            item
            for item in safe_diagnostics
            if item.severity is DiagnosticSeverity.ERROR
        ]
        blocking_statuses = {
            ProductStatus.REVIEW.value,
            ProductStatus.APPROVED.value,
            ProductStatus.SHIPPED.value,
        }
        if normalized_status in blocking_statuses and blocking:
            raise ProductTransitionBlockedError(
                (
                    f"Transition to {normalized_status} is blocked by "
                    f"{len(blocking)} validation error(s)."
                ),
                safe_diagnostics,
            )

        updated_bytes = bom + candidate_text.encode("utf-8")
        self._atomic_replace(
            target,
            updated_bytes,
            original_stat,
            raw_content,
        )
        return ProductStatusUpdateResult(
            document=candidate.document,
            path=target,
            previous_status=previous_status,
            new_status=normalized_status,
            changed=True,
            diagnostics=safe_diagnostics,
        )

    @staticmethod
    def normalize_product_id(product_id: str) -> str:
        normalized = str(product_id).strip().upper()
        if not normalized or VALID_PRODUCT_ID.fullmatch(normalized) is None:
            raise ProductInvalidIdError(
                "PRD_ID may contain only letters, numbers, hyphens, and underscores."
            )
        return normalized

    @staticmethod
    def normalize_status(status_value: Union[str, ProductStatus]) -> str:
        value = status_value.value if isinstance(status_value, ProductStatus) else status_value
        normalized = str(value).strip().upper()
        accepted = {status.value for status in ProductStatus}
        if normalized not in accepted:
            raise ProductInvalidStatusError(
                "STATUS must be DRAFT, REVIEW, APPROVED, SHIPPED, or ARCHIVED."
            )
        return normalized

    @staticmethod
    def _resolve_project_root(project_path: Union[str, Path]) -> Path:
        candidate = Path(project_path)
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProductPathError("Project path does not exist or is unsafe.") from exc
        if not resolved.is_dir():
            raise ProductPathError("Project path is not a directory.")
        if (
            resolved.name.casefold() == "product"
            and resolved.parent.name.casefold() == ".bck-nd"
        ):
            return resolved.parent.parent
        return resolved

    def _product_directory(self, *, create: bool) -> Path:
        metadata_dir = self.project_root / ".bck-nd"
        product_dir = metadata_dir / "product"
        if not ProductParser._is_path_within(product_dir, self.project_root):
            raise ProductPathError("Product directory leaves the selected project root.")

        for directory in (metadata_dir, product_dir):
            try:
                directory_stat = directory.lstat()
            except FileNotFoundError:
                if not create:
                    raise ProductPathError("Product directory does not exist.")
                try:
                    directory.mkdir()
                    directory_stat = directory.lstat()
                except (FileExistsError, OSError) as exc:
                    raise ProductPathError(
                        "Product directory could not be created safely."
                    ) from exc
            except (OSError, RuntimeError) as exc:
                raise ProductPathError(
                    "Product directory could not be inspected safely."
                ) from exc

            if ProductParser._is_link_or_reparse(directory_stat):
                raise ProductPathError(
                    "Product storage may not use symlinks, junctions, or reparse points."
                )
            if not stat.S_ISDIR(directory_stat.st_mode):
                raise ProductPathError("Product storage path is not a directory.")

        try:
            resolved_product = product_dir.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProductPathError(
                "Product directory could not be resolved safely."
            ) from exc
        if not ProductParser._is_path_within(resolved_product, self.project_root):
            raise ProductPathError("Product directory leaves the selected project root.")
        return product_dir

    def _reject_filename_collision(self, product_dir: Path, filename: str) -> None:
        try:
            for entry in product_dir.iterdir():
                if entry.name.casefold() == filename.casefold():
                    raise ProductCollisionError(
                        f"PRD source already exists: .bck-nd/product/{entry.name}"
                    )
        except ProductCollisionError:
            raise
        except OSError as exc:
            raise ProductReadError("Unable to inspect existing PRD sources.") from exc

    def _available_requirement_ids(self) -> List[str]:
        specifications = RequirementsParser.load_from_directory(self.project_root)
        return sorted(
            {
                str(specification.story.id).strip()
                for specification in specifications
                if specification.story is not None
                and str(specification.story.id).strip()
            },
            key=lambda item: (item.casefold(), item),
        )

    def _safe_diagnostics(
        self,
        diagnostics: Iterable[ProductDiagnostic],
    ) -> List[ProductDiagnostic]:
        safe: List[ProductDiagnostic] = []
        seen = set()
        for item in diagnostics:
            source_path = self._exposed_path(item.source_path)
            reference = self._exposed_reference(item.reference)
            message = self._safe_message(item, source_path, reference)
            copied = ProductDiagnostic(
                code=item.code,
                severity=item.severity,
                message=message,
                source_path=source_path,
                field=item.field,
                section=item.section,
                reference=reference,
            )
            key = (
                copied.code.value
                if isinstance(copied.code, ProductDiagnosticCode)
                else copied.code,
                copied.severity.value,
                copied.source_path,
                copied.field,
                copied.section,
                copied.reference,
                copied.message,
            )
            if key not in seen:
                safe.append(copied)
                seen.add(key)
        return sorted(
            safe,
            key=lambda item: (
                item.source_path.casefold(),
                str(item.code.value if isinstance(item.code, ProductDiagnosticCode) else item.code),
                item.field or "",
                item.section or "",
                item.reference or "",
                item.message,
            ),
        )

    def _exposed_path(self, value: Union[str, Path, None]) -> str:
        return _expose_path(value, self.project_root)

    def _exposed_reference(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _expose_path(value, self.project_root)

    def _safe_message(
        self,
        diagnostic: ProductDiagnostic,
        exposed_source_path: str,
        exposed_reference: Optional[str],
    ) -> str:
        if diagnostic.code == ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT:
            return "PRD source could not be resolved safely inside the project root."
        if diagnostic.code == ProductDiagnosticCode.SOURCE_SYMLINK:
            return "PRD source uses a forbidden symlink, junction, or reparse point."
        message = diagnostic.message
        original_source = str(diagnostic.source_path)
        normalized_source = original_source.replace("\\", "/")
        if original_source and exposed_source_path != normalized_source:
            source_variants = {
                original_source,
                normalized_source,
                normalized_source.replace("/", "\\"),
            }
            for source_variant in sorted(
                source_variants,
                key=lambda item: (-len(item), item),
            ):
                message = message.replace(source_variant, exposed_source_path)
        if (
            diagnostic.reference
            and exposed_reference != str(diagnostic.reference).replace("\\", "/")
        ):
            original_reference = str(diagnostic.reference)
            reference_variants = {
                original_reference,
                original_reference.replace("\\", "/"),
                original_reference.replace("\\", "/").replace("/", "\\"),
            }
            for reference_variant in sorted(
                reference_variants,
                key=lambda item: (-len(item), item),
            ):
                message = message.replace(
                    reference_variant,
                    exposed_reference or "",
                )
        root_values = {str(self.project_root), self.project_root.as_posix()}
        for root_value in sorted(root_values, key=len, reverse=True):
            message = message.replace(root_value, ".")
        return message

    def _read_document_source(
        self,
        document: ProductRequirementDocument,
    ) -> Tuple[Path, bytes, os.stat_result]:
        product_dir = self._product_directory(create=False)
        source = str(document.source_path).replace("\\", "/")
        source_path = PurePosixPath(source)
        if source_path.is_absolute() or ".." in source_path.parts:
            raise ProductPathError("PRD source path is unsafe.")
        expected_prefix = (".bck-nd", "product")
        if tuple(source_path.parts[:2]) != expected_prefix or len(source_path.parts) != 3:
            raise ProductPathError("PRD source is outside the product directory.")

        target = self.project_root.joinpath(*source_path.parts)
        try:
            raw_content, verified_stat = ProductParser.read_verified_source(
                target,
                product_directory=product_dir,
                project_root=self.project_root,
            )
        except ProductSourceReadError as exc:
            if exc.path_error:
                raise ProductPathError(
                    "PRD source could not be read safely inside the project root."
                ) from exc
            raise ProductReadError(exc.safe_message) from exc
        return target, raw_content, verified_stat

    @staticmethod
    def _decode_source(raw_content: bytes) -> Tuple[bytes, str]:
        bom = _UTF8_BOM if raw_content.startswith(_UTF8_BOM) else b""
        payload = raw_content[len(bom):]
        try:
            return bom, payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProductReadError("PRD source is not valid UTF-8.") from exc

    @classmethod
    def _replace_front_matter_status(cls, text: str, new_status: str) -> str:
        lines = text.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            raise ProductReadError("PRD YAML front matter is missing.")

        closing_index = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                closing_index = index
                break
        if closing_index is None:
            raise ProductReadError("PRD YAML front matter is not closed.")

        yaml_start = len(lines[0])
        yaml_end = sum(len(line) for line in lines[:closing_index])
        yaml_text = text[yaml_start:yaml_end]
        try:
            root = yaml.compose(yaml_text, Loader=yaml.SafeLoader)
        except yaml.YAMLError as exc:
            raise ProductReadError(
                "PRD YAML front matter cannot be edited safely."
            ) from exc
        if not isinstance(root, MappingNode):
            raise ProductReadError("PRD YAML front matter is not a mapping.")

        status_values = [
            value_node
            for key_node, value_node in root.value
            if isinstance(key_node, ScalarNode)
            and canonical_metadata_key(key_node.value) == "status"
        ]
        if len(status_values) > 1:
            raise ProductReadError("PRD YAML contains an ambiguous status key.")
        if status_values:
            value_node = status_values[0]
            if not isinstance(value_node, ScalarNode):
                raise ProductReadError(
                    "PRD YAML status uses a layout that cannot be edited safely."
                )
            value_start = value_node.start_mark.index
            value_end = value_node.end_mark.index
            if (
                not isinstance(value_start, int)
                or not isinstance(value_end, int)
                or value_start < 0
                or value_end <= value_start
                or value_end > len(yaml_text)
            ):
                raise ProductReadError(
                    "PRD YAML status has an unsafe source span."
                )

            if value_node.style in {"|", ">"}:
                original_scalar = yaml_text[value_start:value_end]
                trailing_newline = original_scalar[len(original_scalar.rstrip("\r\n")):]
                replacement = new_status + trailing_newline
            elif value_node.style == "'":
                replacement = f"'{new_status}'"
            elif value_node.style == '"':
                replacement = f'"{new_status}"'
            elif value_node.style is None:
                replacement = new_status
            elif value_node.style is not None:
                raise ProductReadError(
                    "PRD YAML status uses an unsupported scalar style."
                )

            updated_yaml = (
                yaml_text[:value_start]
                + replacement
                + yaml_text[value_end:]
            )
            return text[:yaml_start] + updated_yaml + text[yaml_end:]

        if root.flow_style:
            raise ProductReadError(
                "PRD flow-style YAML has no status key and cannot be edited safely."
            )

        newline = "\r\n" if "\r\n" in text else "\n"
        if closing_index > 0 and not lines[closing_index - 1].endswith(
            ("\r\n", "\n", "\r")
        ):
            lines[closing_index - 1] += newline
        lines.insert(closing_index, f"status: {new_status}{newline}")
        return "".join(lines)

    @staticmethod
    def _write_temp_file(target: Path, content: bytes) -> Path:
        descriptor = -1
        temp_path: Optional[Path] = None
        try:
            descriptor, raw_temp_path = tempfile.mkstemp(
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=str(target.parent),
            )
            temp_path = Path(raw_temp_path)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            return temp_path
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise ProductWriteError("Unable to write a temporary PRD source.") from exc

    @classmethod
    def _atomic_create(cls, target: Path, content: bytes) -> None:
        temp_path = cls._write_temp_file(target, content)
        try:
            os.link(str(temp_path), str(target))
        except FileExistsError as exc:
            raise ProductCollisionError(
                f"PRD source already exists: .bck-nd/product/{target.name}"
            ) from exc
        except OSError as exc:
            raise ProductWriteError("Unable to publish the new PRD atomically.") from exc
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    def _atomic_replace(
        self,
        target: Path,
        content: bytes,
        original_stat: os.stat_result,
        original_content: bytes,
    ) -> None:
        temp_path = self._write_temp_file(target, content)
        try:
            os.chmod(temp_path, stat.S_IMODE(original_stat.st_mode))
            try:
                current_content, current_stat = ProductParser.read_verified_source(
                    target,
                    product_directory=target.parent,
                    project_root=self.project_root,
                )
            except ProductSourceReadError as exc:
                raise ProductPathError(
                    "PRD source changed during the update."
                ) from exc
            if (
                self._file_state(current_stat) != self._file_state(original_stat)
                or current_content != original_content
            ):
                raise ProductPathError("PRD source changed during the update.")
            os.replace(str(temp_path), str(target))
        except ProductServiceError:
            raise
        except OSError as exc:
            raise ProductWriteError("Unable to replace the PRD source atomically.") from exc
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    @staticmethod
    def _file_state(path_stat: os.stat_result) -> Tuple[int, int, int, int, int, int]:
        """Return identity plus content-sensitive metadata for optimistic locking."""
        return (
            path_stat.st_dev,
            path_stat.st_ino,
            stat.S_IFMT(path_stat.st_mode),
            path_stat.st_size,
            path_stat.st_mtime_ns,
            path_stat.st_ctime_ns,
        )


__all__ = [
    "DEFAULT_PRODUCT_ID",
    "PRODUCT_SCHEMA_VERSION",
    "ProductCollisionError",
    "ProductCreateResult",
    "ProductInvalidIdError",
    "ProductInvalidStatusError",
    "ProductNotFoundError",
    "ProductPathError",
    "ProductReadError",
    "ProductService",
    "ProductServiceError",
    "ProductStatusUpdateResult",
    "ProductTransitionBlockedError",
    "ProductValidationError",
    "ProductValidationReport",
    "ProductWriteError",
]
