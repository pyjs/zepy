from pyjs import js

from zepy.editor.common.folds import hidden_flags
from zepy.editor.common.model.piece_tree_text_buffer.piece_tree_base import PieceTreeBase
from zepy.editor.common.wrap import (
    line_at_visual_row,
    visual_line_count,
    visual_rows_before,
    wrap_col_of_column,
    wrap_row_of_column,
    wrapped_row_count,
)


@js
def test_wrapped_row_count_splits_on_columns():
    assert wrapped_row_count(0, 10) == 1
    assert wrapped_row_count(10, 10) == 1
    assert wrapped_row_count(11, 10) == 2
    assert wrapped_row_count(20, 10) == 2
    assert wrapped_row_count(21, 10) == 3
    assert wrapped_row_count(8, 0) == 1


@js
def test_wrap_row_and_column_are_one_based():
    assert wrap_row_of_column(1, 10) == 0
    assert wrap_row_of_column(10, 10) == 0
    assert wrap_row_of_column(11, 10) == 1
    assert wrap_col_of_column(1, 10) == 1
    assert wrap_col_of_column(10, 10) == 10
    assert wrap_col_of_column(11, 10) == 1


@js
def test_visual_rows_skip_folded_lines_and_count_wraps():
    buffer = PieceTreeBase("short\n" + ("x" * 12) + "\nhi")
    flags = hidden_flags(3, [], [])
    assert visual_rows_before(buffer, 1, 10, flags) == 0
    assert visual_rows_before(buffer, 2, 10, flags) == 1
    assert visual_rows_before(buffer, 3, 10, flags) == 3
    assert visual_line_count(buffer, 10, flags) == 4
    line, row = line_at_visual_row(buffer, 2, 10, flags)
    assert line == 2
    assert row == 1
    folded = hidden_flags(3, [1], [2])
    assert visual_line_count(buffer, 10, folded) == 2
