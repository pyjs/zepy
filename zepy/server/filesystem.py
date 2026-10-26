"""Python filesystem adapter for the shared workspace service."""

import asyncio
import os
import subprocess
from pathlib import Path

from pyjs import nojs

from zepy.services.workspace import Entry, FileSystem, Metadata


@nojs
class PythonFileSystem(FileSystem):
    def join(self, parent: str, child: str) -> str:
        return os.path.join(parent, child)

    def is_absolute(self, path: str) -> bool:
        return os.path.isabs(path)

    def separator(self) -> str:
        return os.sep

    def byte_length(self, text: str) -> int:
        return len(text.encode("utf-8"))

    async def canonical(self, path: str) -> str:
        return str(await asyncio.to_thread(Path(path).resolve, strict=True))

    async def stat(self, path: str) -> Metadata:
        def inspect():
            item = Path(path)
            info = item.stat()
            return Metadata(info.st_size, info.st_mtime_ns / 1_000_000, item.is_file())

        return await asyncio.to_thread(inspect)

    async def entries(self, path: str) -> list[Entry]:
        def inspect():
            with os.scandir(path) as entries:
                return [
                    Entry(entry.name, entry.is_dir(follow_symlinks=False))
                    for entry in entries
                    if entry.is_dir(follow_symlinks=False) or entry.is_file(follow_symlinks=False)
                ]

        return await asyncio.to_thread(inspect)

    async def read(self, path: str) -> str:
        return await asyncio.to_thread(
            Path(path).read_text, encoding="utf-8", errors="replace", newline=""
        )

    async def write(self, path: str, content: str) -> None:
        await asyncio.to_thread(Path(path).write_text, content, encoding="utf-8", newline="\n")

    async def git(self, root: str, arguments: list[str]) -> str:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", root, *arguments],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=10,
        )
        return result.stdout
