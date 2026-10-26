"""Renderer capabilities exposed through fixed, validated IPC channels."""
from collections.abc import Awaitable, Callable

from pyjs import js
from pyjs.electron import Response, expose, invoke


@js
async def request(url: str, options: object) -> Response:
    return await invoke("zepy:request", url, options)


@js
async def workspace(operation: str, arguments: object) -> Response:
    return await invoke("zepy:workspace", operation, arguments)


@js.dictionary
class DesktopAPI:
    def __init__(self, request: Callable[[str, object], Awaitable[Response]],
                 workspace: Callable[[str, object], Awaitable[Response]]):
        self.request = request
        self.workspace = workspace


@js
def main() -> None:
    expose("zepyDesktop", DesktopAPI(request, workspace))
