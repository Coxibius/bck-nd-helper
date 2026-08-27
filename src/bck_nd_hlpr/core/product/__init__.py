"""PRD Intelligence domain core."""

from .models import (
    DiagnosticSeverity,
    ProductCollectionResult,
    ProductDiagnostic,
    ProductDiagnosticCode,
    ProductParseResult,
    ProductRequirementDocument,
    ProductSerializationError,
    ProductStatus,
)
from .parser import ProductParser
from .service import (
    DEFAULT_PRODUCT_ID,
    PRODUCT_SCHEMA_VERSION,
    ProductCollisionError,
    ProductCreateResult,
    ProductInvalidIdError,
    ProductInvalidStatusError,
    ProductNotFoundError,
    ProductPathError,
    ProductReadError,
    ProductService,
    ProductServiceError,
    ProductStatusUpdateResult,
    ProductTransitionBlockedError,
    ProductValidationError,
    ProductValidationReport,
    ProductWriteError,
)
from .templates import render_product_template
from .validator import ProductValidator

__all__ = [
    "DEFAULT_PRODUCT_ID",
    "DiagnosticSeverity",
    "PRODUCT_SCHEMA_VERSION",
    "ProductCollisionError",
    "ProductCollectionResult",
    "ProductCreateResult",
    "ProductDiagnostic",
    "ProductDiagnosticCode",
    "ProductInvalidIdError",
    "ProductInvalidStatusError",
    "ProductNotFoundError",
    "ProductParseResult",
    "ProductPathError",
    "ProductReadError",
    "ProductRequirementDocument",
    "ProductSerializationError",
    "ProductParser",
    "ProductService",
    "ProductServiceError",
    "ProductStatus",
    "ProductStatusUpdateResult",
    "ProductTransitionBlockedError",
    "ProductValidationError",
    "ProductValidationReport",
    "ProductValidator",
    "ProductWriteError",
    "render_product_template",
]
