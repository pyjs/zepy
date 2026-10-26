"""Codex chat routes for the browser workbench, sharing the Electron service."""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import threading
from pathlib import Path

from pyjs import nojs
from pyjs.server.dev import Response
from pyjs.tooling.node import Node as NodeRuntime

from zepy.server.workspace import workspace_root

_bridge: subprocess.Popen | None = None
_bridge_key: tuple[str, str, str] | None = None
_bridge_lock = threading.RLock()


@nojs
def close_chat() -> None:
    global _bridge, _bridge_key
    with _bridge_lock:
        process, _bridge = _bridge, None
        _bridge_key = None
        if process is None:
            return
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if process.stdout:
            process.stdout.close()


atexit.register(close_chat)


@nojs
def chat_request(method: str, body: object = None) -> dict:
    global _bridge, _bridge_key
    with _bridge_lock:
        root = str(workspace_root().resolve())
        key = (root, os.environ.get("CODEX_HOME", ""), os.environ.get("ZEPY_CODEX_BIN", ""))
        if _bridge is None or _bridge.poll() is not None or key != _bridge_key:
            close_chat()
            node = NodeRuntime()
            node.ensure()
            environment = {**os.environ, **node.environment()}
            script = Path(__file__).resolve().parents[2] / ".pyjs/desktop/codex.cjs"
            if not script.is_file():
                raise RuntimeError(
                    "Build the Codex bridge first: pyjs build zepy.desktop.host.codex "
                    "--target node -o .pyjs/desktop/codex.cjs"
                )
            _bridge = subprocess.Popen(
                [node.executable, script, root],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=environment,
            )
            _bridge_key = key
        assert _bridge.stdin is not None and _bridge.stdout is not None
        _bridge.stdin.write(json.dumps({"id": 1, "method": method, "body": body}) + "\n")
        _bridge.stdin.flush()
        raw = _bridge.stdout.readline()
        if not raw:
            close_chat()
            raise RuntimeError("Codex chat service stopped unexpectedly")
        reply = json.loads(raw)
        if "error" in reply:
            raise ValueError(reply["error"])
        return reply["result"]


@nojs
def serve_chat_history(request) -> Response:
    try:
        return Response.json(chat_request("history"))
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        return Response.json(
            {
                "session_id": "",
                "messages": [{"role": "assistant", "text": str(error)}],
                "idle": True,
                "stamp": str(error),
                "queued": 0,
                "partial": "",
            }
        )


@nojs
def serve_chat_send(request) -> Response:
    try:
        body = request.json()
        if not isinstance(body, dict):
            raise TypeError("Invalid chat request")
        return Response.json(chat_request("send", body))
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        return Response.json(
            {"session_id": "", "text": str(error), "queued": False, "idle": True}, status=400
        )
