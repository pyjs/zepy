"""Source Map v3 decoder; coordinates are zero-based until displayed."""
from pyjs import js

from zepy.services.data import array_value, field, text


@js
def decode(segment: str) -> list[int]:
    values: list[int] = []
    value = 0
    shift = 0
    for character in segment:
        digit = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/".find(character)
        if digit < 0:
            raise ValueError("Invalid source map digit")
        value += (digit & 31) * 2 ** shift
        if digit & 32:
            shift += 5
            continue
        values.append(-(value // 2) if value & 1 else value // 2)
        value = 0
        shift = 0
    if shift:
        raise ValueError("Truncated source map")
    return values


@js
class Position:
    def __init__(self, generated_line: int, generated_column: int, source: str,
                 original_line: int = 0, original_column: int = 0):
        self.generated_line = generated_line
        self.generated_column = generated_column
        self.source = source
        self.original_line = original_line
        self.original_column = original_column


@js
class PythonSourceMap:
    def __init__(self, data: dict[str, object]):
        self.sources = [text(value) for value in array_value(data.get("sources"))]
        self.contents = [text(value) for value in array_value(data.get("sourcesContent"))]
        self.entries: list[Position] = []
        source = 0
        original_line = 0
        original_column = 0
        for generated_line, line in enumerate(field(data, "mappings").split(";")):
            generated_column = 0
            for segment in line.split(","):
                if not segment:
                    continue
                fields = decode(segment)
                generated_column += fields[0]
                if len(fields) < 4:
                    self.entries.append(Position(generated_line, generated_column, ""))
                    continue
                source += fields[1]
                original_line += fields[2]
                original_column += fields[3]
                self.entries.append(Position(generated_line, generated_column, self.sources[source],
                                             original_line, original_column))

    def original(self, line: int, column: int) -> Position | None:
        found: Position | None = None
        for entry in self.entries:
            if entry.generated_line > line or (entry.generated_line == line and entry.generated_column > column):
                break
            if entry.generated_line == line:
                found = entry
        if found is not None and found.source:
            return found
        return None

    def generated(self, source: str, line: int) -> list[Position]:
        candidates = [entry for entry in self.entries
                      if entry.source == source and line <= entry.original_line <= line + 4]
        if not candidates:
            raise ValueError("No executable Python statement on this line or the next four lines")
        next_line = min(entry.original_line for entry in candidates)
        return [entry for entry in candidates if entry.original_line == next_line]
