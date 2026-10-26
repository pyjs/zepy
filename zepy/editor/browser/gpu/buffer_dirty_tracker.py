"""Buffer dirty tracker."""

from pyjs import js


@js
class BufferDirtyTracker:
    def __init__(self):
        self._start_index: int | None = None
        self._end_index: int | None = None

    @property
    def data_offset(self) -> int | None:
        return self._start_index

    @property
    def dirty_size(self) -> int | None:
        if self._start_index is None or self._end_index is None:
            return None
        return self._end_index - self._start_index + 1

    @property
    def is_dirty(self) -> bool:
        return self._start_index is not None

    def flag(self, index: int, length: int = 1) -> int:
        self._flag(index)
        if length > 1:
            self._flag(index + length - 1)
        return index

    def _flag(self, index: int) -> None:
        if self._start_index is None or index < self._start_index:
            self._start_index = index
        if self._end_index is None or index > self._end_index:
            self._end_index = index

    def clear(self) -> None:
        self._start_index = None
        self._end_index = None
