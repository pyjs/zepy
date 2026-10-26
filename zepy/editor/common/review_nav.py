# Navigate a concatenated review buffer of unified diffs.

from pyjs import js


@js
def parse_review_header(line: str) -> str:
    if not line.startswith("===== "):
        return ""
    rest = line[6:]
    end = rest.rfind(" =====")
    if end < 0:
        return ""
    rest = rest[0:end]
    bracket = rest.rfind(" [")
    if bracket > 0:
        rest = rest[0:bracket]
    rest = rest.strip()
    arrow = rest.find(" -> ")
    if arrow >= 0:
        rest = rest[arrow + 4 :]
    return rest.strip()


@js
def hunk_new_line(line: str) -> int:
    if not line.startswith("@@ "):
        return 0
    plus = line.find(" +")
    if plus < 0:
        return 0
    index = plus + 2
    digits = ""
    while index < len(line) and line[index] >= "0" and line[index] <= "9":
        digits = digits + line[index]
        index = index + 1
    if digits == "":
        return 0
    return int(digits)


@js
def locate_review_target(lines: list[str], cursor_line: int) -> tuple[str, int]:
    if cursor_line < 1:
        return ("", 0)
    path = ""
    scan = cursor_line
    scan = min(scan, len(lines))
    while scan >= 1:
        header = parse_review_header(lines[scan - 1])
        if header != "":
            path = header
            break
        scan = scan - 1
    if path == "":
        return ("", 0)
    dest = 1
    index = scan + 1
    last = cursor_line
    last = min(last, len(lines))
    while index <= last:
        row = lines[index - 1]
        start = hunk_new_line(row)
        if start > 0:
            dest = start
        elif len(row) > 0 and (row[0] == " " or row[0] == "+"):
            if index == last:
                dest = max(dest, 1)
                return (path, dest)
            dest = dest + 1
        if index == last:
            dest = max(dest, 1)
            return (path, dest)
        index = index + 1
    dest = max(dest, 1)
    return (path, dest)


@js
def next_hunk_line(lines: list[str], cursor_line: int, reverse: bool) -> int:
    if reverse:
        scan = cursor_line - 1
        while scan >= 1:
            if hunk_new_line(lines[scan - 1]) > 0:
                return scan
            scan = scan - 1
        return 0
    scan = cursor_line + 1
    while scan <= len(lines):
        if hunk_new_line(lines[scan - 1]) > 0:
            return scan
        scan = scan + 1
    return 0


@js
def extract_hunk(lines: list[str], cursor_line: int) -> str:
    if cursor_line < 1 or cursor_line > len(lines):
        return ""
    start = cursor_line
    while start >= 1:
        row = lines[start - 1]
        if hunk_new_line(row) > 0 or parse_review_header(row) != "":
            break
        start = start - 1
    start = max(start, 1)
    if parse_review_header(lines[start - 1]) != "" and start < len(lines):
        start = start + 1
    end = cursor_line
    scan = cursor_line + 1
    while scan <= len(lines):
        row = lines[scan - 1]
        if hunk_new_line(row) > 0 or parse_review_header(row) != "":
            break
        end = scan
        scan = scan + 1
    parts: list[str] = []
    index = start
    while index <= end:
        parts.append(lines[index - 1])
        index = index + 1
    return "\n".join(parts)


@js
def next_review_header_line(lines: list[str], cursor_line: int, reverse: bool) -> int:
    if reverse:
        scan = cursor_line - 1
        while scan >= 1:
            if parse_review_header(lines[scan - 1]) != "":
                return scan
            scan = scan - 1
        return 0
    scan = cursor_line + 1
    while scan <= len(lines):
        if parse_review_header(lines[scan - 1]) != "":
            return scan
        scan = scan + 1
    return 0
