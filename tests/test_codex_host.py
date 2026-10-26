"""Python-authored tests of the generated Node chat service."""
import pytest
from pyjs import js
from pyjs.node import (
    environment,
    executable,
    exists,
    join,
    mkdtemp,
    read_text,
    remove_environment,
    remove_tree,
    set_environment,
    sleep,
    temp_directory,
)
from pyjs.node.json import loads

from zepy.desktop.host.codex import CodexChat, build_prompt
from zepy.services.data import array_value, field, object_value

pytestmark = pytest.mark.pyjs_node


@js
async def wait_idle(chat: CodexChat) -> None:
    for _attempt in range(500):
        if not chat.active:
            return
        await sleep(10)
    raise ValueError("Codex fixture did not settle")


@js
async def wait_progress(chat: CodexChat) -> None:
    for _attempt in range(500):
        if "Inspect" in chat.partial:
            return
        await sleep(10)
    raise ValueError("Codex fixture did not report progress")


@js
class Session:
    def __init__(self, root: str):
        self.root = root
        self.previous = environment("CODEX_HOME")
        set_environment("CODEX_HOME", root)
        self.chat = CodexChat(root, join(root, "chat.json"), executable(),
                              [environment("ZEPY_TEST_CODEX_FIXTURE")])

    async def close(self) -> None:
        await self.chat.close()
        await wait_idle(self.chat)
        if self.previous:
            set_environment("CODEX_HOME", self.previous)
        else:
            remove_environment("CODEX_HOME")
        await remove_tree(self.root)


@js
async def setup() -> Session:
    return Session(await mkdtemp(join(temp_directory(), "desktop-codex-")))


@js
def test_selection_prompt_retains_paths_ranges_and_newlines():
    assert build_prompt({"text": "why?", "path": "a.py", "selection": "x = 1\ny = 2", "line": 4, "end_line": 5}) == "why?\n\nSelected a.py:4-5:\nx = 1\ny = 2"
    rejected = False
    try:
        build_prompt({"text": " "})
    except Exception as error:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
        rejected = "Empty" in str(error)
    assert rejected


@js
async def test_real_child_stream_queue_persist_and_resume():
    session = await setup()
    chat = session.chat
    try:
        assert chat.send({"text": "first"})["idle"] is False
        assert chat.send({"text": "second"})["queued"] is True
        await wait_progress(chat)
        await wait_idle(chat)
        history = chat.history()
        assert history["session_id"] == "00000000-0000-4000-8000-000000000001"
        messages = [field(object_value(item), "text") for item in array_value(history["messages"])]
        assert messages == ["first", "second", "Codex fixture: first", "Codex fixture: second"]
        calls = [object_value(loads(line)) for line in (await read_text(join(session.root, "calls.jsonl"))).strip().split("\n")]
        first = array_value(calls[0]["args"])
        second = array_value(calls[1]["args"])
        assert first[0] == "exec"
        assert "resume" not in first
        assert "resume" in second
        assert history["session_id"] in second
        assert 'sandbox_mode="workspace-write"' in first
        assert "--model" not in first
        assert calls[0]["cwd"] == session.root
        restored = CodexChat(session.root, chat.filename)
        assert restored.session_id == chat.session_id
        assert restored.messages == chat.messages
        await restored.close()
    finally:
        await session.close()


@js
async def test_parallel_instance_cannot_resume_busy_conversation():
    session = await setup()
    chat = session.chat
    try:
        chat.send({"text": "first"})
        other = CodexChat(session.root, chat.filename)
        rejected = False
        try:
            other.send({"text": "collision"})
        except Exception as error:  # noqa: BLE001 -- Node APIs raise JavaScript errors.
            rejected = "another Zepy window" in str(error)
        await other.close()
        assert rejected
        await wait_idle(chat)
        assert all(message["text"] != "collision" for message in chat.messages)
    finally:
        await session.close()


@js
async def test_failed_turn_releases_lock():
    session = await setup()
    try:
        session.chat.send({"text": "fail"})
        await wait_idle(session.chat)
        assert "Fixture turn failed" in session.chat.messages[-1]["text"]
        assert not exists(session.chat.lockfile)
    finally:
        await session.close()


@js
async def test_missing_cli_and_timeout_release_process():
    session = await setup()
    chat = session.chat
    try:
        chat.command = "/nonexistent-codex"
        chat.send({"text": "hello"})
        await wait_idle(chat)
        assert "not found on PATH" in chat.messages[-1]["text"]
        chat.command = executable()
        chat.timeout = 100
        chat.send({"text": "hang"})
        await wait_idle(chat)
        assert "timed out" in chat.messages[-1]["text"]
        assert chat.child is None
    finally:
        await session.close()


@js
async def test_closing_chat_stops_child_and_releases_lock():
    session = await setup()
    chat = session.chat
    try:
        chat.send({"text": "hang"})
        await wait_progress(chat)
        await chat.close()
        assert chat.child is None
        assert not chat.active
        assert "was stopped" in chat.messages[-1]["text"]
        assert not exists(chat.lockfile)
    finally:
        await session.close()
