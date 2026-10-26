from pyjs import js

from zepy.editor.common.core.position import Position
from zepy.editor.common.model.piece_tree_text_buffer.piece_tree_base import PieceTreeBase
from zepy.editor.common.vim import (
    bracket_span,
    clamp_normal,
    ex_is_edit,
    ex_is_line_number,
    ex_is_next,
    ex_is_nohl,
    ex_is_prev,
    ex_is_write,
    ex_line_number,
    find_char,
    first_nonblank_column,
    letter_index,
    match_bracket,
    quote_span,
    rest_after_word,
    toggle_case_char,
    word_back,
    word_end,
    word_forward,
    word_span,
)


@js
def test_word_forward_skips_to_the_next_word():
    buffer = PieceTreeBase("foo bar baz")
    pos = word_forward(buffer, Position(1, 1))
    assert pos.line_number == 1
    assert pos.column == 5
    pos = word_forward(buffer, pos)
    assert pos.column == 9


@js
def test_word_back_and_end():
    buffer = PieceTreeBase("foo bar")
    pos = word_end(buffer, Position(1, 1))
    assert pos.column == 3
    pos = word_back(buffer, Position(1, 5))
    assert pos.column == 1


@js
def test_clamp_normal_stays_on_the_last_character():
    buffer = PieceTreeBase("ab")
    pos = clamp_normal(buffer, Position(1, 8))
    assert pos.column == 2
    empty = PieceTreeBase("")
    pos = clamp_normal(empty, Position(1, 4))
    assert pos.column == 1


@js
def test_first_nonblank_skips_indent():
    buffer = PieceTreeBase("    hi")
    assert first_nonblank_column(buffer, 1) == 5


@js
def test_ex_write_commands():
    assert ex_is_write("w")
    assert ex_is_write(":w")
    assert ex_is_write("  write")
    assert ex_is_write("wq")
    assert not ex_is_write("q")
    assert not ex_is_write("set")


@js
def test_find_char_on_the_line():
    buffer = PieceTreeBase("abxcx")
    landed = find_char(buffer, Position(1, 1), "f", "x", 1)
    assert landed.column == 3
    landed = find_char(buffer, Position(1, 1), "f", "x", 2)
    assert landed.column == 5
    till = find_char(buffer, Position(1, 1), "t", "x", 1)
    assert till.column == 2
    back = find_char(buffer, Position(1, 5), "F", "b", 1)
    assert back.column == 2
    missing = find_char(buffer, Position(1, 1), "f", "z", 1)
    assert missing.line_number == 0


@js
def test_match_bracket_finds_the_pair():
    buffer = PieceTreeBase("a(bc(d)e)f")
    close = match_bracket(buffer, Position(1, 2))
    assert close.column == 9
    inner = match_bracket(buffer, Position(1, 5))
    assert inner.column == 7
    open_from_close = match_bracket(buffer, Position(1, 9))
    assert open_from_close.column == 2


@js
def test_word_span_and_toggle_case():
    buffer = PieceTreeBase("ab cd")
    span = word_span(buffer, Position(1, 1), False)
    assert span.start_column == 1
    assert span.end_column == 3
    indented = PieceTreeBase("    foo")
    inner = word_span(indented, Position(1, 5), False)
    assert inner.start_column == 5
    assert inner.end_column == 8
    assert toggle_case_char("a") == "A"
    assert toggle_case_char("Z") == "z"


@js
def test_quote_and_bracket_spans():
    quoted = PieceTreeBase('say "hi" now')
    inner = quote_span(quoted, Position(1, 6), '"', False)
    assert inner.start_column == 6
    assert inner.end_column == 8
    around = quote_span(quoted, Position(1, 6), '"', True)
    assert around.start_column == 5
    assert around.end_column == 9
    nested = PieceTreeBase("a(bc(d)e)f")
    inner_b = bracket_span(nested, Position(1, 3), "(", ")", False)
    assert inner_b.start_column == 3
    assert inner_b.end_column == 9
    around_b = bracket_span(nested, Position(1, 3), "(", ")", True)
    assert around_b.start_column == 2
    assert around_b.end_column == 10


@js
def test_ex_commands_and_letters():
    assert letter_index("a") == 0
    assert letter_index("z") == 25
    assert letter_index("A") == -1
    assert rest_after_word("e src/hello.py") == "src/hello.py"
    assert rest_after_word(":e  notes.txt") == "notes.txt"
    assert ex_is_line_number("12")
    assert ex_is_line_number(":40")
    assert not ex_is_line_number("w")
    assert ex_line_number(":12") == 12
    assert ex_is_edit("e")
    assert ex_is_edit(":edit foo")
    assert ex_is_next("n")
    assert ex_is_prev("N")
    assert ex_is_nohl("noh")
    assert ex_is_nohl("nohlsearch")
    assert not ex_is_nohl("w")
