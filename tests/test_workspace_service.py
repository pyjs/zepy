"""One workspace contract exercised against Python and compiled Node adapters."""

import asyncio
import os
import tempfile

import pytest
from pyjs import js
from pyjs.node import join, mkdir, mkdtemp, remove_tree, symlink, temp_directory, write_text

from zepy.desktop.host.filesystem import NodeFileSystem
from zepy.services.data import array_value, field, integer, object_value
from zepy.services.workspace import MAX_FILE_BYTES, WorkspaceService


@js
async def workspace_contract(service: WorkspaceService) -> None:
    fs = service.filesystem
    path = fs.join(service.root, "example.py")
    await fs.write(path, 'print("🐍")\r\n')
    tree = await service.tree()
    assert [field(entry, "path") for entry in tree] == ["example.py"]
    assert tree[0]["content"] is None
    loaded = await service.file("example.py")
    assert loaded["content"] == 'print("🐍")\r\n'
    saved = object_value(
        await service.execute("write", {"path": "example.py", "content": "a\r\nb\rc\n"})
    )
    assert saved["content"] == "a\nb\nc\n"
    assert await fs.read(path) == "a\nb\nc\n"
    await fs.write(path, "match " + "x" * 200 + "\n" + "MATCH\n" * 110)
    hits = array_value(await service.execute("search", {"query": "match"}))
    assert len(hits) == 100
    assert len(field(object_value(hits[0]), "text")) == 160
    assert integer(object_value(hits[1])["line"]) == 2
    assert await service.search("") == []
    # Byte limits must count UTF-8 bytes rather than Python or JavaScript characters.
    await service.save("example.py", "🐍" * 30000)
    assert (await service.file("example.py"))["content"] == "🐍" * 30000
    for arguments in [
        {"path": "example.py", "content": "🐍" * (MAX_FILE_BYTES // 4 + 1)},
        {"path": "example.py", "content": 42},
        {"path": 42, "content": "bad"},
        {"path": "../outside.txt", "content": "bad"},
        {"path": "escape.txt", "content": "bad"},
        {"path": "example.py", "content": "\0binary"},
    ]:
        rejected = False
        try:
            await service.execute("write", arguments)
        except Exception:  # noqa: BLE001 -- Node filesystem errors are JavaScript errors.
            rejected = True
        assert rejected
        assert await fs.read(path) == "🐍" * 30000
    for name in ["../outside.txt", "escape.txt", fs.join(service.root, "example.py")]:
        rejected = False
        try:
            await service.file(name)
        except Exception:  # noqa: BLE001 -- Node filesystem errors are JavaScript errors.
            rejected = True
        assert rejected
    for content in ["\0binary", "x" * (MAX_FILE_BYTES + 1)]:
        await fs.write(path, content)
        rejected = False
        try:
            await service.file("example.py")
        except Exception:  # noqa: BLE001 -- Node filesystem errors are JavaScript errors.
            rejected = True
        assert rejected
        assert await service.search("binary") == []
    rejected = False
    try:
        await service.execute("unknown", {})
    except Exception:  # noqa: BLE001 -- Node filesystem errors are JavaScript errors.
        rejected = True
    assert rejected


@pytest.mark.pyjs_python
def test_python_workspace_contract():
    from zepy.server.filesystem import PythonFileSystem

    with tempfile.TemporaryDirectory() as directory:
        root = os.path.join(directory, "project")
        os.mkdir(root)
        os.mkdir(os.path.join(root, "external"))
        outside = os.path.join(directory, "outside.txt")
        with open(outside, "w") as file:
            file.write("private")
        os.symlink(outside, os.path.join(root, "escape.txt"))
        asyncio.run(workspace_contract(WorkspaceService(root, PythonFileSystem())))
        with open(outside) as file:
            assert file.read() == "private"


@pytest.mark.pyjs_node
@js
async def test_node_workspace_contract():
    directory = await mkdtemp(join(temp_directory(), "workspace-contract-"))
    try:
        root = join(directory, "project")
        await mkdir(root)
        await mkdir(join(root, "external"))
        await write_text(join(directory, "outside.txt"), "private")
        await symlink(join(directory, "outside.txt"), join(root, "escape.txt"))
        await workspace_contract(WorkspaceService(root, NodeFileSystem()))
    finally:
        await remove_tree(directory)
