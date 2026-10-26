"""Range."""

from pyjs import js

from zepy.editor.common.core.position import Position


@js
class Range:
    def __init__(
        self,
        start_line_number: int,
        start_column: int,
        end_line_number: int,
        end_column: int,
    ):
        if start_line_number > end_line_number or (
            start_line_number == end_line_number and start_column > end_column
        ):
            self.start_line_number = end_line_number
            self.start_column = end_column
            self.end_line_number = start_line_number
            self.end_column = start_column
        else:
            self.start_line_number = start_line_number
            self.start_column = start_column
            self.end_line_number = end_line_number
            self.end_column = end_column

    def is_empty(self) -> bool:
        return (
            self.start_line_number == self.end_line_number and self.start_column == self.end_column
        )

    def get_start_position(self) -> Position:
        return Position(self.start_line_number, self.start_column)

    def get_end_position(self) -> Position:
        return Position(self.end_line_number, self.end_column)
