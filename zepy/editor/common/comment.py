# Line-range labels and numbered snippets for comments shared with Codex.

from pyjs import js


@js
def line_span_label(path: str, start: int, end: int) -> str:
    name = path
    slash = path.rfind("/")
    if slash >= 0:
        name = path[slash + 1 :]
    if name == "":
        name = path
    if start < 1:
        return name
    if end > start:
        return name + ":" + str(start) + "-" + str(end)
    return name + ":" + str(start)


@js
def numbered_snippet(text: str, start_line: int) -> str:
    if text == "":
        return ""
    rows = text.split("\n")
    if len(rows) > 1 and rows[len(rows) - 1] == "":
        kept: list[str] = []
        index = 0
        last = len(rows) - 1
        while index < last:
            kept.append(rows[index])
            index = index + 1
        rows = kept
    line_no = start_line
    line_no = max(line_no, 1)
    parts: list[str] = []
    index = 0
    while index < len(rows):
        parts.append(str(line_no) + "| " + rows[index])
        line_no = line_no + 1
        index = index + 1
    return "\n".join(parts)
