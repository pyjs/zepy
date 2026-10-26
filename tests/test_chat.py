import json
import os
import time

import pytest

from zepy.server import chat


@pytest.fixture
def service(tmp_path, monkeypatch):
    chat.close_chat()
    monkeypatch.setattr(chat, "workspace_root", lambda: tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setenv("ZEPY_CODEX_BIN", os.environ["ZEPY_TEST_CODEX_FIXTURE"])
    yield tmp_path
    chat.close_chat()


def settled():
    for _ in range(200):
        result = chat.chat_request("history")
        if result["idle"]:
            return result
        time.sleep(.02)
    pytest.fail("Codex fixture did not settle")


def test_browser_bridge_runs_selected_context_and_resumes_after_restart(service):
    result = chat.chat_request("send", {"text": "why?", "path": "a.py", "selection": "x = 1", "line": 4})
    assert result["idle"] is False
    first = settled()
    assert first["messages"][-1]["text"] == "Codex fixture: why?\n\nSelected a.py:4:\nx = 1"
    assert not any("Private reasoning" in m["text"] for m in first["messages"])
    chat.close_chat()
    assert chat.chat_request("history")["messages"] == first["messages"]
    chat.chat_request("send", {"text": "continue"})
    assert settled()["session_id"] == first["session_id"]
    calls = [json.loads(line) for line in (service / "calls.jsonl").read_text().splitlines()]
    assert calls[1]["args"][1:3] == ["resume", first["session_id"]]


def test_browser_bridge_rejects_empty_prompt_and_exposes_cli_failures(service):
    with pytest.raises(ValueError, match="Empty prompt"):
        chat.chat_request("send", {"text": " "})
    chat.chat_request("send", {"text": "fail"})
    assert settled()["messages"][-1]["text"] == "Fixture turn failed"
