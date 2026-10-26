"""Shared browser/desktop chat service; the Codex CLI owns authentication."""
from pyjs import js
from pyjs.node import (
    ChildProcess,
    LineReader,
    Timer,
    arguments,
    clear_timeout,
    close_descriptor,
    dirname,
    environment,
    error_code,
    executable,
    home_directory,
    join,
    kill,
    mkdir_sync,
    on_close,
    on_error,
    on_signal,
    on_stderr,
    on_stdout_size,
    open_exclusive,
    platform,
    process_id,
    read_lines,
    read_stdin_lines,
    read_text_sync,
    realpath_sync,
    remove_environment,
    rename_sync,
    send_stdin,
    set_environment,
    set_timeout,
    sha256,
    spawn,
    stat_sync,
    unlink_sync,
    wait_closed,
    write_descriptor,
    write_stdout,
    write_text_sync,
)
from pyjs.node.json import dumps, loads

from zepy.services.data import array_value, field, integer, object_value


@js
def state_path(root: str, home: str = "") -> str:
    if not home:
        home = environment("CODEX_HOME") or join(home_directory(), ".codex")
    return join(join(home, "zepy"), sha256(realpath_sync(root)) + ".json")


@js
def build_prompt(body: dict[str, object]) -> str:
    message = field(body, "text").strip()
    selection = field(body, "selection").strip()
    where = field(body, "path")
    line = integer(body.get("line"))
    end_line = integer(body.get("end_line"))
    if line > 0:
        where += ":" + str(line)
        if end_line > line:
            where += "-" + str(end_line)
    prompt = message
    if selection:
        excerpt = "Selected " + where + ":\n" + selection
        prompt = message + "\n\n" + excerpt if message else excerpt
    if not prompt:
        raise ValueError("Empty prompt")
    if len(prompt) > 100000:
        raise ValueError("Chat prompt exceeds 100,000 characters")
    return prompt


@js
def lock_alive(filename: str) -> bool:
    try:
        lock = object_value(loads(read_text_sync(filename)))
        for value in [lock.get("owner"), lock.get("child")]:
            pid = integer(value)
            if pid <= 0:
                continue
            try:
                kill(pid, 0)
                return True
            except Exception as error:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
                if error_code(error) != "ESRCH":
                    return True
        return False
    except Exception as error:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
        return error_code(error) != "ENOENT"


@js
class CodexChat:
    def __init__(self, root: str, filename: str = "", command: str = "",
                 prefix: list[str] | None = None, timeout: int = 600000):
        self.root = realpath_sync(root)
        self.filename = filename or state_path(self.root)
        self.lockfile = self.filename + ".lock"
        self.command = command or environment("ZEPY_CODEX_BIN") or "codex"
        self.prefix = prefix if prefix is not None else []
        self.timeout = timeout
        self.queue: list[str] = []
        self.child: ChildProcess | None = None
        self.lines: LineReader | None = None
        self.timer: Timer | None = None
        self.kill_timer: Timer | None = None
        self.active = False
        self.closed = False
        self.locked = False
        self.partial = ""
        self.session_id = ""
        self.messages: list[dict[str, str]] = []
        self.completed = False
        self.failure = ""
        self.stderr = ""
        self.buffer_size = 0
        self.pending: dict[str, str] = {}
        self.emitted: set[str] = set[str]()
        self.load()

    def load(self) -> None:
        self.session_id = ""
        self.messages = []
        try:
            saved = object_value(loads(read_text_sync(self.filename)))
            if isinstance(saved.get("session_id"), str) and isinstance(saved.get("messages"), list):
                self.session_id = field(saved, "session_id")
                for value in array_value(saved.get("messages")):
                    message = object_value(value)
                    if field(message, "role") in ["user", "assistant"] and isinstance(message.get("text"), str):
                        self.messages.append({"role": field(message, "role"), "text": field(message, "text")})
                self.messages = self.messages[-40:]
        except Exception as error:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
            if error_code(error) != "ENOENT":
                self.messages.append({"role": "assistant", "text": "Could not read the saved Codex conversation: " + str(error)})

    def save(self) -> None:
        mkdir_sync(dirname(self.filename))
        temporary = self.filename + "." + str(process_id()) + ".tmp"
        write_text_sync(temporary, dumps({"session_id": self.session_id, "messages": self.messages}))
        rename_sync(temporary, self.filename)

    def add(self, role: str, message: str) -> None:
        if not message:
            return
        self.messages.append({"role": role, "text": message[:8000] + "\n…" if len(message) > 8000 else message})
        self.messages = self.messages[-40:]
        self.save()

    def acquire(self) -> None:
        mkdir_sync(dirname(self.filename))
        for _attempt in range(2):
            try:
                fd = open_exclusive(self.lockfile)
                try:
                    write_descriptor(fd, dumps({"owner": process_id()}))
                finally:
                    close_descriptor(fd)
                self.locked = True
                return
            except Exception as error:
                if error_code(error) != "EEXIST":
                    raise
                if lock_alive(self.lockfile):
                    raise ValueError("Codex is working in another Zepy window. Wait for that turn to finish.")  # noqa: B904 -- JavaScript target has no exception chaining.
                unlink_sync(self.lockfile)
        raise ValueError("Could not acquire the Codex conversation")

    def release(self) -> None:
        if not self.locked:
            return
        try:
            unlink_sync(self.lockfile)
        except Exception as error:
            if error_code(error) != "ENOENT":
                raise
        self.locked = False

    def history(self) -> dict[str, object]:
        if not self.active:
            self.load()
        stamp = ""
        try:
            info = stat_sync(self.filename)
            stamp = str(info.mtimeMs) + ":" + str(info.size)
        except Exception:  # noqa: BLE001, S110 -- Node APIs raise JavaScript errors.
            pass
        return {"session_id": self.session_id, "messages": self.messages,
                "idle": not self.active and not lock_alive(self.lockfile), "stamp": stamp,
                "queued": len(self.queue), "partial": self.partial}

    def send(self, body: dict[str, object]) -> dict[str, object]:
        if self.closed:
            raise ValueError("Codex chat is closed")
        if body.get("flush"):
            return {"session_id": self.session_id, "text": "", "queued": False, "idle": not self.active}
        prompt = build_prompt(body)
        if not self.active:
            self.acquire()
            self.load()
        try:
            self.add("user", prompt)
        except Exception:
            if not self.active:
                self.release()
            raise
        self.queue.append(prompt)
        queued = self.active
        if not self.active:
            self.active = True
            self.next()
        return {"session_id": self.session_id, "text": "", "queued": queued, "idle": False}

    def next(self) -> None:
        if self.closed or not self.queue:
            self.active = False
            self.partial = ""
            self.release()
            return
        prompt = self.queue.pop(0)
        args = self.prefix + ["exec"]
        if self.session_id:
            args += ["resume", self.session_id]
        args += ["--json", "-c", 'approval_policy="never"', "-c", 'sandbox_mode="workspace-write"', "-"]
        self.completed = False
        self.failure = ""
        self.stderr = ""
        self.buffer_size = 0
        self.pending = {}
        self.emitted = set[str]()
        self.partial = "Starting Codex…"
        command = self.command
        previous_node_mode = environment("ELECTRON_RUN_AS_NODE")
        javascript_cli = command.endswith((".js", ".cjs", ".mjs"))
        if javascript_cli:
            args = [command] + args
            command = executable()
            set_environment("ELECTRON_RUN_AS_NODE", "1")
        try:
            child = spawn(command, args, self.root)
        finally:
            if javascript_cli:
                if previous_node_mode:
                    set_environment("ELECTRON_RUN_AS_NODE", previous_node_mode)
                else:
                    remove_environment("ELECTRON_RUN_AS_NODE")
        self.child = child
        if child.pid:
            write_text_sync(self.lockfile, dumps({"owner": process_id(), "child": child.pid}))
        send_stdin(child, prompt)
        self.kill_timer = None
        self.timer = set_timeout(self.timed_out, self.timeout)
        on_stderr(child, self.received_stderr)
        on_error(child, self.spawn_failed)
        self.lines = read_lines(child, self.received_line)
        on_stdout_size(child, self.received_size)
        on_close(child, self.finished)

    def signal_child(self, signal: str) -> None:
        child = self.child
        if child is None:
            return
        try:
            if platform() == "win32":
                child.kill(signal)
            else:
                kill(-child.pid, signal)
        except Exception:  # noqa: BLE001, S110 -- Node APIs raise JavaScript errors.
            pass

    def force_stop(self) -> None:
        self.signal_child("SIGKILL")

    def stop(self) -> None:
        child = self.child
        if child is None or child.exitCode is not None:
            return
        self.signal_child("SIGTERM")
        if self.kill_timer is None:
            timer = set_timeout(self.force_stop, 1500)
            self.kill_timer = timer
            timer.unref()

    def timed_out(self) -> None:
        self.failure = "Codex timed out after " + str(round(self.timeout / 1000)) + " seconds."
        self.stop()

    def received_stderr(self, data: str) -> None:
        self.stderr = (self.stderr + data)[-4000:]

    def spawn_failed(self, error: Exception) -> None:
        self.failure = ("Codex CLI was not found on PATH. Install Codex and run codex login."
                        if error_code(error) == "ENOENT" else str(error))

    def received_size(self, size: int) -> None:
        self.buffer_size += size
        if self.buffer_size > 16 * 1024 * 1024:
            self.failure = "Codex output exceeded the chat limit."
            self.stop()

    def received_line(self, line: str) -> None:
        try:
            event = object_value(loads(line))
        except Exception:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
            return
        try:
            kind = field(event, "type")
            if kind == "thread.started" and isinstance(event.get("thread_id"), str):
                self.session_id = field(event, "thread_id")
                self.save()
            elif kind == "turn.completed":
                self.completed = True
            elif kind in ["turn.failed", "error"]:
                self.failure = field(object_value(event.get("error")), "message") or field(event, "message") or "Codex turn failed."
            item = object_value(event.get("item"))
            if field(item, "type") == "agent_message" and isinstance(item.get("text"), str):
                identifier = field(item, "id")
                self.pending[identifier] = field(item, "text")
                self.partial = field(item, "text")
                if kind == "item.completed" and identifier not in self.emitted:
                    self.emitted.add(identifier)
                    self.add("assistant", field(item, "text"))
                    self.partial = ""
            elif kind == "item.started":
                item_type = field(item, "type")
                if item_type == "command_execution":
                    self.partial = "▸ " + (field(item, "command") or "Running command")[:200]
                elif item_type == "file_change":
                    self.partial = "▸ Updating files"
                elif item_type == "mcp_tool_call":
                    self.partial = "▸ " + (field(item, "tool") or "Using tool")[:200]
                elif item_type == "web_search":
                    self.partial = "▸ Searching the web"
        except Exception as error:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
            self.failure = str(error)
            self.stop()

    def finished(self, code: int) -> None:
        clear_timeout(self.timer)
        clear_timeout(self.kill_timer)
        if self.lines is not None:
            self.lines.close()
        self.child = None
        try:
            if self.closed:
                self.failure = "Codex was stopped when this Zepy session closed."
            elif not self.failure and (code != 0 or not self.completed):
                self.failure = self.stderr.strip() or "Codex exited before completing the turn (status " + str(code) + ")."
            for identifier, message in self.pending.items():
                if identifier not in self.emitted:
                    self.add("assistant", message)
            if self.failure:
                self.add("assistant", self.failure)
            if self.failure and self.queue:
                self.add("assistant", "The remaining queued messages were not sent.")
            if self.closed or self.failure:
                self.queue = []
        except Exception:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
            self.queue = []
        self.next()

    async def close(self) -> None:
        self.closed = True
        self.queue = []
        child = self.child
        if child is not None:
            self.stop()
            await wait_closed(child)
            return
        self.active = False
        self.release()


@js
class StdioService:
    def __init__(self, root: str):
        self.chat = CodexChat(root)

    def receive(self, line: str) -> None:
        request: dict[str, object] = {}
        try:
            request = object_value(loads(line))
            method = field(request, "method")
            if method == "history":
                result = self.chat.history()
            elif method == "send":
                result = self.chat.send(object_value(request.get("body")))
            else:
                raise ValueError("Unknown chat request")
            write_stdout(dumps({"id": request.get("id"), "result": result}) + "\n")
        except Exception as error:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
            write_stdout(dumps({"id": request.get("id"), "error": str(error)}) + "\n")

    async def close(self) -> None:
        await self.chat.close()


@js
def main() -> None:
    service = StdioService(arguments()[2])
    read_stdin_lines(service.receive, service.close)
    on_signal("SIGTERM", service.close)
