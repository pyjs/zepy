"""Deterministic Codex protocol fixture: no models, network or authentication."""
from pyjs import js
from pyjs.node import (
    append_text_sync,
    arguments,
    cwd,
    environment,
    join,
    read_stdin,
    set_exit_code,
    set_interval,
    set_timeout,
    write_stdout,
)
from pyjs.node.json import dumps


@js
class Fixture:
    def __init__(self):
        self.prompt = ""

    def data(self, value: str) -> None:
        self.prompt += value

    def emit(self, value: dict[str, object]) -> None:
        write_stdout(dumps(value) + "\n")

    def wait(self) -> None:
        pass

    def end(self) -> None:
        append_text_sync(join(environment("CODEX_HOME"), "calls.jsonl"),
                         dumps({"args": arguments()[2:], "prompt": self.prompt, "cwd": cwd()}) + "\n")
        self.emit({"type": "thread.started", "thread_id": "00000000-0000-4000-8000-000000000001"})
        self.emit({"type": "item.started", "item": {"id": "command", "type": "command_execution", "command": "Inspect selected lines"}})
        self.emit({"type": "item.completed", "item": {"id": "reasoning", "type": "reasoning", "text": "Private reasoning must not appear"}})
        self.emit({"type": "item.completed", "item": {"id": "tool", "type": "command_execution", "aggregated_output": "Raw tool payload must not appear"}})
        if self.prompt == "hang":
            set_interval(self.wait, 1000)
            return
        set_timeout(self.finish, 120)

    def finish(self) -> None:
        if self.prompt == "fail":
            self.emit({"type": "turn.failed", "error": {"message": "Fixture turn failed"}})
            set_exit_code(1)
            return
        self.emit({"type": "item.updated", "item": {"id": "reply", "type": "agent_message", "text": "Reading the selection…"}})
        self.emit({"type": "item.completed", "item": {"id": "reply", "type": "agent_message", "text": "Codex fixture: " + self.prompt}})
        self.emit({"type": "turn.completed", "usage": {}})


@js
def main() -> None:
    fixture = Fixture()
    read_stdin(fixture.data, fixture.end)
