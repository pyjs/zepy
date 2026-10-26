"""Modal editing with motions, counts, operators, and a yank register."""

from typing import Final

from pyjs import JS, js

from zepy.editor.common.core.position import Position
from zepy.editor.common.core.range import Range
from zepy.editor.common.model.piece_tree_text_buffer.piece_tree_base import PieceTreeBase
from zepy.editor.common.tokenize import is_ident_part

MODE_NORMAL: Final[JS] = "normal"
MODE_INSERT: Final[JS] = "insert"
MODE_VISUAL: Final[JS] = "visual"
MODE_VISUAL_LINE: Final[JS] = "visual-line"
MODE_VISUAL_BLOCK: Final[JS] = "visual-block"
MODE_COMMAND: Final[JS] = "command"


@js
class VimState:
    def __init__(self):
        self.mode = MODE_NORMAL
        self.count = 0
        self.operator = ""
        self.g_pending = False
        self.yank = ""
        self.yank_linewise = False
        self.yank_block = False
        self.block_insert = ""
        self.block_top = 1
        self.block_bot = 1
        self.block_col = 1
        self.block_old_len = 0
        self.command = ""
        self.find_pending = ""
        self.last_find_kind = ""
        self.last_find_char = ""
        self.command_kind = ":"
        self.text_object = ""
        self.indent_pending = ""
        self.replace_pending = False
        self.z_pending = False
        self.last_edit = ""
        self.last_edit_count = 1
        self.last_edit_char = ""
        self.last_edit_op = ""
        self.last_edit_motion = ""
        self.replaying = False
        self.mark_pending = False
        self.jump_pending = ""
        self.register_pending = False
        self.register_name = ""
        self.mark_line: list[int] = []
        self.mark_col: list[int] = []
        self.jump_line: list[int] = []
        self.jump_col: list[int] = []
        self.jump_index = -1
        self.reg_text: list[str] = []
        self.reg_linewise: list[int] = []
        fill = 0
        while fill < 26:
            self.mark_line.append(0)
            self.mark_col.append(0)
            self.reg_text.append("")
            self.reg_linewise.append(0)
            fill = fill + 1

    def reset_pending(self) -> None:
        self.count = 0
        self.operator = ""
        self.g_pending = False
        self.find_pending = ""
        self.text_object = ""
        self.indent_pending = ""
        self.replace_pending = False
        self.z_pending = False
        self.mark_pending = False
        self.jump_pending = ""
        self.register_pending = False
        self.register_name = ""

    def take_count(self) -> int:
        count = self.count
        self.count = 0
        if count < 1:
            return 1
        return count


@js
def offset_class(value: str, offset: int) -> int:
    if offset < 0 or offset >= len(value):
        return 0
    ch = value[offset]
    if ch == " " or ch == "\t" or ch == "\n":
        return 0
    if is_ident_part(ch):
        return 1
    return 2


@js
def clamp_normal(buffer: PieceTreeBase, pos: Position) -> Position:
    line = pos.line_number
    line = max(line, 1)
    last = buffer.get_line_count()
    line = min(line, last)
    length = buffer.get_line_length(line)
    column = pos.column
    if length < 1:
        column = 1
    elif column > length:
        column = length
    column = max(column, 1)
    return Position(line, column)


@js
def first_nonblank_column(buffer: PieceTreeBase, line: int) -> int:
    text = buffer.get_line_content(line)
    index = 0
    while index < len(text):
        ch = text[index]
        if ch != " " and ch != "\t":
            return index + 1
        index = index + 1
    if len(text) == 0:
        return 1
    return len(text)


@js
def word_forward(buffer: PieceTreeBase, pos: Position) -> Position:
    value = buffer.get_value()
    offset = buffer.get_offset_at(pos.line_number, pos.column)
    n = len(value)
    if offset >= n:
        return buffer.get_position_at(n)
    cls = offset_class(value, offset)
    while offset < n and offset_class(value, offset) == cls:
        offset = offset + 1
    while offset < n and offset_class(value, offset) == 0:
        offset = offset + 1
    if offset >= n:
        return clamp_normal(buffer, buffer.get_position_at(n))
    return buffer.get_position_at(offset)


@js
def word_back(buffer: PieceTreeBase, pos: Position) -> Position:
    value = buffer.get_value()
    offset = buffer.get_offset_at(pos.line_number, pos.column)
    if offset <= 0:
        return Position(1, 1)
    offset = offset - 1
    while offset > 0 and offset_class(value, offset) == 0:
        offset = offset - 1
    cls = offset_class(value, offset)
    while offset > 0 and offset_class(value, offset - 1) == cls:
        offset = offset - 1
    return buffer.get_position_at(offset)


@js
def word_end(buffer: PieceTreeBase, pos: Position) -> Position:
    value = buffer.get_value()
    offset = buffer.get_offset_at(pos.line_number, pos.column)
    n = len(value)
    if n == 0:
        return Position(1, 1)
    if offset < n - 1:
        offset = offset + 1
    while offset < n and offset_class(value, offset) == 0:
        offset = offset + 1
    cls = offset_class(value, offset)
    while offset + 1 < n and offset_class(value, offset + 1) == cls:
        offset = offset + 1
    if offset >= n:
        offset = n - 1
    return clamp_normal(buffer, buffer.get_position_at(offset))


@js
def find_char(
    buffer: PieceTreeBase,
    pos: Position,
    kind: str,
    ch: str,
    count: int,
) -> Position:
    line = buffer.get_line_content(pos.line_number)
    start = pos.column - 1
    found = 0
    if kind == "f" or kind == "t":
        index = start + 1
        while index < len(line):
            if line[index] == ch:
                found = found + 1
                if found == count:
                    if kind == "t":
                        if index < 1:
                            return Position(0, 0)
                        return Position(pos.line_number, index)
                    return Position(pos.line_number, index + 1)
            index = index + 1
        return Position(0, 0)
    index = start - 1
    while index >= 0:
        if line[index] == ch:
            found = found + 1
            if found == count:
                if kind == "T":
                    dest = index + 2
                    length = len(line)
                    dest = min(dest, length)
                    if dest < 1:
                        return Position(0, 0)
                    return Position(pos.line_number, dest)
                return Position(pos.line_number, index + 1)
        index = index - 1
    return Position(0, 0)


@js
def reverse_find_kind(kind: str) -> str:
    if kind == "f":
        return "F"
    if kind == "F":
        return "f"
    if kind == "t":
        return "T"
    if kind == "T":
        return "t"
    return kind


@js
def is_open_bracket(ch: str) -> bool:
    return ch == "(" or ch == "[" or ch == "{"


@js
def is_close_bracket(ch: str) -> bool:
    return ch == ")" or ch == "]" or ch == "}"


@js
def closing_bracket(ch: str) -> str:
    if ch == "(":
        return ")"
    if ch == "[":
        return "]"
    if ch == "{":
        return "}"
    return ""


@js
def opening_bracket(ch: str) -> str:
    if ch == ")":
        return "("
    if ch == "]":
        return "["
    if ch == "}":
        return "{"
    return ""


@js
def match_bracket(buffer: PieceTreeBase, pos: Position) -> Position:
    value = buffer.get_value()
    n = len(value)
    offset = buffer.get_offset_at(pos.line_number, pos.column)
    if offset >= n:
        return Position(0, 0)
    ch = value[offset]
    if not is_open_bracket(ch) and not is_close_bracket(ch):
        scan = offset
        while scan < n:
            here = value[scan]
            if is_open_bracket(here) or is_close_bracket(here):
                offset = scan
                ch = here
                break
            scan = scan + 1
        if scan >= n:
            return Position(0, 0)
    if is_open_bracket(ch):
        want = closing_bracket(ch)
        depth = 1
        index = offset + 1
        while index < n:
            here = value[index]
            if here == ch:
                depth = depth + 1
            elif here == want:
                depth = depth - 1
                if depth == 0:
                    return buffer.get_position_at(index)
            index = index + 1
        return Position(0, 0)
    want = opening_bracket(ch)
    depth = 1
    index = offset - 1
    while index >= 0:
        here = value[index]
        if here == ch:
            depth = depth + 1
        elif here == want:
            depth = depth - 1
            if depth == 0:
                return buffer.get_position_at(index)
        index = index - 1
    return Position(0, 0)


@js
def word_span(buffer: PieceTreeBase, pos: Position, around: bool) -> Range:
    value = buffer.get_value()
    n = len(value)
    if n == 0:
        return Range(1, 1, 1, 1)
    offset = buffer.get_offset_at(pos.line_number, pos.column)
    if offset >= n:
        offset = n - 1
    cls = offset_class(value, offset)
    start = offset
    while start > 0 and offset_class(value, start - 1) == cls:
        start = start - 1
    end = offset
    while end < n and offset_class(value, end) == cls:
        end = end + 1
    if around and cls != 0:
        while end < n and offset_class(value, end) == 0 and value[end] != "\n":
            end = end + 1
    a = buffer.get_position_at(start)
    b = buffer.get_position_at(end)
    return Range(a.line_number, a.column, b.line_number, b.column)


@js
def quote_is_escaped(line: str, index: int) -> bool:
    slashes = 0
    i = index - 1
    while i >= 0 and line[i] == "\\":
        slashes = slashes + 1
        i = i - 1
    return slashes % 2 == 1


@js
def quote_span(buffer: PieceTreeBase, pos: Position, quote: str, around: bool) -> Range:
    line_n = pos.line_number
    line = buffer.get_line_content(line_n)
    if len(line) == 0:
        return Range(0, 1, 0, 1)
    col = pos.column - 1
    col = max(col, 0)
    if col >= len(line):
        col = len(line) - 1
    left = -1
    i = col
    while i >= 0:
        if line[i] == quote and not quote_is_escaped(line, i):
            left = i
            break
        i = i - 1
    if left < 0:
        i = col
        while i < len(line):
            if line[i] == quote and not quote_is_escaped(line, i):
                left = i
                break
            i = i + 1
    if left < 0:
        return Range(0, 1, 0, 1)
    right = -1
    i = left + 1
    while i < len(line):
        if line[i] == quote and not quote_is_escaped(line, i):
            right = i
            break
        i = i + 1
    if right < 0:
        return Range(0, 1, 0, 1)
    if around:
        return Range(line_n, left + 1, line_n, right + 2)
    return Range(line_n, left + 2, line_n, right + 1)


@js
def bracket_span(
    buffer: PieceTreeBase, pos: Position, open_ch: str, close_ch: str, around: bool
) -> Range:
    value = buffer.get_value()
    n = len(value)
    if n == 0:
        return Range(0, 1, 0, 1)
    offset = buffer.get_offset_at(pos.line_number, pos.column)
    if offset >= n:
        offset = n - 1
    if offset < 0:
        return Range(0, 1, 0, 1)
    start = -1
    ch = value[offset]
    if ch == close_ch:
        depth = 1
        i = offset - 1
        while i >= 0:
            here = value[i]
            if here == close_ch:
                depth = depth + 1
            elif here == open_ch:
                depth = depth - 1
                if depth == 0:
                    start = i
                    break
            i = i - 1
    elif ch == open_ch:
        start = offset
    else:
        depth = 0
        i = offset
        while i >= 0:
            here = value[i]
            if here == close_ch:
                depth = depth + 1
            elif here == open_ch:
                if depth == 0:
                    start = i
                    break
                depth = depth - 1
            i = i - 1
    if start < 0:
        return Range(0, 1, 0, 1)
    depth = 1
    end = -1
    i = start + 1
    while i < n:
        here = value[i]
        if here == open_ch:
            depth = depth + 1
        elif here == close_ch:
            depth = depth - 1
            if depth == 0:
                end = i
                break
        i = i + 1
    if end < 0:
        return Range(0, 1, 0, 1)
    if around:
        a = buffer.get_position_at(start)
        b = buffer.get_position_at(end + 1)
        return Range(a.line_number, a.column, b.line_number, b.column)
    a = buffer.get_position_at(start + 1)
    b = buffer.get_position_at(end)
    return Range(a.line_number, a.column, b.line_number, b.column)


@js
def letter_index(key: str) -> int:
    letters = "abcdefghijklmnopqrstuvwxyz"
    i = 0
    while i < 26:
        if letters[i] == key:
            return i
        i = i + 1
    return -1


@js
def rest_after_word(text: str) -> str:
    word = first_word(text)
    index = 0
    while index < len(text) and (text[index] == " " or text[index] == "\t" or text[index] == ":"):
        index = index + 1
    index = index + len(word)
    while index < len(text) and (text[index] == " " or text[index] == "\t"):
        index = index + 1
    return text[index:]


@js
def ex_is_line_number(text: str) -> bool:
    word = first_word(text)
    if word == "":
        return False
    i = 0
    while i < len(word):
        ch = word[i]
        if ch < "0" or ch > "9":
            return False
        i = i + 1
    return True


@js
def ex_line_number(text: str) -> int:
    word = first_word(text)
    n = 0
    i = 0
    while i < len(word):
        n = n * 10 + digit_value(word[i])
        i = i + 1
    return n


@js
def toggle_case_char(ch: str) -> str:
    if ch >= "a" and ch <= "z":
        return ch.upper()
    if ch >= "A" and ch <= "Z":
        return ch.lower()
    return ch


@js
def first_word(text: str) -> str:
    index = 0
    while index < len(text) and (text[index] == " " or text[index] == "\t" or text[index] == ":"):
        index = index + 1
    start = index
    while index < len(text) and text[index] != " " and text[index] != "\t":
        index = index + 1
    return text[start:index]


@js
def ex_is_write(text: str) -> bool:
    word = first_word(text)
    if word == "w" or word == "wq" or word == "x":
        return True
    return word == "wr" or word == "wri" or word == "writ" or word == "write"


@js
def ex_is_edit(text: str) -> bool:
    word = first_word(text)
    return word == "e" or word == "ed" or word == "edi" or word == "edit"


@js
def ex_is_next(text: str) -> bool:
    word = first_word(text)
    return word == "n" or word == "ne" or word == "nex" or word == "next"


@js
def ex_is_prev(text: str) -> bool:
    word = first_word(text)
    return word == "N" or word == "prev" or word == "Next" or word == "previous"


@js
def ex_is_nohl(text: str) -> bool:
    word = first_word(text)
    return word == "noh" or word == "nohl" or word == "nohls" or word == "nohlsearch"


@js
def digit_value(key: str) -> int:
    if key == "0":
        return 0
    if key == "1":
        return 1
    if key == "2":
        return 2
    if key == "3":
        return 3
    if key == "4":
        return 4
    if key == "5":
        return 5
    if key == "6":
        return 6
    if key == "7":
        return 7
    if key == "8":
        return 8
    if key == "9":
        return 9
    return -1
