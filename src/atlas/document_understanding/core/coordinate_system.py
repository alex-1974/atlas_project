# src/atlas/document_understanding/core/coordinate_system.py
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


EPSILON = 1e-9


def _safe_ratio(value: float | int | None, reference: float | int | None) -> float | None:
    if value is None or reference is None:
        return None
    v = float(value)
    r = float(reference)
    if not isfinite(v) or not isfinite(r):
        return None
    if abs(r) < EPSILON:
        return None
    return v / r


def _clamp01(value: float | None) -> float | None:
    if value is None:
        return None
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


@dataclass(frozen=True, slots=True)
class ColumnReference:
    left: float
    right: float

    @property
    def width(self) -> float:
        return max(0.0, self.right - self.left)

    @property
    def center_x(self) -> float:
        return self.left + self.width / 2.0


@dataclass(frozen=True, slots=True)
class DocumentCoordinateSystem:
    """
    Canonical normalized coordinate system for all Document Understanding layers.

    Design rule:
    - raw extraction may use absolute coordinates
    - DU analysis layers should prefer normalized, dimensionless values
    """

    page_width: float | None
    page_height: float | None
    document_height: float | None

    body_font_size: float | None
    median_line_gap: float | None
    median_paragraph_gap: float | None

    default_column_left: float | None
    default_column_right: float | None
    column_count: int | None = None

    def default_column(self) -> ColumnReference | None:
        if self.default_column_left is None or self.default_column_right is None:
            return None
        if self.default_column_right <= self.default_column_left:
            return None
        return ColumnReference(
            left=float(self.default_column_left),
            right=float(self.default_column_right),
        )

    def page_x_ratio(self, x: float | None) -> float | None:
        return _clamp01(_safe_ratio(x, self.page_width))

    def page_y_ratio(self, y: float | None) -> float | None:
        return _clamp01(_safe_ratio(y, self.page_height))

    def doc_y_ratio(self, y: float | None) -> float | None:
        return _clamp01(_safe_ratio(y, self.document_height))

    def width_ratio_to_page(self, width: float | None) -> float | None:
        return _clamp01(_safe_ratio(width, self.page_width))

    def height_ratio_to_page(self, height: float | None) -> float | None:
        return _clamp01(_safe_ratio(height, self.page_height))

    def font_ratio(self, font_size: float | None) -> float | None:
        return _safe_ratio(font_size, self.body_font_size)

    def line_gap_ratio(self, gap: float | None) -> float | None:
        return _safe_ratio(gap, self.median_line_gap)

    def paragraph_gap_ratio(self, gap: float | None) -> float | None:
        return _safe_ratio(gap, self.median_paragraph_gap)

    def width_ratio_to_column(
        self,
        width: float | None,
        column: ColumnReference | None = None,
    ) -> float | None:
        column = column or self.default_column()
        if column is None:
            return None
        return _clamp01(_safe_ratio(width, column.width))

    def indent_ratio(
        self,
        x0: float | None,
        column: ColumnReference | None = None,
    ) -> float | None:
        column = column or self.default_column()
        if column is None or x0 is None:
            return None
        return _safe_ratio(float(x0) - column.left, column.width)

    def right_indent_ratio(
        self,
        x1: float | None,
        column: ColumnReference | None = None,
    ) -> float | None:
        column = column or self.default_column()
        if column is None or x1 is None:
            return None
        return _safe_ratio(column.right - float(x1), column.width)

    def center_offset_ratio(
        self,
        x0: float | None,
        x1: float | None,
        column: ColumnReference | None = None,
    ) -> float | None:
        column = column or self.default_column()
        if column is None or x0 is None or x1 is None:
            return None
        width = column.width
        if width < EPSILON:
            return None
        line_center = (float(x0) + float(x1)) / 2.0
        return abs(line_center - column.center_x) / width

    def centeredness(
        self,
        x0: float | None,
        x1: float | None,
        column: ColumnReference | None = None,
    ) -> float | None:
        """
        1.0 = perfectly centered
        0.0 = strongly off-center
        """
        offset = self.center_offset_ratio(x0=x0, x1=x1, column=column)
        if offset is None:
            return None
        return max(0.0, 1.0 - min(1.0, 2.0 * offset))
