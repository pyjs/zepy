"""Electron application host, compiled by PyJS during packaging."""
from pyjs import js
from pyjs.electron import (
    Event,
    HostContext,
    IpcEvent,
    Response,
    WebContents,
    WebPreferences,
    WindowOptions,
    handle,
)
from pyjs.node import (
    arguments,
    basename,
    bundle_directory,
    cwd,
    file_url,
    join,
    platform,
    realpath,
    stat,
)
from pyjs.node.json import dumps, loads

from zepy.desktop.host.codex import CodexChat
from zepy.desktop.host.debugger import PythonDebugger
from zepy.desktop.host.workspace import Workspace
from zepy.services.data import field, integer, object_value


@js
class DesktopHost:
    def __init__(self, context: HostContext, root: str):
        self.context = context
        self.workspace = Workspace(root)
        self.windows = set[WebContents]()
        self.chat = CodexChat(root)
        self.closing_chat = False
        self.debugger = PythonDebugger(context, self.workspace, self.windows)
        self.expected_url = file_url(context.renderer)
        self.controller = context.createWindow(WindowOptions(
            "Zepy — " + basename(root), WebPreferences(join(bundle_directory(), "preload.cjs")),
        ))

    async def close_chat(self) -> None:
        try:
            await self.chat.close()
        finally:
            self.context.app.quit()

    def before_quit(self, event: Event) -> None:
        if self.chat.child is not None:
            event.preventDefault()
            if not self.closing_chat:
                self.closing_chat = True
                self.close_chat()
        else:
            self.chat.close()

    def closed(self) -> None:
        if self.debugger.target is not None:
            self.debugger.target.destroy()
        self.context.app.quit()

    def validate_sender(self, event: IpcEvent) -> None:
        if (event.sender not in self.windows or event.senderFrame is not event.sender.mainFrame
                or event.senderFrame.url.split("?")[0] != self.expected_url):
            raise ValueError("Untrusted desktop request")

    async def workspace_request(self, event: IpcEvent, operation: str, raw_arguments: str) -> Response:
        self.validate_sender(event)
        try:
            result = await self.workspace.execute(operation, object_value(loads(raw_arguments)))
            return Response(200, dumps(result))
        except Exception as error:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
            return Response(400, dumps({"error": str(error)}))

    async def request(self, event: IpcEvent, url: str, raw_options: str) -> Response:
        self.validate_sender(event)
        try:
            if not isinstance(url, str) or not url.startswith("/api/"):
                raise ValueError("Invalid desktop request")
            options = object_value(loads(raw_options))
            method = field(options, "method")
            body = field(options, "body")
            if url.startswith("/api/debug/"):
                if event.sender is not self.controller.webContents:
                    raise ValueError("Debugger controls belong to the controller window")
                data = object_value(loads(body)) if body else {}
                result: dict[str, object] = {}
                if url == "/api/debug/state":
                    result = self.debugger.state()
                elif url == "/api/debug/start":
                    result = await self.debugger.start()
                elif url == "/api/debug/breakpoint":
                    result = await self.debugger.toggle(field(data, "path"), integer(data.get("line")))
                elif url == "/api/debug/action":
                    result = await self.debugger.action(field(data, "action"))
                else:
                    raise ValueError("Unknown debugger request")
                return Response(200, dumps(result))
            if url == "/api/chat":
                if method == "POST" and event.sender is not self.controller.webContents:
                    raise ValueError("Send Codex messages from the controller window")
                result = self.chat.send(object_value(loads(body))) if method == "POST" else self.chat.history()
                return Response(200, dumps(result))
            return Response(200, await self.workspace.request(url, method, body))
        except Exception as error:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
            return Response(400, dumps({"error": str(error), "text": str(error),
                                        "session_id": "", "queued": False, "idle": True}))

    async def start(self) -> None:
        self.context.app.on("before-quit", self.before_quit)
        await self.debugger.initialize()
        handle("zepy:request", self.request)
        handle("zepy:workspace", self.workspace_request)
        self.windows.add(self.controller.webContents)
        self.controller.on("closed", self.closed)
        await self.controller.loadFile(self.context.renderer)


@js
async def main(context: HostContext) -> None:
    context.app.setName("Zepy")
    if platform() == "linux":
        context.app.setDesktopName("zepy.desktop")
    root = cwd()
    for argument in arguments():
        if argument.startswith("--workspace="):
            root = argument[len("--workspace="):]
            break
    root = await realpath(root)
    if not (await stat(root)).isDirectory():
        raise ValueError("Workspace must be a directory")
    host = DesktopHost(context, root)
    await host.start()
