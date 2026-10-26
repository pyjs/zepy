"""Platform."""

from pyjs import js
from pyjs.web.dom import window


@js
def is_macintosh() -> bool:
    agent = window.navigator.userAgent
    return "Mac" in agent
