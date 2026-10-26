"""Gpu utils."""

from pyjs import js
from pyjs.javascript import Float32Array

from zepy.base.common.errors import BugIndicatingError
from zepy.editor.browser.environment import get_device_pixel_ratio


@js
def quad_vertices() -> Float32Array:
    return Float32Array([1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0])


@js
def device_pixel_ratio() -> float:
    ratio = get_device_pixel_ratio()
    if ratio < 1.0:
        return 1.0
    return ratio


@js
def ensure_non_nullable(value: object) -> object:
    if value is None:
        raise BugIndicatingError("Value cannot be null")
    return value
