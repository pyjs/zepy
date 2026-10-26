"""Workspace behavior shared by the desktop host and browser server."""

from pyjs import JS, js

from zepy.services.data import field

MAX_FILE_BYTES: JS[int] = 8 * 1024 * 1024
MAX_DEPTH: JS[int] = 12
MAX_SEARCH_RESULTS: JS[int] = 100
IGNORE_NAMES: JS[list[str]] = [
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    ".codex",
    ".pyjs",
    ".zepy",
    "external",
    ".local",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".build",
]


@js
class Entry:
    def __init__(self, name: str, directory: bool):
        self.name = name
        self.directory = directory


@js
class Metadata:
    def __init__(self, size: int, mtime: float, file: bool):
        self.size = size
        self.mtime = mtime
        self.file = file


@js
class FileSystem:
    """Runtime operations required by WorkspaceService; implementations own OS access."""

    def join(self, parent: str, child: str) -> str:
        raise NotImplementedError()

    def is_absolute(self, path: str) -> bool:
        raise NotImplementedError()

    def separator(self) -> str:
        raise NotImplementedError()

    def byte_length(self, text: str) -> int:
        raise NotImplementedError()

    async def canonical(self, path: str) -> str:
        raise NotImplementedError()

    async def stat(self, path: str) -> Metadata:
        raise NotImplementedError()

    async def entries(self, path: str) -> list[Entry]:
        raise NotImplementedError()

    async def read(self, path: str) -> str:
        raise NotImplementedError()

    async def write(self, path: str, content: str) -> None:
        raise NotImplementedError()

    async def git(self, root: str, arguments: list[str]) -> str:
        raise NotImplementedError()


@js
def ignored_name(name: str) -> bool:
    return name in IGNORE_NAMES or name.endswith((".egg-info", ".pyc"))


@js
def entry_order(entry: Entry) -> tuple[int, str]:
    return (0 if entry.directory else 1, entry.name.lower())


@js
class WorkspaceService:
    def __init__(self, root: str, filesystem: FileSystem):
        self.root = root
        self.filesystem = filesystem

    def validate_relative(self, relative: str) -> None:
        if self.filesystem.is_absolute(relative) or ".." in relative.replace("\\", "/").split("/"):
            raise ValueError("Path must be relative to the workspace")

    async def safe(self, relative: str) -> str:
        self.validate_relative(relative)
        fs = self.filesystem
        resolved = await fs.canonical(fs.join(self.root, relative))
        prefix = self.root.rstrip("/\\") + fs.separator()
        if resolved != self.root and not resolved.startswith(prefix):
            raise ValueError("Path escapes the workspace")
        return resolved

    async def walk(
        self, directory: str, prefix: str, depth: int, result: list[dict[str, object]]
    ) -> None:
        children = [
            entry
            for entry in await self.filesystem.entries(directory)
            if not ignored_name(entry.name)
        ]
        children.sort(key=entry_order)
        for entry in children:
            relative = prefix + entry.name
            result.append(
                {
                    "name": entry.name,
                    "path": relative,
                    "kind": "dir" if entry.directory else "file",
                    "depth": depth,
                    "content": None,
                    "git": "",
                }
            )
            if entry.directory and depth < MAX_DEPTH:
                await self.walk(
                    self.filesystem.join(directory, entry.name), relative + "/", depth + 1, result
                )

    async def tree(self) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        await self.walk(self.root, "", 0, result)
        return result

    async def file(self, relative: str, revision: str = "") -> dict[str, object]:
        mtime = 0.0
        if revision:
            self.validate_relative(relative)
            content = await self.filesystem.git(self.root, ["show", revision + ":./" + relative])
        else:
            path = await self.safe(relative)
            info = await self.filesystem.stat(path)
            if not info.file:
                raise ValueError("Not a file")
            if info.size > MAX_FILE_BYTES:
                raise ValueError("File exceeds the 8 MiB editor limit")
            content = await self.filesystem.read(path)
            mtime = info.mtime
        if self.filesystem.byte_length(content) > MAX_FILE_BYTES:
            raise ValueError("File exceeds the 8 MiB editor limit")
        if "\0" in content:
            raise ValueError("Binary files cannot be opened as source")
        return {
            "path": "head:" + relative if revision else relative,
            "content": content,
            "mtime": mtime,
        }

    async def save(self, relative: str, content: str) -> dict[str, object]:
        if self.filesystem.byte_length(content) > MAX_FILE_BYTES:
            raise ValueError("File exceeds the 8 MiB editor limit")
        if "\0" in content:
            raise ValueError("Binary files cannot be saved as source")
        path = await self.safe(relative)
        if not (await self.filesystem.stat(path)).file:
            raise ValueError("Not a file")
        await self.filesystem.write(path, content.replace("\r\n", "\n").replace("\r", "\n"))
        return await self.file(relative)

    async def search(self, query: str) -> list[dict[str, object]]:
        hits: list[dict[str, object]] = []
        if not query:
            return hits
        needle = query.lower()
        for entry in await self.tree():
            if entry.get("kind") != "file":
                continue
            relative = field(entry, "path")
            try:
                content = field(await self.file(relative), "content")
            except Exception:  # noqa: BLE001, S112 -- Unreadable or binary files are not searchable.
                continue
            for index, line in enumerate(content.split("\n")):
                if needle in line.lower():
                    hits.append({"path": relative, "line": index + 1, "text": line[:160]})
                    if len(hits) >= MAX_SEARCH_RESULTS:
                        return hits
        return hits

    async def execute(self, operation: str, arguments: dict[str, object]) -> object:
        if operation == "tree":
            return await self.tree()
        if operation == "search":
            return await self.search(field(arguments, "query"))
        if operation in ("read", "write"):
            if not isinstance(arguments.get("path"), str):
                raise ValueError("Path must be a string")
            path = field(arguments, "path")
            if operation == "read":
                return await self.file(path, field(arguments, "revision"))
            if not isinstance(arguments.get("content"), str):
                raise ValueError("Content must be a string")
            return await self.save(path, field(arguments, "content"))
        raise ValueError("Unknown workspace operation")
