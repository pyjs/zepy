"""Node filesystem adapter for the shared workspace service."""

from pyjs import js
from pyjs.node import (
    byte_length,
    execute,
    is_absolute,
    join,
    read_text,
    readdir,
    realpath,
    separator,
    stat,
    write_text,
)

from zepy.services.workspace import Entry, FileSystem, Metadata


@js
class NodeFileSystem(FileSystem):
    def join(self, parent: str, child: str) -> str:
        return join(parent, child)

    def is_absolute(self, path: str) -> bool:
        return is_absolute(path)

    def separator(self) -> str:
        return separator()

    def byte_length(self, text: str) -> int:
        return byte_length(text)

    async def canonical(self, path: str) -> str:
        return await realpath(path)

    async def stat(self, path: str) -> Metadata:
        info = await stat(path)
        return Metadata(info.size, info.mtimeMs, info.isFile())

    async def entries(self, path: str) -> list[Entry]:
        return [
            Entry(entry.name, entry.isDirectory())
            for entry in await readdir(path)
            if entry.isDirectory() or entry.isFile()
        ]

    async def read(self, path: str) -> str:
        return await read_text(path)

    async def write(self, path: str, content: str) -> None:
        await write_text(path, content)

    async def git(self, root: str, arguments: list[str]) -> str:
        return await execute("git", ["-C", root] + arguments, root, 8 * 1024 * 1024, 10000)
