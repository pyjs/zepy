# Indent-based folds for the GPU editor. A header is a line whose next
# non-blank line is more indented; the fold runs until indent returns.

from pyjs import js

from zepy.editor.common.model.piece_tree_text_buffer.piece_tree_base import PieceTreeBase


@js
def line_indent(text: str) -> int:
    n = 0
    index = 0
    while index < len(text):
        ch = text[index]
        if ch == " ":
            n = n + 1
        elif ch == "\t":
            n = n + 4
        else:
            break
        index = index + 1
    return n


@js
def line_is_blank(text: str) -> bool:
    index = 0
    while index < len(text):
        ch = text[index]
        if ch != " " and ch != "\t":
            return False
        index = index + 1
    return True


@js
def fold_end(buffer: PieceTreeBase, start: int) -> int:
    last = buffer.get_line_count()
    if start < 1 or start >= last:
        return 0
    start_indent = line_indent(buffer.get_line_content(start))
    nxt = start + 1
    while nxt <= last and line_is_blank(buffer.get_line_content(nxt)):
        nxt = nxt + 1
    if nxt > last:
        return 0
    if line_indent(buffer.get_line_content(nxt)) <= start_indent:
        return 0
    end = nxt
    line = nxt + 1
    while line <= last:
        text = buffer.get_line_content(line)
        if line_is_blank(text):
            line = line + 1
            continue
        if line_indent(text) <= start_indent:
            break
        end = line
        line = line + 1
    return end


@js
def hidden_flags(line_count: int, starts: list[int], ends: list[int]) -> list[int]:
    flags: list[int] = []
    line = 1
    while line <= line_count:
        flags.append(0)
        line = line + 1
    index = 0
    while index < len(starts):
        start = starts[index]
        end = ends[index]
        line = start + 1
        while line <= end and line <= line_count:
            flags[line - 1] = 1
            line = line + 1
        index = index + 1
    return flags


@js
def visible_count_before(line: int, flags: list[int]) -> int:
    n = 0
    scan = 1
    last = len(flags)
    last = min(last, line - 1)
    while scan <= last:
        if flags[scan - 1] == 0:
            n = n + 1
        scan = scan + 1
    return n


@js
def visible_line_count(flags: list[int]) -> int:
    n = 0
    index = 0
    while index < len(flags):
        if flags[index] == 0:
            n = n + 1
        index = index + 1
    return n


@js
def line_at_view_index(flags: list[int], view_index: int) -> int:
    seen = 0
    index = 0
    last_visible = 1
    while index < len(flags):
        if flags[index] == 0:
            if seen == view_index:
                return index + 1
            last_visible = index + 1
            seen = seen + 1
        index = index + 1
    return last_visible


@js
def innermost_fold_start(buffer: PieceTreeBase, line: int) -> int:
    scan = line
    found = 0
    while scan >= 1:
        end = fold_end(buffer, scan)
        if end >= line:
            found = scan
            break
        scan = scan - 1
    return found
