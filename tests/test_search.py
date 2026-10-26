from pyjs import js

from zepy.editor.common.model.piece_tree_text_buffer.piece_tree_base import PieceTreeBase
from zepy.editor.common.search import find_index_from, find_ranges


@js
def test_find_index_from_returns_the_next_literal():
    assert find_index_from("ababa", "ba", 0) == 1
    assert find_index_from("ababa", "ba", 2) == 3
    assert find_index_from("ababa", "ba", 4) == -1
    assert find_index_from("aaa", "", 0) == -1


@js
def test_find_ranges_is_case_insensitive():
    buffer = PieceTreeBase("Foo foo FOO")
    matches = find_ranges(buffer, "foo")
    assert len(matches) == 3
    assert matches[0].start_column == 1
    assert matches[0].end_column == 4
    assert matches[1].start_column == 5
    assert matches[2].start_column == 9


@js
def test_find_ranges_spans_lines():
    buffer = PieceTreeBase("one\ntwo one")
    matches = find_ranges(buffer, "one")
    assert len(matches) == 2
    assert matches[0].start_line_number == 1
    assert matches[1].start_line_number == 2
    assert matches[1].start_column == 5
