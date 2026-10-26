# Soft-wrap math for the GPU editor. Columns are character cells, not pixels.

from pyjs import js

from zepy.editor.common.model.piece_tree_text_buffer.piece_tree_base import PieceTreeBase


@js
def wrapped_row_count(length: int, columns: int) -> int:
    if columns < 1:
        return 1
    if length < 1:
        return 1
    rows = length // columns
    if length % columns != 0:
        rows = rows + 1
    if rows < 1:
        return 1
    return rows


@js
def wrap_row_of_column(column: int, columns: int) -> int:
    if columns < 1:
        return 0
    if column < 1:
        return 0
    return (column - 1) // columns


@js
def wrap_col_of_column(column: int, columns: int) -> int:
    if columns < 1:
        if column < 1:
            return 1
        return column
    if column < 1:
        return 1
    return (column - 1) % columns + 1


@js
def line_is_hidden(flags: list[int], line: int) -> bool:
    if line < 1 or line > len(flags):
        return False
    return flags[line - 1] == 1


@js
def visual_rows_before(buffer: PieceTreeBase, line: int, columns: int, flags: list[int]) -> int:
    n = 0
    scan = 1
    last = line - 1
    while scan <= last:
        if not line_is_hidden(flags, scan):
            if columns < 1:
                n = n + 1
            else:
                n = n + wrapped_row_count(buffer.get_line_length(scan), columns)
        scan = scan + 1
    return n


@js
def visual_line_count(buffer: PieceTreeBase, columns: int, flags: list[int]) -> int:
    return visual_rows_before(buffer, buffer.get_line_count() + 1, columns, flags)


@js
def line_at_visual_row(
    buffer: PieceTreeBase, visual_row: int, columns: int, flags: list[int]
) -> tuple[int, int]:
    row = 0
    line = 1
    last = buffer.get_line_count()
    last_line = 1
    target = visual_row
    target = max(target, 0)
    while line <= last:
        if line_is_hidden(flags, line):
            line = line + 1
            continue
        last_line = line
        n = 1
        if columns >= 1:
            n = wrapped_row_count(buffer.get_line_length(line), columns)
        if row + n > target:
            return (line, target - row)
        row = row + n
        line = line + 1
    return (last_line, 0)
