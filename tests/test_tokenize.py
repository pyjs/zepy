from pyjs import js

from zepy.editor.common.tokenize import (
    COLOR_ADD,
    COLOR_COMMENT,
    COLOR_DEL,
    COLOR_FUNCTION,
    COLOR_KEYWORD,
    COLOR_META,
    COLOR_NUMBER,
    COLOR_STRING,
    COLOR_TEXT,
    COLOR_TYPE,
    STATE_NONE,
    STATE_TDQ,
    language_from_path,
    tokenize_line,
)


@js
def test_language_from_path():
    assert language_from_path("src/hello.py") == "python"
    assert language_from_path("workspace/welcome.md") == "markdown"
    assert language_from_path("notes.txt") == "plaintext"
    assert language_from_path("untitled") == "plaintext"
    assert language_from_path("review:dirty") == "diff"
    assert language_from_path("patch.diff") == "diff"


@js
def test_plaintext_is_one_color():
    tokens = tokenize_line("def not python", "plaintext", STATE_NONE)
    assert tokens.color_at(0) == COLOR_TEXT
    assert tokens.color_at(2) == COLOR_TEXT
    assert tokens.end_state == STATE_NONE


@js
def test_python_keywords_names_comments_and_strings():
    tokens = tokenize_line("def greet():  # hi", "python", STATE_NONE)
    assert tokens.color_at(0) == COLOR_KEYWORD
    assert tokens.color_at(2) == COLOR_KEYWORD
    assert tokens.color_at(4) == COLOR_FUNCTION
    assert tokens.color_at(8) == COLOR_FUNCTION
    assert tokens.color_at(15) == COLOR_COMMENT
    assert tokens.end_state == STATE_NONE

    assignment = tokenize_line("x = 12 + 'hi'", "python", STATE_NONE)
    assert assignment.color_at(4) == COLOR_NUMBER
    assert assignment.color_at(5) == COLOR_NUMBER
    assert assignment.color_at(9) == COLOR_STRING
    assert assignment.color_at(12) == COLOR_STRING

    typed = tokenize_line("class App:", "python", STATE_NONE)
    assert typed.color_at(0) == COLOR_KEYWORD
    assert typed.color_at(6) == COLOR_TYPE


@js
def test_python_one_line_docstring_does_not_leave_extra_quotes():
    line = '"""Server-side workspace listing for the explorer."""'
    tokens = tokenize_line(line, "python", STATE_NONE)
    assert tokens.end_state == STATE_NONE
    assert len(tokens.colors) == len(line)
    assert tokens.color_at(0) == COLOR_STRING
    assert tokens.color_at(len(line) - 1) == COLOR_STRING


@js
def test_python_triple_string_carries_state():
    first = tokenize_line('"""hello', "python", STATE_NONE)
    assert first.end_state == STATE_TDQ
    assert first.color_at(0) == COLOR_STRING
    second = tokenize_line('world""" x', "python", first.end_state)
    assert second.end_state == STATE_NONE
    assert second.color_at(0) == COLOR_STRING
    assert second.color_at(7) == COLOR_STRING
    assert second.color_at(8) == COLOR_TEXT
    assert second.color_at(9) == COLOR_TEXT


@js
def test_markdown_headings_and_code():
    heading = tokenize_line("# Title", "markdown", STATE_NONE)
    assert heading.color_at(0) == COLOR_KEYWORD
    assert heading.color_at(2) == COLOR_KEYWORD
    code = tokenize_line("use `x` here", "markdown", STATE_NONE)
    assert code.color_at(0) == COLOR_TEXT
    assert code.color_at(4) == COLOR_STRING
    assert code.color_at(6) == COLOR_STRING
    assert code.color_at(8) == COLOR_TEXT


@js
def test_diff_colors_add_and_delete():
    added = tokenize_line("+hello", "diff", STATE_NONE)
    assert added.color_at(0) == COLOR_ADD
    removed = tokenize_line("-hello", "diff", STATE_NONE)
    assert removed.color_at(0) == COLOR_DEL
    meta = tokenize_line("===== zepy/app.py [M] =====", "diff", STATE_NONE)
    assert meta.color_at(0) == COLOR_META
    moved = tokenize_line("rename from zepy/old.py", "diff", STATE_NONE)
    assert moved.color_at(0) == COLOR_TYPE
