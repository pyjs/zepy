"""HTTP transport used when the workbench runs in a browser."""

from pyjs import js
from pyjs.javascript import JSON, encodeURIComponent
from pyjs.web.network import Response, fetch

from zepy.services.types import WorkspaceArguments


@js
async def http_workspace_request(operation: str, arguments: WorkspaceArguments) -> Response:
    if operation == "tree":
        return await fetch("/api/tree")
    if operation == "search":
        return await fetch("/api/search?q=" + encodeURIComponent(arguments["query"]))
    if operation == "read":
        return await fetch(
            "/api/file?path="
            + encodeURIComponent(arguments["path"])
            + "&rev="
            + encodeURIComponent(arguments["revision"])
        )
    if operation == "write":
        return await fetch(
            "/api/file",
            {
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": JSON.stringify(arguments),
            },
        )
    raise ValueError("Unknown workspace operation")
