"""Standard pagination models, metadata contracts, and safe sorting utilities."""

from typing import Generic, TypeVar, List, Optional, Set
from pydantic import BaseModel, Field

T = TypeVar("T")

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


class PaginationParams(BaseModel):
    """Query parameters for paginated list endpoints."""

    page: int = Field(default=DEFAULT_PAGE, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description=f"Number of items per page (max {MAX_PAGE_SIZE})")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard pagination envelope."""

    items: List[T]
    page: int
    page_size: int
    total_items: int
    total_pages: int

    @classmethod
    def create(cls, items: List[T], total_items: int, params: PaginationParams) -> "PaginatedResponse[T]":
        total_pages = (total_items + params.page_size - 1) // params.page_size if total_items > 0 else 0
        return cls(
            items=items,
            page=params.page,
            page_size=params.page_size,
            total_items=total_items,
            total_pages=total_pages,
        )


def validate_sort_field(field_name: Optional[str], allowed_fields: Set[str], default_field: str = "created_at") -> str:
    """Safely validate and whitelist sort column names preventing SQL injection."""
    if not field_name:
        return default_field
    field_clean = field_name.strip().lower()
    if field_clean not in allowed_fields:
        raise ValueError(f"Invalid sort field '{field_name}'. Must be one of: {sorted(allowed_fields)}")
    return field_clean
