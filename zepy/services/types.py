"""JSON records exchanged by workspace transports."""

from pyjs.javascript import JSONObject


class FileEntry(JSONObject):
    name: str
    path: str
    kind: str
    depth: int
    content: str | None
    git: str


class FilePayload(JSONObject):
    path: str
    content: str
    mtime: float


class SearchHit(JSONObject):
    path: str
    line: int
    text: str


class WorkspaceArguments(JSONObject):
    path: str
    content: str
    revision: str
    query: str
