"""Real stock-Electron acceptance: filesystem, GPU scrolling, Python debugging."""
import asyncio
import base64
import json
import os
import signal
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import pytest
from pyjs.tooling.browser import BrowserPage, CDPSession, free_port, request_json

pytestmark = pytest.mark.pyjs_python
ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "dist/desktop-validation"
EXECUTABLE = Path(os.environ.get("ZEPY_ELECTRON_BIN", ROOT / "dist/zepy/electron"))


async def connect(port, target_query=""):
    for _ in range(300):
        try:
            targets = await asyncio.to_thread(request_json, f"http://127.0.0.1:{port}/json")
            target = next((t for t in targets if t["type"] == "page" and t["url"].startswith("file:")
                           and (target_query in t["url"] if target_query else "debugTarget" not in t["url"])), None)
            if target:
                page = BrowserPage(await CDPSession.open(target["webSocketDebuggerUrl"]), target["id"])
                await page.initialize()
                return page
        except OSError, RuntimeError:
            pass
        await asyncio.sleep(.1)
    raise AssertionError("Electron did not open the expected window; see run.log")


async def screenshot(page, name):
    # Composite the submitted GPU canvas, matching the workbench screenshot contract.
    await page.evaluate("""(async () => {
        const editor = document.querySelector('pyjs-app').editor;
        editor.render(); await editor.device.queue.onSubmittedWorkDone();
        const image = new Image(); image.src = editor.canvas.toDataURL('image/png');
        await image.decode();
        const overlay = document.createElement('canvas'); overlay.id = 'desktop-gpu-snapshot';
        overlay.width = editor.canvas.width; overlay.height = editor.canvas.height;
        Object.assign(overlay.style, {position:'absolute',left:'0',top:'0',width:'100%',height:'100%',pointerEvents:'none'});
        editor.canvas.parentElement.appendChild(overlay); overlay.getContext('2d').drawImage(image,0,0);
    })()""")
    data = await page.session.send("Page.captureScreenshot", {"format":"png"})
    (ARTIFACTS / name).write_bytes(base64.b64decode(data["data"]))
    await page.evaluate("document.getElementById('desktop-gpu-snapshot').remove()")


def test_electron_browses_scrolls_and_debugs_its_python_source():
    if not EXECUTABLE.is_file():
        pytest.fail("Build the Electron app first; see zepy/desktop/README.md")

    async def run():
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        port = free_port()
        pages = []
        with tempfile.TemporaryDirectory(prefix="zepy-desktop-") as profile, (ARTIFACTS / "run.log").open("w") as log:
            codex_home = Path(profile) / "codex"
            codex_home.mkdir()
            environment = {**os.environ, "CODEX_HOME":str(codex_home),
                "ZEPY_CODEX_BIN":os.environ["ZEPY_TEST_CODEX_FIXTURE"]}
            arguments = [str(EXECUTABLE), f"--workspace={ROOT}",
                f"--remote-debugging-port={port}", f"--user-data-dir={profile}"]
            if os.environ.get("ZEPY_ELECTRON_HEADLESS", "1") != "0":
                arguments.extend([
                    "--no-sandbox", "--force-device-scale-factor=1",
                    "--use-webgpu-adapter=swiftshader", "--enable-unsafe-webgpu", "--enable-unsafe-swiftshader",
                    "--enable-logging=stderr",
                    "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                    "--disable-backgrounding-occluded-windows",
                ])
                if os.name != "nt" and sys.platform != "darwin":
                    arguments.extend([
                        "--enable-features=Vulkan", "--use-angle=swiftshader", "--use-vulkan=swiftshader",
                        "--disable-vulkan-surface", "--ozone-platform=headless",
                        "--ozone-override-screen-size=1440,1000",
                    ])
                elif os.name == "nt":
                    arguments.remove("--use-webgpu-adapter=swiftshader")
                    # Windows shared images require the passthrough command decoder.
                    arguments.extend(["--use-angle=d3d11", "--use-cmd-decoder=passthrough",
                                      "--use-webgpu-adapter=d3d11",
                                      "--force-webgpu-compat", "--enable-logging=file",
                                      f"--log-file={ARTIFACTS / 'chromium.log'}"])
                else:
                    arguments.extend(["--use-angle=swiftshader", "--use-vulkan=swiftshader"])
            process = await asyncio.to_thread(subprocess.Popen, arguments,
                cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
            try:
                page = await connect(port); pages.append(page)
                await page.evaluate("""(() => {
                    globalThis.gpuDiagnostics = {destroyCalls: []};
                    const destroy = GPUDevice.prototype.destroy;
                    GPUDevice.prototype.destroy = function() {
                        gpuDiagnostics.destroyCalls.push(new Error().stack);
                        return destroy.call(this);
                    };
                })()""")
                await page.set_viewport(1280, 900, scale=1)
                await page.wait_for("document.querySelector('pyjs-app')?.editor != null", "GPU editor", timeout=90)
                await page.evaluate("""(() => {
                    const device = document.querySelector('pyjs-app').editor.device;
                    const info = device.adapterInfo;
                    gpuDiagnostics.adapter = {vendor:info.vendor,architecture:info.architecture,
                        device:info.device,description:info.description,isFallbackAdapter:info.isFallbackAdapter};
                    device.lost.then(info => {gpuDiagnostics.lost = {reason: info.reason, message: info.message};});
                    device.addEventListener('uncapturederror', event => {gpuDiagnostics.error = event.error.message;});
                })()""")
                assert await page.evaluate("typeof require") == "undefined"
                assert await page.evaluate("location.protocol") == "file:"
                assert await page.evaluate("document.querySelectorAll('[data-kind=dir]').length") > 5
                await page.click("[data-testid=explorer] [data-path='zepy/app.py']")
                await page.wait_for("document.querySelector('pyjs-app').editor.path === 'zepy/app.py'", "own source")
                contents = await page.evaluate("document.querySelector('pyjs-app').editor.buffer.get_value()")
                assert contents == (ROOT / "zepy/app.py").read_text()
                assert len(contents) > 80_000, "The acceptance file must exercise large source reads"
                await page.session.send("Input.dispatchMouseEvent", {"type":"mouseWheel", "x":700,"y":450,"deltaY":1200,"deltaX":0})
                await page.wait_for("document.querySelector('pyjs-app').editor.scroll_y > 500", "source scroll")
                await screenshot(page, "source.png")
                assert await page.evaluate("document.querySelector('[data-testid=chat-input]').placeholder") == "Ask Codex about this file…"
                await page.fill("[data-testid=chat-input]", "Explain this file")
                await page.click("[data-testid=chat-send]")
                await page.wait_for("document.querySelector('[data-testid=chat-log]').textContent.includes('Codex fixture: Explain this file')", "Codex reply", timeout=30)
                await page.fill("[data-testid=chat-input]", "Continue")
                await page.click("[data-testid=chat-send]")
                await page.wait_for("document.querySelector('[data-testid=chat-log]').textContent.includes('Codex fixture: Continue')", "Codex resumed reply", timeout=30)
                calls = [json.loads(raw) for raw in (codex_home / "calls.jsonl").read_text().splitlines()]
                assert calls[1]["args"][1:3] == ["resume", "00000000-0000-4000-8000-000000000001"]
                assert "Private reasoning" not in await page.text("[data-testid=chat-log]")
                assert "Raw tool payload" not in await page.text("[data-testid=chat-log]")
                await screenshot(page, "codex.png")
                await page.click("[data-testid=activity-debug]")
                lines = contents.splitlines()
                line = next(i+2 for i,text in enumerate(lines) if text.startswith("    async def open_path("))
                # Move the real editor cursor to the first statement in open_path.
                await page.evaluate(f"""(() => {{const e=document.querySelector('pyjs-app').editor;
                    e.cursor.line_number={line};e.cursor.column=1;e.ensure_visible();e.render();}})()""")
                await page.click("[data-testid=debug-breakpoint]")
                await page.wait_for(f"document.querySelector('[data-testid=debug-breakpoints]').textContent.includes('zepy/app.py:{line}')", "Python breakpoint")
                await page.click("[data-testid=debug-start]")
                target = await connect(port, "debugTarget=1"); pages.append(target)
                await target.wait_for("document.querySelector('pyjs-app')?.editor != null", "debug target editor", timeout=90)
                # The click can remain pending while its handler is paused; the controller must still work.
                trigger = asyncio.create_task(target.click("[data-testid=explorer] [data-path='zepy/services/workspace.py']"))
                await page.wait_for("document.querySelector('[data-testid=debug-status]').textContent.startsWith('Paused')", "Python pause", timeout=30)
                await page.wait_for("document.querySelector('[data-testid=debug-variables]').textContent.includes('workspace.py')", "Python local path")
                assert await page.evaluate("document.querySelector('pyjs-app').editor.cursor.line_number") == line
                assert 'open_path' in await page.text("[data-testid=debug-frames]")
                assert 'self' in await page.text("[data-testid=debug-variables]")
                await screenshot(page, "debugger.png")
                await page.click("[data-testid=debug-step]")
                await page.wait_for(f"document.querySelector('pyjs-app').editor.cursor.line_number > {line}", "Python source step", timeout=30)
                await page.click("[data-testid=debug-continue]")
                await asyncio.wait_for(trigger, 10)
                await target.wait_for("document.querySelector('pyjs-app').editor.path === 'zepy/services/workspace.py'", "continued file open")
                await page.click("[data-testid=debug-stop]")
                await page.wait_for("document.querySelector('[data-testid=debug-status]').textContent.startsWith('Ready')", "debug target stopped")
                assert not page.exceptions, page.exceptions
                assert not target.exceptions, target.exceptions
                (ARTIFACTS / "result.json").write_text(json.dumps({"workspace":str(ROOT), "source_bytes":len(contents),
                    "python_breakpoint_line":line, "scrolled":True, "paused_with_locals":True, "stepped":True,
                    "continued":True, "stopped":True, "python_server":False, "codex_chat_and_resume":True,
                    "headless":os.environ.get("ZEPY_ELECTRON_HEADLESS", "1") != "0",
                    "arguments":arguments}, indent=2) + "\n")
            except Exception:
                diagnostics = {"traceback": traceback.format_exc(), "pages": []}
                (ARTIFACTS / "failure.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
                for page in pages:
                    item = {"exceptions": page.exceptions, "console": page.console}
                    try:
                        item["page"] = await asyncio.wait_for(
                            page.evaluate("({url:location.href,text:document.body.innerText,gpu:globalThis.gpuDiagnostics})"), timeout=5)
                        item["probe"] = await asyncio.wait_for(page.evaluate("""(async () => {
                            const adapter = await navigator.gpu.requestAdapter();
                            if (!adapter) return {adapter:null};
                            const device = await adapter.requestDevice();
                            try {
                                await device.queue.onSubmittedWorkDone();
                                return {emptySubmission:'ok'};
                            } catch(error) {return {error:String(error)};}
                            finally {device.destroy();}
                        })()"""), timeout=5)
                    except Exception as error:  # noqa: BLE001 -- Diagnostics must preserve the original failure.
                        item["error"] = str(error)
                    diagnostics["pages"].append(item)
                (ARTIFACTS / "failure.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
                raise
            finally:
                for page in pages:
                    await page.session.close()
                if process.poll() is None:
                    if os.name == "nt":
                        await asyncio.to_thread(subprocess.run, ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
                    try:
                        await asyncio.to_thread(process.wait, timeout=5)
                    except subprocess.TimeoutExpired:
                        if os.name == "nt":
                            process.kill()
                        else:
                            os.killpg(process.pid, signal.SIGKILL)
                        await asyncio.to_thread(process.wait, timeout=5)
    asyncio.run(asyncio.wait_for(run(), timeout=240))
