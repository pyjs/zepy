"""Text buffer backed by a linear list of pieces."""

from pyjs import js

from zepy.base.common.strings import split_lines
from zepy.editor.common.core.position import Position
from zepy.editor.common.core.range import Range


@js
class PieceTreeBase:
    def __init__(self, value: str = ""):
        self._eol = "\n"
        self._value = ""
        self._lines: list[str] = [""]
        self.set_value(value)

    def set_value(self, value: str) -> None:
        self._value = value.replace("\r\n", "\n").replace("\r", "\n")
        self._rebuild_lines()

    def _rebuild_lines(self) -> None:
        self._lines = split_lines(self._value)

    def get_value(self) -> str:
        return self._value

    def get_length(self) -> int:
        return len(self._value)

    def get_line_count(self) -> int:
        return len(self._lines)

    def get_line_content(self, line_number: int) -> str:
        if line_number < 1 or line_number > len(self._lines):
            return ""
        return self._lines[line_number - 1]

    def get_line_length(self, line_number: int) -> int:
        return len(self.get_line_content(line_number))

    def get_offset_at(self, line_number: int, column: int) -> int:
        if line_number < 1:
            return 0
        offset = 0
        index = 1
        while index < line_number and index <= len(self._lines):
            offset = offset + len(self._lines[index - 1]) + 1
            index = index + 1
        line_length = 0
        if line_number <= len(self._lines):
            line_length = len(self._lines[line_number - 1])
        extra = column - 1
        extra = max(extra, 0)
        extra = min(extra, line_length)
        return offset + extra

    def get_position_at(self, offset: int) -> Position:
        offset = max(offset, 0)
        offset = min(offset, len(self._value))
        remaining = offset
        line_number = 1
        while line_number <= len(self._lines):
            line = self._lines[line_number - 1]
            if remaining <= len(line):
                return Position(line_number, remaining + 1)
            remaining = remaining - len(line) - 1
            line_number = line_number + 1
        last = len(self._lines)
        return Position(last, len(self._lines[last - 1]) + 1)

    def insert(self, offset: int, text: str) -> None:
        offset = max(offset, 0)
        offset = min(offset, len(self._value))
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        self._value = self._value[0:offset] + normalized + self._value[offset:]
        self._rebuild_lines()

    def delete(self, offset: int, length: int) -> None:
        if length <= 0:
            return
        offset = max(offset, 0)
        end = offset + length
        end = min(end, len(self._value))
        self._value = self._value[0:offset] + self._value[end:]
        self._rebuild_lines()

    def apply_edits(self, range: Range, text: str) -> None:
        start = self.get_offset_at(range.start_line_number, range.start_column)
        end = self.get_offset_at(range.end_line_number, range.end_column)
        if end > start:
            self.delete(start, end - start)
        if text != "":
            self.insert(start, text)
