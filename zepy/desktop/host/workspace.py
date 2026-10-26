"""Desktop workspace construction and Git request handling."""
from pyjs import js
from pyjs.node.json import dumps
from pyjs.web.url import URL

from zepy.desktop.host.filesystem import NodeFileSystem
from zepy.services.workspace import WorkspaceService


@js
class Workspace(WorkspaceService):
    def __init__(self, root: str):
        super().__init__(root, NodeFileSystem())

    async def git(self, args: list[str]) -> str:
        try:
            return await self.filesystem.git(self.root, args)
        except Exception:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
            return ""

    async def status(self) -> dict[str, object]:
        raw = await self.git(["status", "--porcelain=v1", "-z"])
        names = raw.split("\0")
        changes: list[dict[str, object]] = []
        index = 0
        while index < len(names):
            name = names[index]
            index += 1
            if not name:
                continue
            code = name[:2]
            kind = "untracked" if code == "??" else "del" if "D" in code else "add" if "A" in code else "mod"
            changes.append({"path": name[3:], "git": kind, "plus": 0, "minus": 0})
            if "R" in code or "C" in code:
                index += 1
        return {"scope": "dirty", "tree": changes, "changes": changes, "plus": 0,
                "minus": 0, "stamp": raw}

    async def request(self, url: str, method: str = "", body: str = "") -> str:
        query = URL(url, "https://local.invalid")
        relative = query.searchParams.get("path") or ""
        if query.pathname == "/api/git-status":
            return dumps(await self.status())
        if query.pathname == "/api/git":
            return dumps({"path": relative, "gutter": [], "blame": []})
        raise ValueError("This service is not available in the desktop app yet")
