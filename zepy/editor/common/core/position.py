"""Position."""

from pyjs import js


@js
class Position:
    def __init__(self, line_number: int, column: int):
        self.line_number = line_number
        self.column = column

    def with_position(self, line_number: int, column: int) -> Position:
        if line_number == self.line_number and column == self.column:
            return self
        return Position(line_number, column)

    def delta(self, delta_line_number: int, delta_column: int) -> Position:
        line_number = self.line_number + delta_line_number
        column = self.column + delta_column
        line_number = max(line_number, 1)
        column = max(column, 1)
        return self.with_position(line_number, column)

    def equals(self, other: Position) -> bool:
        return self.line_number == other.line_number and self.column == other.column

    def is_before(self, other: Position) -> bool:
        if self.line_number < other.line_number:
            return True
        if self.line_number > other.line_number:
            return False
        return self.column < other.column
