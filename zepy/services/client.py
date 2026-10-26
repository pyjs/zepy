"""Typed workspace operations for the workbench."""

from pyjs import js
from pyjs.javascript import JSON
from pyjs.web.network import Response

from zepy.desktop.api import is_desktop, workspace_request
from zepy.services.http import http_workspace_request
from zepy.services.types import FileEntry, FilePayload, SearchHit, WorkspaceArguments


@js
async def request(operation: str, arguments: WorkspaceArguments) -> Response:
    # Choose at request time: server-rendered state is also used by Electron.
    if is_desktop():
        return await workspace_request(operation, arguments)
    return await http_workspace_request(operation, arguments)


@js
async def workspace_tree() -> list[FileEntry] | None:
    response = await request("tree", WorkspaceArguments())
    if not response.ok:
        return None
    result: list[FileEntry] = JSON.parse(await response.text())
    return result


@js
async def read_file(path: str, revision: str = "") -> FilePayload | None:
    response = await request("read", WorkspaceArguments(path=path, revision=revision))
    if not response.ok:
        return None
    result: FilePayload = JSON.parse(await response.text())
    return result


@js
async def write_file(path: str, content: str) -> FilePayload | None:
    response = await request("write", WorkspaceArguments(path=path, content=content))
    if not response.ok:
        return None
    result: FilePayload = JSON.parse(await response.text())
    return result


@js
async def search_files(query: str) -> list[SearchHit] | None:
    response = await request("search", WorkspaceArguments(query=query))
    if not response.ok:
        return None
    result: list[SearchHit] = JSON.parse(await response.text())
    return result
