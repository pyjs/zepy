"""Host tests execute compiled Python in Node, with real files and processes."""
from collections.abc import Callable
from typing import cast

import pytest
from pyjs import js
from pyjs.electron import BrowserWindow, HostContext, WebContents, WindowOptions
from pyjs.node import (
    join,
    mkdir,
    mkdtemp,
    read_text,
    remove_tree,
    symlink,
    temp_directory,
    write_text,
)

from zepy.desktop.host.debugger import PythonDebugger
from zepy.desktop.host.sourcemap import PythonSourceMap
from zepy.desktop.host.workspace import Workspace
from zepy.services.data import array_value, field, object_value

pytestmark = pytest.mark.pyjs_node


@js
async def test_workspace_reads_saves_and_rejects_escaping_paths():
    directory = await mkdtemp(join(temp_directory(), "desktop-host-"))
    try:
        root = join(directory, "project")
        await mkdir(join(root, "src"))
        await mkdir(join(root, "external"))
        await write_text(join(root, "src/example.py"), 'print("🐍")\n')
        await write_text(join(root, "external/ignore.txt"), "ignored")
        await write_text(join(directory, "outside.txt"), "private")
        await symlink(join(directory, "outside.txt"), join(root, "escape.txt"))
        workspace = Workspace(root)
        entries = await workspace.tree()
        assert [field(entry, "path") for entry in entries] == ["src", "src/example.py"]
        assert entries[1]["content"] is None
        assert (await workspace.file("src/example.py"))["content"] == 'print("🐍")\n'
        await workspace.save("src/example.py", "updated\r\n")
        assert await read_text(join(root, "src/example.py")) == "updated\n"
        for name in ["../outside.txt", "escape.txt", join(directory, "outside.txt")]:
            rejected = False
            try:
                await workspace.file(name)
            except Exception:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
                rejected = True
            assert rejected
            rejected = False
            try:
                await workspace.save(name, "changed")
            except Exception:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
                rejected = True
            assert rejected
        assert await read_text(join(directory, "outside.txt")) == "private"
        await write_text(join(root, "binary.bin"), "\0\x01\x02")
        rejected = False
        try:
            await workspace.file("binary.bin")
        except Exception as error:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
            rejected = "Binary" in str(error)
        assert rejected
        result = array_value(await workspace.execute("search", {"query": "updated"}))
        assert field(object_value(result[0]), "path") == "src/example.py"
        rejected = False
        try:
            await workspace.request("/api/not-a-service")
        except Exception:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
            rejected = True
        assert rejected
    finally:
        await remove_tree(directory)


@js
def test_source_map_signed_deltas_and_unmapped_ranges():
    data: dict[str, object] = {"sources": ["example.py"], "sourcesContent": ["a\nb\n"],
                               "mappings": "AAAA,KACC,C;AACD;AADG"}
    source_map = PythonSourceMap(data)
    first = source_map.original(0, 0)
    assert first is not None
    assert first.original_line == 0
    second = source_map.original(0, 5)
    assert second is not None
    assert second.original_column == 1
    assert source_map.original(0, 6) is None
    third = source_map.original(1, 0)
    assert third is not None
    assert third.original_line == 2
    fourth = source_map.original(2, 0)
    assert fourth is not None
    assert fourth.original_line == 1
    assert fourth.original_column == 3
    assert source_map.generated("example.py", 1)[0].original_line == 1
    rejected = False
    try:
        source_map.generated("other.py", 0)
    except Exception as error:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
        rejected = "No executable" in str(error)
    assert rejected


@js
def nothing() -> None:
    pass


@js.dictionary
class DebugAPI:
    def __init__(self, attach: Callable[[str], None]):
        self.attach = attach


@js.dictionary
class ContentsAPI:
    def __init__(self, debugger: DebugAPI):
        self.debugger = debugger


@js.dictionary
class WindowAPI:
    def __init__(self, webContents: ContentsAPI, isDestroyed: Callable[[], bool],
                 destroy: Callable[[], None], on: Callable[[str, Callable[[], None]], None]):
        self.webContents = webContents
        self.isDestroyed = isDestroyed
        self.destroy = destroy
        self.on = on


@js.dictionary
class ContextAPI:
    def __init__(self, createWindow: Callable[[WindowOptions], BrowserWindow]):
        self.createWindow = createWindow


@js
class FakeWindow:
    def __init__(self):
        self.destroyed = False
        self.closed = nothing
        self.api = WindowAPI(ContentsAPI(DebugAPI(self.attach)), self.is_destroyed, self.destroy, self.on)

    def attach(self, version: str) -> None:
        raise ValueError("cannot attach")

    def is_destroyed(self) -> bool:
        return self.destroyed

    def on(self, event: str, callback: Callable[[], None]) -> None:
        self.closed = callback

    def destroy(self) -> None:
        self.destroyed = True
        self.closed()

    def create(self, options: WindowOptions) -> BrowserWindow:
        return cast(BrowserWindow, self.api)


@js
async def test_failed_debugger_startup_cleans_window_and_state():
    window = FakeWindow()
    context = ContextAPI(window.create)
    windows = set[WebContents]()
    debugger = PythonDebugger(cast(HostContext, context), Workspace(""), windows)
    rejected = False
    failure = ""
    try:
        await debugger.start()
    except Exception as error:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
        failure = str(error)
        rejected = "cannot attach" in failure
    assert rejected, failure
    assert window.destroyed
    assert len(windows) == 0
    assert debugger.state()["running"] is False


@js
async def test_debugger_stop_ignores_late_detach():
    window = FakeWindow()
    context = ContextAPI(window.create)
    windows = set[WebContents]()
    debugger = PythonDebugger(cast(HostContext, context), Workspace(""), windows)
    debugger.target = cast(BrowserWindow, window.api)
    contents = cast(WebContents, window.api.webContents)
    debugger.target_contents = contents
    windows.add(contents)
    debugger.detached("unexpected")
    assert debugger.state()["error"] == "Debugger detached: unexpected"
    await debugger.action("stop")
    debugger.detached("target closed")
    assert window.destroyed
    assert len(windows) == 0
    assert debugger.state()["running"] is False
    assert debugger.state()["error"] == ""
