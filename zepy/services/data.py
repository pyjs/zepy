"""Validate values at the JSON boundary."""

from typing import cast

from pyjs import js


@js
def object_value(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return {}


@js
def array_value(value: object) -> list[object]:
    if isinstance(value, list):
        return cast(list[object], value)
    return []


@js
def text(value: object) -> str:
    return value if isinstance(value, str) else ""


@js
def integer(value: object) -> int:
    if isinstance(value, (int, float)) and value == int(value):
        return int(value)
    return 0


@js
def field(value: dict[str, object], key: str) -> str:
    return text(value.get(key))
