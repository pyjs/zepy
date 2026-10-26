"""Selection."""

from pyjs import js

from zepy.editor.common.core.position import Position
from zepy.editor.common.core.range import Range


@js
class Selection(Range):
    def __init__(
        self,
        selection_start_line_number: int,
        selection_start_column: int,
        position_line_number: int,
        position_column: int,
    ):
        super().__init__(
            selection_start_line_number,
            selection_start_column,
            position_line_number,
            position_column,
        )
        self.selection_start_line_number = selection_start_line_number
        self.selection_start_column = selection_start_column
        self.position_line_number = position_line_number
        self.position_column = position_column

    def get_position(self) -> Position:
        return Position(self.position_line_number, self.position_column)
