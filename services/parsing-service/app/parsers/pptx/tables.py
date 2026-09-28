from __future__ import annotations

import logging

from app.models.presentation import TableCell, TableElement

from pptx.oxml.ns import qn

logger = logging.getLogger(__name__)


def parse_table(table) -> TableElement:
    """Извлекает таблицу с текстом ячеек, объединениями и ширинами"""
    rows = len(table.rows)
    cols = len(table.columns)

    column_widths = [col.width for col in table.columns]
    row_heights = [row.height for row in table.rows]

    cells_matrix: list[list[TableCell]] = []
    for row in table.rows:
        row_cells: list[TableCell] = []
        for cell in row.cells:
            row_span, col_span, is_origin, is_spanned = parse_cell_span(cell)
            row_cells.append(
                TableCell(
                    text=cell.text,
                    row_span=row_span,
                    col_span=col_span,
                    is_merged_origin=is_origin,
                    is_spanned=is_spanned,
                )
            )
        cells_matrix.append(row_cells)

    return TableElement(
        rows=rows,
        cols=cols,
        column_widths=column_widths,
        row_heights=row_heights,
        first_row_header=is_first_row_header(table),
        banded_rows=is_banded_rows(table),
        cells=cells_matrix,
    )


def parse_cell_span(cell) -> tuple[int, int, bool, bool]:
    """Определяет span-атрибуты ячейки (row_span, col_span, origin, spanned)"""
    try:
        tc = cell._tc
        row_span = int(tc.get("rowSpan", "1"))
        col_span = int(tc.get("gridSpan", "1"))
        is_origin = row_span > 1 or col_span > 1
        is_spanned = tc.get("hMerge") == "1" or tc.get("vMerge") == "1"
        return row_span, col_span, is_origin, is_spanned
    except Exception:
        return 1, 1, False, False


def is_first_row_header(table) -> bool:
    """Проверяет флаг header-строки у таблицы"""
    try:
        tbl = table._tbl
        tblPr = tbl.find(qn("a:tblPr"))
        if tblPr is None:
            return False
        return tblPr.get("firstRow") == "1"
    except Exception:
        return False


def is_banded_rows(table) -> bool:
    """Проверяет флаг чередования фона строк"""
    try:
        tbl = table._tbl
        tblPr = tbl.find(qn("a:tblPr"))
        if tblPr is None:
            return False
        return tblPr.get("bandRow") == "1"
    except Exception:
        return False