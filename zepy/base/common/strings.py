"""Strings."""

from pyjs import js


@js
def split_lines(value: str) -> list[str]:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.split("\n")


@js
def is_full_width_character(char_code: int) -> bool:
    if char_code >= 0x2E80 and char_code <= 0x9FFF:
        return True
    if char_code >= 0xAC00 and char_code <= 0xD7AF:
        return True
    if char_code >= 0xF900 and char_code <= 0xFAFF:
        return True
    return char_code >= 0xFF01 and char_code <= 0xFF60
