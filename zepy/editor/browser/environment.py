"""Browser services selected by the host backend."""

from pyjs import js
from pyjs.web.dom import Clipboard, Document, document, window
from pyjs.web.dom import navigator as dom_navigator
from pyjs.web.webgpu import GPU, navigator


@js
def get_device_pixel_ratio() -> float:
    return window.devicePixelRatio


@js
def get_gpu() -> GPU:
    return navigator.gpu


@js
def get_document() -> Document:
    return document


@js
def get_clipboard() -> Clipboard | None:
    return dom_navigator.clipboard
