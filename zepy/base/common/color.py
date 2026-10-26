"""Color."""

from pyjs import js


@js
class Color:
    def __init__(self, red: float, green: float, blue: float, alpha: float = 1.0):
        self.red = red
        self.green = green
        self.blue = blue
        self.alpha = alpha


@js
def parse_hex_color(value: str) -> Color | None:
    if len(value) == 7 and value[0] == "#":
        red = int(value[1:3], 16)
        green = int(value[3:5], 16)
        blue = int(value[5:7], 16)
        return Color(red / 255.0, green / 255.0, blue / 255.0, 1.0)
    if len(value) == 4 and value[0] == "#":
        red = int(value[1] + value[1], 16)
        green = int(value[2] + value[2], 16)
        blue = int(value[3] + value[3], 16)
        return Color(red / 255.0, green / 255.0, blue / 255.0, 1.0)
    return None
