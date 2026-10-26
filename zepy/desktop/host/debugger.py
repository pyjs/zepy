"""Python source-map debugging over Electron's DevTools transport."""
from pyjs import js
from pyjs.electron import (
    BrowserWindow,
    HostContext,
    WebContents,
    WebPreferences,
    WindowOptions,
    load_debug_target,
    on_debug_detach,
    on_debug_message,
    send_command,
)
from pyjs.node import (
    bundle_directory,
    catch_task,
    file_url,
    is_absolute,
    join,
    now,
    read_text,
    relative,
    resolve,
)
from pyjs.node.json import dumps, loads

from zepy.desktop.host.sourcemap import PythonSourceMap
from zepy.desktop.host.workspace import Workspace
from zepy.services.data import array_value, field, integer, object_value


@js
class Breakpoint:
    def __init__(self, path: str, line: int, resolved: int):
        self.path = path
        self.line = line
        self.resolved = resolved
        self.ids: list[str] = []


@js
class PythonDebugger:
    def __init__(self, context: HostContext, workspace: Workspace, windows: set[WebContents]):
        self.context = context
        self.workspace = workspace
        self.windows = windows
        self.target: BrowserWindow | None = None
        self.target_contents: WebContents | None = None
        self.breakpoints: list[Breakpoint] = []
        self.frames: list[dict[str, object]] = []
        self.variables: list[dict[str, str]] = []
        self.paused = False
        self.revision = 0
        self.error = ""
        self.generation = 0
        self.pause_version = 0
        self.script = ""
        self.script_url = ""
        self.script_ids = set[str]()
        self.source_map = PythonSourceMap({"sources": [], "sourcesContent": [], "mappings": ""})

    async def initialize(self) -> None:
        self.script = self.context.renderer[:-5] + ".js"
        self.script_url = file_url(self.script)
        self.source_map = PythonSourceMap(object_value(loads(await read_text(self.script + ".map"))))

    def state(self) -> dict[str, object]:
        breakpoints: list[dict[str, object]] = []
        for point in self.breakpoints:
            breakpoints.append({"path": point.path, "line": point.line, "resolved": point.resolved})
        return {"running": self.target is not None, "paused": self.paused,
                "frames": self.frames, "variables": self.variables, "breakpoints": breakpoints,
                "revision": self.revision, "error": self.error}

    async def command(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        target = self.target
        if target is None or target.isDestroyed():
            raise ValueError("Start a debug session first")
        result = await send_command(target.webContents.debugger, method, dumps(params or {}))
        return object_value(loads(result))

    def source_path(self, source: str) -> str:
        return resolve(source if is_absolute(source) else join(self.workspace.root, source))

    def source(self, path: str) -> str:
        for source in self.source_map.sources:
            if self.source_path(source) == join(self.workspace.root, path):
                return source
        raise ValueError("This file is not part of the compiled renderer")

    async def check_source(self, source: str) -> None:
        original = self.source_map.contents[self.source_map.sources.index(source)]
        if await read_text(self.source_path(source)) != original:
            raise ValueError("Python source changed since this app was built. Rebuild and restart before debugging.")

    async def bind(self, point: Breakpoint) -> None:
        point.ids = []
        source = self.source(point.path)
        await self.check_source(source)
        positions = self.source_map.generated(source, point.line - 1)
        for position in positions:
            result = await self.command("Debugger.setBreakpointByUrl", {
                "url": self.script_url, "lineNumber": position.generated_line,
                "columnNumber": position.generated_column,
            })
            point.ids.append(field(result, "breakpointId"))
        point.resolved = positions[0].original_line + 1

    async def toggle(self, path: str, line: int) -> dict[str, object]:
        if line < 1:
            raise ValueError("Breakpoint line must be a positive integer")
        await self.workspace.safe(path)
        existing: Breakpoint | None = None
        for point in self.breakpoints:
            if point.path == path and point.line == line:
                existing = point
                break
        if existing is not None:
            if self.target is not None:
                for identifier in existing.ids:
                    await self.command("Debugger.removeBreakpoint", {"breakpointId": identifier})
            self.breakpoints = [point for point in self.breakpoints if point is not existing]
        else:
            source = self.source(path)
            await self.check_source(source)
            position = self.source_map.generated(source, line - 1)[0]
            point = Breakpoint(path, line, position.original_line + 1)
            if self.target is not None:
                await self.bind(point)
            self.breakpoints.append(point)
        self.revision += 1
        return self.state()

    async def on_paused(self, params: dict[str, object]) -> None:
        generation = self.generation
        self.pause_version += 1
        pause_version = self.pause_version
        self.paused = True
        self.frames = []
        self.variables = []
        self.revision += 1
        call_frames = array_value(params.get("callFrames"))
        for value in call_frames:
            frame = object_value(value)
            location = object_value(frame.get("location"))
            original = self.source_map.original(integer(location.get("lineNumber")), integer(location.get("columnNumber")))
            own = field(location, "scriptId") in self.script_ids
            path = ""
            line = 0
            if own and original is not None:
                path = relative(self.workspace.root, self.source_path(original.source)).replace("\\", "/")
                line = original.original_line + 1
            self.frames.append({"name": field(frame, "functionName") or "(anonymous)", "path": path, "line": line})
        if call_frames:
            top = object_value(call_frames[0])
            receiver = object_value(top.get("this"))
            self.variables.append({"name": "self", "value": field(receiver, "description") or field(receiver, "type")})
            for value in array_value(top.get("scopeChain")):
                scope = object_value(value)
                if field(scope, "type") != "local":
                    continue
                properties = await self.command("Runtime.getProperties", {
                    "objectId": field(object_value(scope.get("object")), "objectId"), "ownProperties": True,
                })
                if generation != self.generation or pause_version != self.pause_version or not self.paused:
                    return
                for item in array_value(properties.get("result")):
                    prop = object_value(item)
                    if prop.get("value") is None:
                        continue
                    remote = object_value(prop.get("value"))
                    display = remote.get("value")
                    if display is None:
                        display = remote.get("unserializableValue")
                    if display is None:
                        display = remote.get("description")
                    if display is None:
                        display = remote.get("type")
                    self.variables.append({"name": field(prop, "name"), "value": str(display)[:1000]})
        self.revision += 1

    def failed(self, error: Exception) -> None:
        self.error = str(error)
        self.revision += 1

    def message(self, method: str, raw: str) -> None:
        params = object_value(loads(raw))
        if method == "Debugger.scriptParsed" and field(params, "url") == self.script_url:
            self.script_ids.add(field(params, "scriptId"))
        if method == "Debugger.paused":
            catch_task(self.on_paused(params), self.failed)
        if method == "Debugger.resumed":
            self.paused = False
            self.frames = []
            self.variables = []
            self.revision += 1

    def detached(self, reason: str) -> None:
        self.paused = False
        self.error = "Debugger detached: " + reason
        self.revision += 1

    def closed(self) -> None:
        contents = self.target_contents
        if contents is not None:
            self.windows.discard(contents)
        self.target_contents = None
        self.target = None
        self.paused = False
        self.frames = []
        self.variables = []
        self.error = ""
        self.revision += 1
        self.generation += 1

    async def load(self, window: BrowserWindow) -> None:
        try:
            await load_debug_target(window, self.context.renderer)
        except Exception as error:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
            if self.target is window:
                self.failed(error)

    async def start(self) -> dict[str, object]:
        if self.target is not None:
            return self.state()
        window = self.context.createWindow(WindowOptions(
            "Zepy — debug target", WebPreferences(join(bundle_directory(), "preload.cjs"), "zepy-debug-" + str(now())),
            width=1100, height=800,
        ))
        self.target = window
        self.target_contents = window.webContents
        self.windows.add(window.webContents)
        self.script_ids = set[str]()
        self.error = ""
        self.generation += 1
        window.on("closed", self.closed)
        debugger = window.webContents.debugger
        try:
            debugger.attach("1.3")
            on_debug_message(debugger, self.message)
            on_debug_detach(debugger, self.detached)
            await window.loadURL("about:blank")
            await self.command("Debugger.enable")
            for point in self.breakpoints:
                await self.bind(point)
            self.load(window)
            self.revision += 1
            return self.state()
        except Exception:
            if not window.isDestroyed():
                window.destroy()
            raise

    async def action(self, action: str) -> dict[str, object]:
        commands = {"continue": "Debugger.resume", "stepOver": "Debugger.stepOver",
                    "stepInto": "Debugger.stepInto", "stepOut": "Debugger.stepOut", "pause": "Debugger.pause"}
        if action == "stop":
            if self.target is not None:
                self.target.destroy()
            return self.state()
        if action not in commands:
            raise ValueError("Unknown debugger action")
        await self.command(commands[action])
        return self.state()
