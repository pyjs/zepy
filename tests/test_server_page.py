"""The served workbench page, after custom-element hydration."""

import asyncio
import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

import pytest
from pyjs.tooling.browser import Browser, free_port, wait_for_http


class VisibleScrollbarBrowser(Browser):
    def _launch_arguments(self, profile):
        return [
            argument
            for argument in super()._launch_arguments(profile)
            if argument != "--hide-scrollbars"
        ]

from zepy.server.app import create_workbench_server
from zepy.server.workspace import workspace_root

pytestmark = pytest.mark.pyjs_python
RENDERS = Path(__file__).resolve().parent / "renders"


def test_hydrated_workbench_shows_explorer_and_opens_a_file():
    async def run() -> None:
        port = free_port()
        url = f"http://127.0.0.1:{port}/"
        server = create_workbench_server(port=port)
        server.start()
        try:
            await wait_for_http(url, timeout=120)
            async with Browser(headless=True, webgpu=True) as browser:
                page = await browser.new_page(url)
                await page.wait_for(
                    "document.querySelector('pyjs-app')?.editor != null",
                    "the GPU editor to start",
                    timeout=60,
                )
                files = await page.evaluate(
                    "document.querySelectorAll('[data-kind=\"file\"]').length"
                )
                dirs = await page.evaluate(
                    "document.querySelectorAll('[data-kind=\"dir\"]').length"
                )
                assert files >= 3
                assert dirs >= 1
                assert "welcome.md" in await page.text("[data-testid='explorer']")

                await page.click("[data-testid='explorer'] [data-path='workspace/hello.py']")
                await page.wait_for(
                    "document.querySelector('pyjs-app')?.tab_name === 'hello.py'",
                    "the editor tab to show hello.py",
                    timeout=30,
                )
                assert page.exceptions == []
        finally:
            server.close()

    asyncio.run(run())


def _save_over_http(url: str, content: str):
    body = json.dumps({"path": "workspace/notes.txt", "content": content}).encode()
    request = Request(url + "api/file", data=body,
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request) as response:
        return json.load(response)


def test_hydrated_workbench_saves_a_typed_edit():
    async def run() -> None:
        notes = workspace_root() / "workspace" / "notes.txt"
        original = notes.read_text(encoding="utf-8")
        port = free_port()
        url = f"http://127.0.0.1:{port}/"
        server = create_workbench_server(port=port)
        server.start()
        try:
            await wait_for_http(url, timeout=120)
            # Exercise the real HTTP body limit before testing the editor save action.
            large = "🐍" * 30000 + "\n"
            for content in [large, original]:
                saved = await asyncio.to_thread(_save_over_http, url, content)
                assert saved["content"] == content
                assert notes.read_text(encoding="utf-8") == content
            async with Browser(headless=True, webgpu=True) as browser:
                page = await browser.new_page(url)
                await page.wait_for(
                    "document.querySelector('pyjs-app')?.editor != null",
                    "the GPU editor to start",
                    timeout=60,
                )
                await page.click("[data-testid='explorer'] [data-path='workspace/notes.txt']")
                await page.wait_for(
                    "document.querySelector('pyjs-app')?.tab_name === 'notes.txt'",
                    "the editor tab to show notes.txt",
                )
                result = await page.evaluate(
                    """(async () => {
                        const app = document.querySelector('pyjs-app');
                        app.editor.insert('SAVE_PROBE');
                        app.sync_status();
                        const dirtyBefore = app.tab_label.getAttribute('data-dirty');
                        await app.save();
                        return {
                            dirtyBefore: dirtyBefore,
                            dirtyAfter: app.tab_label.getAttribute('data-dirty'),
                            value: app.editor.buffer.get_value()
                        };
                    })()"""
                )
                assert result["dirtyBefore"] == "true"
                assert result["dirtyAfter"] == "false"
                assert "SAVE_PROBE" in result["value"]
                assert "SAVE_PROBE" in notes.read_text(encoding="utf-8")
                assert page.exceptions == []
        finally:
            notes.write_text(original, encoding="utf-8")
            server.close()

    asyncio.run(run())


def _write_chat_fixture(home: Path) -> None:
    root = workspace_root()
    state = home / "zepy" / (hashlib.sha256(str(root.resolve()).encode()).hexdigest() + ".json")
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"session_id": "00000000-0000-4000-8000-000000000001", "messages": [
        {"role": "user", "text": "How are files read?"},
        {"role": "assistant", "text": "The workspace service reads files on demand."},
        {"role": "tool", "text": "this tool payload must not appear"},
    ]}), encoding="utf-8")


def test_hydrated_workbench_dumps_screenshot_of_zepy_source():
    """Dump tests/renders/zepy_source.png for tests/renders/SCREENSHOT_REVIEW.md."""
    async def run() -> None:
        assert (workspace_root() / "zepy" / "app.py").is_file()
        previous_home = os.environ.get("CODEX_HOME")
        home = Path(tempfile.mkdtemp(prefix="zepy-codex-"))
        os.environ["CODEX_HOME"] = str(home)
        _write_chat_fixture(home)
        port = free_port()
        url = f"http://127.0.0.1:{port}/"
        server = create_workbench_server(port=port)
        server.start()
        try:
            await wait_for_http(url, timeout=120)
            async with VisibleScrollbarBrowser(headless=True, webgpu=True) as browser:
                page = await browser.new_page("about:blank")
                await page.set_viewport(1280, 800, scale=2)
                await page.session.send("Page.navigate", {"url": url})
                await page.wait_for(
                    "document.querySelector('pyjs-app')?.editor != null",
                    "the GPU editor to start",
                    timeout=60,
                )
                explorer = await page.text("[data-testid='explorer']")
                assert "app.py" in explorer
                assert "workbench_chat.py" in explorer
                await page.click(
                    "[data-testid='explorer'] [data-path='zepy/services/workspace.py']"
                )
                await page.wait_for(
                    "document.querySelector(\"[data-testid='explorer'] [data-path='zepy/services/workspace.py']\")"
                    "?.getAttribute('data-active') === 'true'",
                    "explorer to highlight zepy/services/workspace.py",
                    timeout=30,
                )
                await page.wait_for(
                    "document.querySelector('pyjs-app')?.tab_name === 'workspace.py'",
                    "the editor tab to show zepy/services/workspace.py",
                    timeout=30,
                )
                await page.wait_for(
                    "document.querySelector('pyjs-app')?.editor?.path === 'zepy/services/workspace.py'",
                    "the GPU editor to open zepy/services/workspace.py",
                    timeout=30,
                )
                await page.wait_for(
                    "(document.querySelector('[data-testid=\"chat-pane\"]')?.innerText || '')"
                    ".includes('The workspace service reads files on demand.')",
                    "chat pane to show the assistant turn",
                    timeout=30,
                )
                line1 = await page.evaluate(
                    "document.querySelector('pyjs-app')?.editor?.buffer?.get_line_content(1)"
                )
                assert line1 == '"""Workspace behavior shared by the desktop host and browser server."""'
                presented = await page.evaluate(
                    """(async () => {
                        const app = document.querySelector('pyjs-app');
                        const editor = app && app.editor;
                        if (!editor) {
                            throw new Error('expected GPU editor');
                        }
                        editor.render();
                        await editor.device.queue.onSubmittedWorkDone();
                        const gpu = editor.canvas;
                        const url = gpu.toDataURL('image/png');
                        if (!url || url === 'data:,') {
                            throw new Error('GPU canvas toDataURL was empty');
                        }
                        const host = gpu.parentElement;
                        const style = window.getComputedStyle(host);
                        if (style.position === 'static') {
                            host.style.position = 'relative';
                        }
                        let overlay = document.getElementById('zepy-gpu-snapshot');
                        if (!overlay) {
                            overlay = document.createElement('canvas');
                            overlay.id = 'zepy-gpu-snapshot';
                            overlay.style.position = 'absolute';
                            overlay.style.left = '0';
                            overlay.style.top = '0';
                            overlay.style.width = '100%';
                            overlay.style.height = '100%';
                            overlay.style.pointerEvents = 'none';
                            host.appendChild(overlay);
                        }
                        overlay.width = gpu.width;
                        overlay.height = gpu.height;
                        const image = new Image();
                        await new Promise((resolve, reject) => {
                            image.onload = resolve;
                            image.onerror = () => reject(new Error('GPU snapshot image failed'));
                            image.src = url;
                        });
                        overlay.getContext('2d').drawImage(image, 0, 0);
                        return url;
                    })()"""
                )
                if not isinstance(presented, str) or not presented.startswith("data:image/png"):
                    raise AssertionError("expected a PNG data URL from the GPU canvas")
                gpu_png = base64.b64decode(presented.split(",", 1)[1])
                assert gpu_png.startswith(b"\x89PNG")
                (RENDERS / "zepy_source_gpu.png").write_bytes(gpu_png)
                path = RENDERS / "zepy_source.png"
                await page.screenshot(path)
                data = path.read_bytes()
                assert data.startswith(b"\x89PNG")
                assert len(data) > 10_000
                chat = await page.text("[data-testid='chat-pane']")
                assert "How are files read?" in chat
                assert "The workspace service reads files on demand." in chat
                assert "this tool payload must not appear" not in chat
                vthumb = await page.evaluate(
                    "document.querySelector('[data-testid=\"editor-vthumb\"]')"
                    "?.getAttribute('style') || ''"
                )
                assert "height:" in vthumb
                assert page.exceptions == []
        finally:
            server.close()
            if previous_home is None:
                os.environ.pop("CODEX_HOME", None)
            else:
                os.environ["CODEX_HOME"] = previous_home
            from zepy.server.chat import close_chat
            close_chat()

    asyncio.run(run())
