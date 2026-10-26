"""Case-insensitive literal text search."""

from pyjs import js

from zepy.editor.common.core.range import Range
from zepy.editor.common.model.piece_tree_text_buffer.piece_tree_base import PieceTreeBase


@js
def find_index_from(haystack: str, needle: str, start: int) -> int:
    if needle == "":
        return -1
    needle_len = len(needle)
    hay_len = len(haystack)
    index = start
    while index + needle_len <= hay_len:
        if haystack[index : index + needle_len] == needle:
            return index
        index = index + 1
    return -1


@js
def find_ranges(buffer: PieceTreeBase, query: str) -> list[Range]:
    matches: list[Range] = []
    if query == "":
        return matches
    haystack = buffer.get_value().lower()
    needle = query.lower()
    needle_len = len(query)
    offset = 0
    while True:
        found = find_index_from(haystack, needle, offset)
        if found < 0:
            return matches
        start = buffer.get_position_at(found)
        end = buffer.get_position_at(found + needle_len)
        matches.append(
            Range(
                start.line_number,
                start.column,
                end.line_number,
                end.column,
            )
        )
        if len(matches) >= 200:
            return matches
        offset = found + len(needle)
        if len(needle) == 0:
            return matches
