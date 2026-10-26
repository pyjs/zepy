"""Line tokenizer producing per-character colors for the glyph atlas."""

from typing import Final

from pyjs import JS, js

COLOR_TEXT: Final[JS] = "#d4d4d4"
COLOR_KEYWORD: Final[JS] = "#569cd6"
COLOR_STRING: Final[JS] = "#ce9178"
COLOR_COMMENT: Final[JS] = "#6a9955"
COLOR_NUMBER: Final[JS] = "#b5cea8"
COLOR_FUNCTION: Final[JS] = "#dcdcaa"
COLOR_TYPE: Final[JS] = "#4ec9b0"
COLOR_ADD: Final[JS] = "#81b88b"
COLOR_DEL: Final[JS] = "#f14c4c"
COLOR_META: Final[JS] = "#569cd6"

STATE_NONE: Final[JS] = 0
STATE_SQ: Final[JS] = 1
STATE_DQ: Final[JS] = 2
STATE_TSQ: Final[JS] = 3
STATE_TDQ: Final[JS] = 4
STATE_FENCE: Final[JS] = 5

PYTHON_KEYWORDS: Final[JS] = (
    " False None True and as assert async await break class continue def del "
    "elif else except finally for from global if import in is lambda nonlocal "
    "not or pass raise return try while with yield match case self cls "
)

PYTHON_BUILTINS: Final[JS] = (
    " print len range str int float bool list dict set tuple type super "
    "object open enumerate zip map filter abs min max sum any all "
)


@js
class LineTokens:
    def __init__(self, colors: list[str], end_state: int):
        self.colors = colors
        self.end_state = end_state

    def color_at(self, column: int) -> str:
        if column < 0 or column >= len(self.colors):
            return COLOR_TEXT
        return self.colors[column]


@js
def has_suffix(path: str, suffix: str) -> bool:
    path_len = len(path)
    suffix_len = len(suffix)
    if path_len < suffix_len:
        return False
    return path[path_len - suffix_len :] == suffix


@js
def language_from_path(path: str) -> str:
    if has_suffix(path, ".py"):
        return "python"
    if has_suffix(path, ".md"):
        return "markdown"
    if has_suffix(path, ".diff") or path.startswith("review:"):
        return "diff"
    return "plaintext"


@js
def starts_at(line: str, index: int, token: str) -> bool:
    if index + len(token) > len(line):
        return False
    offset = 0
    while offset < len(token):
        if line[index + offset] != token[offset]:
            return False
        offset = offset + 1
    return True


@js
def is_ident_start(ch: str) -> bool:
    if ch == "_":
        return True
    if ch >= "A" and ch <= "Z":
        return True
    return ch >= "a" and ch <= "z"


@js
def is_ident_part(ch: str) -> bool:
    if is_ident_start(ch):
        return True
    return ch >= "0" and ch <= "9"


@js
def is_digit(ch: str) -> bool:
    return ch >= "0" and ch <= "9"


@js
def in_blob(word: str, blob: str) -> bool:
    return (" " + word + " ") in blob


@js
def add_range(colors: list[str], start: int, end: int, color: str) -> None:
    index = start
    while index < end:
        colors.append(color)
        index = index + 1


@js
def tokenize_plain(line: str) -> LineTokens:
    colors: list[str] = []
    add_range(colors, 0, len(line), COLOR_TEXT)
    return LineTokens(colors, STATE_NONE)


@js
def quote_kind(line: str, index: int) -> int:
    if starts_at(line, index, "'''"):
        return STATE_TSQ
    if starts_at(line, index, '"""'):
        return STATE_TDQ
    if line[index] == "'":
        return STATE_SQ
    if line[index] == '"':
        return STATE_DQ
    return STATE_NONE


@js
def prefix_then_quote(line: str, index: int) -> int:
    pos = index
    taken = 0
    while taken < 2 and pos < len(line):
        ch = line[pos]
        if (
            ch == "r"
            or ch == "R"
            or ch == "f"
            or ch == "F"
            or ch == "b"
            or ch == "B"
            or ch == "u"
            or ch == "U"
        ):
            pos = pos + 1
            taken = taken + 1
        else:
            break
    if pos < len(line) and (line[pos] == "'" or line[pos] == '"'):
        return pos
    return -1


@js
def find_string_end(line: str, start: int, state: int) -> int:
    quote = "'"
    if state == STATE_DQ or state == STATE_TDQ:
        quote = '"'
    if state == STATE_TSQ or state == STATE_TDQ:
        closer = quote + quote + quote
        index = start
        while index < len(line):
            if starts_at(line, index, closer):
                return index + 3
            index = index + 1
        return -1
    index = start
    while index < len(line):
        ch = line[index]
        if ch == "\\" and index + 1 < len(line):
            index = index + 2
            continue
        if ch == quote:
            return index + 1
        index = index + 1
    return -1


@js
def paint_string(colors: list[str], line: str, start: int, state: int) -> int:
    end = find_string_end(line, start, state)
    if end < 0:
        add_range(colors, start, len(line), COLOR_STRING)
        return -1
    add_range(colors, start, end, COLOR_STRING)
    return end


@js
def tokenize_python(line: str, state: int) -> LineTokens:
    colors: list[str] = []
    index = 0
    expect_def = False
    expect_class = False
    if state == STATE_SQ or state == STATE_DQ or state == STATE_TSQ or state == STATE_TDQ:
        index = paint_string(colors, line, 0, state)
        if index < 0:
            return LineTokens(colors, state)
        state = STATE_NONE

    while index < len(line):
        ch = line[index]
        if ch == " " or ch == "\t":
            colors.append(COLOR_TEXT)
            index = index + 1
            continue
        if ch == "#":
            add_range(colors, index, len(line), COLOR_COMMENT)
            return LineTokens(colors, STATE_NONE)
        if ch == "@":
            colors.append(COLOR_FUNCTION)
            index = index + 1
            expect_def = True
            continue
        quote_at = prefix_then_quote(line, index)
        if quote_at >= 0:
            kind = quote_kind(line, quote_at)
            opener = 1
            if kind == STATE_TSQ or kind == STATE_TDQ:
                opener = 3
            add_range(colors, index, quote_at + opener, COLOR_STRING)
            next_index = paint_string(colors, line, quote_at + opener, kind)
            if next_index < 0:
                return LineTokens(colors, kind)
            index = next_index
            expect_def = False
            expect_class = False
            continue
        if is_digit(ch):
            start = index
            index = index + 1
            if ch == "0" and index < len(line) and (line[index] == "x" or line[index] == "X"):
                index = index + 1
                while index < len(line):
                    hex_ch = line[index]
                    if (
                        is_digit(hex_ch)
                        or (hex_ch >= "a" and hex_ch <= "f")
                        or (hex_ch >= "A" and hex_ch <= "F")
                    ):
                        index = index + 1
                    else:
                        break
            else:
                while index < len(line) and (is_digit(line[index]) or line[index] == "_"):
                    index = index + 1
                if index < len(line) and line[index] == ".":
                    index = index + 1
                    while index < len(line) and (is_digit(line[index]) or line[index] == "_"):
                        index = index + 1
            add_range(colors, start, index, COLOR_NUMBER)
            expect_def = False
            expect_class = False
            continue
        if is_ident_start(ch):
            start = index
            index = index + 1
            while index < len(line) and is_ident_part(line[index]):
                index = index + 1
            word = line[start:index]
            color = COLOR_TEXT
            if expect_def:
                color = COLOR_FUNCTION
                expect_def = False
                expect_class = False
            elif expect_class:
                color = COLOR_TYPE
                expect_def = False
                expect_class = False
            elif in_blob(word, PYTHON_KEYWORDS):
                color = COLOR_KEYWORD
                if word == "def":
                    expect_def = True
                elif word == "class":
                    expect_class = True
            elif in_blob(word, PYTHON_BUILTINS):
                color = COLOR_FUNCTION
            add_range(colors, start, index, color)
            continue
        colors.append(COLOR_TEXT)
        index = index + 1
        expect_def = False
        expect_class = False
    return LineTokens(colors, STATE_NONE)


@js
def leading_ws(line: str) -> int:
    index = 0
    while index < len(line) and (line[index] == " " or line[index] == "\t"):
        index = index + 1
    return index


@js
def tokenize_markdown(line: str, state: int) -> LineTokens:
    colors: list[str] = []
    if state == STATE_FENCE:
        add_range(colors, 0, len(line), COLOR_STRING)
        indent = leading_ws(line)
        if starts_at(line, indent, "```"):
            return LineTokens(colors, STATE_NONE)
        return LineTokens(colors, STATE_FENCE)
    indent = leading_ws(line)
    if starts_at(line, indent, "```"):
        add_range(colors, 0, len(line), COLOR_STRING)
        return LineTokens(colors, STATE_FENCE)
    if indent < len(line) and line[indent] == "#":
        add_range(colors, 0, len(line), COLOR_KEYWORD)
        return LineTokens(colors, STATE_NONE)
    index = 0
    while index < len(line):
        if line[index] == "`":
            start = index
            index = index + 1
            while index < len(line) and line[index] != "`":
                index = index + 1
            if index < len(line):
                index = index + 1
            add_range(colors, start, index, COLOR_STRING)
            continue
        colors.append(COLOR_TEXT)
        index = index + 1
    return LineTokens(colors, STATE_NONE)


@js
def tokenize_diff(line: str) -> LineTokens:
    colors: list[str] = []
    color = COLOR_TEXT
    if (
        line[0:3] == "+++"
        or line[0:3] == "---"
        or line[0:5] == "diff "
        or line[0:2] == "@@"
        or line[0:5] == "====="
    ):
        color = COLOR_META
    elif (
        line[0:7] == "rename "
        or line[0:5] == "copy "
        or line[0:11] == "similarity"
        or line[0:6] == "index "
    ):
        color = COLOR_TYPE
    elif len(line) > 0 and line[0] == "+":
        color = COLOR_ADD
    elif len(line) > 0 and line[0] == "-":
        color = COLOR_DEL
    add_range(colors, 0, len(line), color)
    return LineTokens(colors, STATE_NONE)


@js
def tokenize_line(line: str, language: str, state: int) -> LineTokens:
    if language == "python":
        return tokenize_python(line, state)
    if language == "markdown":
        return tokenize_markdown(line, state)
    if language == "diff":
        return tokenize_diff(line)
    return tokenize_plain(line)
