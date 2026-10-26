# Zepy desktop

Build the Python workbench as a stock Electron application:

```bash
uv run pyjs build zepy.app --target electron --electron-host zepy/desktop/host -o dist/zepy
mkdir -p dist/zepy/licenses/zepy
cp LICENSE THIRD_PARTY_NOTICES.md dist/zepy/licenses/zepy/
./dist/zepy/electron --workspace="$PWD"
```

The lockfile pins the public PyJS revision with Electron support. The first
build downloads the pinned stock Electron runtime; subsequent builds reuse it.
For an offline build, pass `--electron-runtime /path/to/electron/dist` with an
already downloaded runtime. Choose a fresh output directory for each build.

The host and isolated preload are also authored in Python, in
`zepy/desktop/host/`. The build compiles them into self-contained CommonJS
bundles and Python source maps. Generated JavaScript is not checked into Git,
and the packaged application never invokes the compiler at launch.

For browser development, build its shared Codex bridge once before starting
the server, and rebuild after editing host Python:

```bash
uv run pyjs build zepy.desktop.host.codex --target node -o .pyjs/desktop/codex.cjs
uv run zepy serve
```

Tests compile their Node services and CLI fixture automatically. Tests marked
`pyjs_node` run the compiled Python in a real Node process.

The running application uses JavaScript and stock Electron. Python is needed
for building and tests, not for launching the application. There is no HTTP
server. The sandboxed renderer owns the Python-authored editor, DOM, state and
GPU rendering. A small Node host handles coarse file and debugger requests.
The packaged UI is trusted application code: its local `file://` origin can
read user-accessible files even without Node globals. Workspace checks constrain
the host API, not every capability of the renderer.
The workspace defaults to the launch directory, or the explicit `--workspace`
argument. The explorer loads names and hierarchy first; opening a file reads
its content. Text files up to 8 MiB are supported. Dependencies, build output,
Git internals and symlink directories are excluded from the explorer.

## Linux sandbox setup

Electron needs working user namespaces or a correctly installed sandbox
helper on Linux. Follow your distribution's Electron packaging guidance when
installing a runtime. Zepy does not add `--no-sandbox` to normal launches.

The managed headless test explicitly disables the sandbox in its isolated
test profile. To test an installed runtime with sandboxing and normal GPU
selection, run `ZEPY_ELECTRON_HEADLESS=0 uv run pytest -q tests/test_desktop.py`.

## Debug Zepy from Zepy

1. Open a Python file included in the compiled renderer, such as `zepy/app.py`.
2. Click **▷** in the activity bar to open the debug panel.
3. Put the editor cursor on an executable line. Click **Toggle breakpoint at
   cursor**. The panel shows the resolved Python line.
4. Click **Start Zepy**. A second window runs the same compiled application with
   a separate renderer session. Use that window to trigger the breakpoint.
5. The first window stays responsive and displays the Python source location,
   call stack and local values. Use **Step over**, **Step into**, **Step out**,
   **Continue**, **Pause** or **Stop**. Click a mapped stack frame to open it.

For a concrete example, break on the first statement inside `App.open_path`
in `zepy/app.py`, then open a file in the second window. The `path` local shows
that file's workspace-relative name. Breakpoints can be set before launch;
blank or non-executable lines resolve within the next four Python lines.
Toggle the same cursor location again to remove a breakpoint.

This debugger consumes PyJS's existing v3 Python source map and talks to
Electron's `webContents.debugger` CDP transport. It debugs compiled renderer
Python, not CPython or the Node host. Values are JavaScript runtime values:
`self` represents `this`, and not-yet-assigned locals may appear as `undefined`.
Release source maps use workspace-relative paths so a matching source checkout
can be debugged on another machine. Rebuild after editing Python; stale source
is rejected when setting or binding breakpoints.
Framework sources outside the selected workspace are not opened by this first
version. Breakpoints are session-local; there is no watch-expression editor or
conditional-breakpoint UI yet.

## Validation

```bash
uv run pytest -q tests/test_desktop.py
uv run pytest -q tests/test_server_page.py::test_hydrated_workbench_dumps_screenshot_of_zepy_source
uv run pytest -q --pyjs-target=node tests/test_desktop_host.py tests/test_codex_host.py
```

The desktop acceptance launches the packaged app in an isolated managed
headless session, browses this repository, opens the complete `zepy/app.py`,
scrolls using a wheel event, sets a Python breakpoint through the workbench,
starts a debug target, checks locals and Python stepping, continues and stops.
Screenshots composite submitted GPU canvas pixels. Results and screenshots are
under `dist/desktop-validation`; `ZEPY_ELECTRON_BIN` can select another build.
The test-only launch uses software WebGPU and `--no-sandbox` because the
uninstalled development runtime has no configured setuid sandbox helper.
Normal desktop launch retains Electron's sandbox defaults.

The desktop app supports hierarchy, tabs, source viewing, editing,
saving, search, basic dirty-file status, renderer debugging and Codex chat.
The browser server uses the same Codex chat backend. Review services,
full Git blame/diff integration and unpushed review are not ported to
the desktop host yet.

## Codex chat

Install the Codex CLI on `PATH` and authenticate with `codex login` once.
Zepy runs `codex exec --json` and resumes its saved thread for subsequent turns,
using your CLI authentication and configured model. It does not bundle the CLI
or need an API key of its own. `ZEPY_CODEX_BIN` can select a different CLI binary.
The implementation was checked with Codex CLI 0.163.0 and the
[non-interactive protocol](https://developers.openai.com/codex/noninteractive).

The Codex pane opens by default. Ctrl+Enter sends the message with any pinned
source selection. Messages sent during a turn are queued within the running
app. Tool progress and assistant updates appear while it works; raw tool output
and reasoning are not chat messages. Closing the app stops its active turn;
queued messages are not resumed automatically on restart.

Zepy maintains its own conversation per canonical workspace path under
`$CODEX_HOME/zepy` (normally `~/.codex/zepy`), shared by browser and desktop modes.
It does not take over a session currently running in another Codex interface.
The saved thread ID can also be opened with `codex resume ID` when Zepy is idle.
Only one Zepy process may run a turn for that conversation at a time.
The CLI receives workspace-write sandbox permissions and `approval_policy=never`:
it can edit the workspace, but commands requiring an approval are denied.
Missing CLI/authentication and failed or timed-out turns appear in the chat.

## Installed releases

The PyPI package installs a platform wheel from GitHub Releases using
`wheel-stub`. It contains the complete desktop archive and a standard-library
launcher, with no PyJS runtime dependency. `zepy --install-only` prepares the
local runtime cache and prints its executable path. `zepy --version` reports
the installed release. Source development and browser mode require a checkout.

Linux builds need glibc and the system libraries normally required by Electron,
including GTK, NSS, ALSA, and GBM. A sandbox helper installed under a root-owned
application directory is an alternative when user namespaces are unavailable;
follow your distribution's Electron installation guidance. The launcher does
not disable sandboxing automatically.

macOS application bundles are ad-hoc signed for local execution, not notarized
with an Apple Developer identity. Windows binaries do not carry a Zepy publisher
signature. These are portable desktop distributions, not OS installers.

On Windows, point `ZEPY_CODEX_BIN` to a native Codex executable or the installed
CLI's JavaScript entry file if your shell installation only exposes a `.cmd`
wrapper. JavaScript CLI entry files are run using the bundled Node runtime.
