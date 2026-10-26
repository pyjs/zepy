from pyjs import js

from zepy.editor.common.folds import (
    fold_end,
    hidden_flags,
    innermost_fold_start,
    line_at_view_index,
    line_indent,
    visible_count_before,
    visible_line_count,
)
from zepy.editor.common.model.piece_tree_text_buffer.piece_tree_base import PieceTreeBase


@js
def test_line_indent_counts_spaces_and_tabs():
    assert line_indent("    x") == 4
    assert line_indent("\tx") == 4
    assert line_indent("x") == 0


@js
def test_fold_end_covers_indented_block():
    buffer = PieceTreeBase("def f():\n    x = 1\n    y = 2\nz = 3")
    assert fold_end(buffer, 1) == 3
    assert fold_end(buffer, 2) == 0
    assert fold_end(buffer, 4) == 0


@js
def test_hidden_flags_and_view_index():
    buffer = PieceTreeBase("def f():\n    x = 1\n    y = 2\nz = 3")
    end = fold_end(buffer, 1)
    flags = hidden_flags(buffer.get_line_count(), [1], [end])
    assert flags[0] == 0
    assert flags[1] == 1
    assert flags[2] == 1
    assert flags[3] == 0
    assert visible_line_count(flags) == 2
    assert visible_count_before(4, flags) == 1
    assert line_at_view_index(flags, 0) == 1
    assert line_at_view_index(flags, 1) == 4
    assert innermost_fold_start(buffer, 3) == 1
