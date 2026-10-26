# Zepy

Zepy is a Python IDE built with PyJS and Electron.
It has its own editor and WebGPU rendering implementation, written in Python,
and uses PyJS's component model for its UI. The project is in early development.

Zepy runs in stock Electron with a Python-authored UI compiled to JavaScript.
It can browse its own source and debug its compiled Python in a second window.
Standalone desktop bundles run without Python. The PyPI distribution uses a small
Python launcher; the editor and host are already compiled.
See the [desktop guide](zepy/desktop/README.md) for debugging and platform setup.

## Install

With Python 3.14 or newer:

```bash
uv tool install zepy
zepy .
```

`pip install zepy` works too. Installation downloads the matching desktop wheel
from GitHub Releases. The first launch extracts the already installed runtime
into your user cache; it does not download or compile anything. Standalone
archives are also available on the [releases page](https://github.com/pyjs/zepy/releases).

Builds are provided for Linux x64/ARM64, Windows x64, and macOS Intel/Apple Silicon.
Linux requires the desktop system libraries and a working Electron sandbox.
The initial macOS and Windows builds are not notarized or publisher-signed.
See the [desktop guide](zepy/desktop/README.md) for platform requirements.

## File access

The workbench calls a typed workspace client for directory listings, file reads,
saves, and search. Both runtimes use the same workspace service:

- **Electron:** a sandboxed renderer calls a fixed preload API over Electron IPC.
  The main process uses Node filesystem APIs. No HTTP server or Python runtime
  is needed by the packaged app.
- **Browser:** the client calls HTTP routes in `zepy/server/`. The development
  server uses Python filesystem APIs on the machine running that server.

The explorer loads metadata first and reads file contents when opened. Both
paths support text files up to 8 MiB, reject paths outside the workspace,
normalize saved line endings, and skip symlinks in directory listings. Search
returns at most 100 matches. Git review features remain browser-only; the
Electron host currently provides basic dirty-file status.

The browser server is a local development option. It is not an authenticated
remote-workspace service.

## Development setup

Install Python 3.14 or newer, uv, and Node.js/npm. From this checkout:

```bash
uv sync --locked --extra test
```

The lockfile pins the PyJS version used to build and test the application.

## Run in Electron

```bash
uv run pyjs build zepy.app --target electron --electron-host zepy/desktop/host -o dist/zepy
mkdir -p dist/zepy/licenses/zepy
cp LICENSE THIRD_PARTY_NOTICES.md dist/zepy/licenses/zepy/
./dist/zepy/electron --workspace="$PWD"
```

The output directory must be new. The first build downloads stock Electron;
the generated app runs without Python. Linux development runtimes may require
sandbox setup; see the [desktop instructions](zepy/desktop/README.md#linux-sandbox-setup).

## Run in the browser

Build the shared Codex service once, and rebuild it after changing the host
Python sources:

```bash
uv run pyjs build zepy.desktop.host.codex --target node -o .pyjs/desktop/codex.cjs
```

Then start the development server:

```bash
uv run python -m zepy serve
uv run python -m zepy review
uv run python -m zepy review --unpushed
```

The browser development server opens the current Git checkout. A second
`zepy serve` launch in the same checkout prints the existing URL.

Open <http://127.0.0.1:8000/>. Explorer is the map, the center is the file or
a concatenated review diff, Codex is on the right. Source Control toggles
**Dirty** vs **Unpushed**; **Review** opens every change in one buffer. In
that buffer, `]` / `[` move between hunks, `g]` / `g[` between files, Enter
jumps to the full file, `gb` returns to the diff, `u` toggles viewed, and `K`
asks Codex about the hunk. Drag to select lines (or `V` then `K`) to comment
on a range and send it to Codex; an Ask Codex chip appears over the editor.
`gH` opens the HEAD revision in the split (working
tree stays in the primary pane). Long diff lines wrap; `zw` toggles wrap in
any buffer. `-w` ignores whitespace; `U10` widens hunk context. Renames show
as `old -> new [R]`. The review buffer reloads when git changes and keeps
your place in the current file. Select text and send a chat message to
include that selection. The pane retains a Codex conversation for this workspace,
including live tool progress and assistant messages.

Install the Codex CLI and run `codex login` once. Zepy uses your configured
model and saves its own conversation per workspace. The same integration works
in Electron and the browser; see [Codex chat setup](zepy/desktop/README.md#codex-chat).

- Line numbers, current-line highlight, and a caret
- Shift+arrows or click-and-drag to select; Backspace/Delete clear the range.
  A comment bar appears for the selected lines; Ask Codex (or `K`) pins them
  to the chat. Ctrl+Enter sends your note with the numbered snippet.
- Mouse wheel scrolls; Shift+wheel or trackpad X pans long lines. The caret
  stays in view while typing
- Newlines keep the indent of the previous line
- Ctrl/Cmd+C / X / V copy, cut, and paste through the system clipboard
- `za` toggles an indent fold; `zM` closes all; `zR` opens all
- Explorer lists `workspace/` samples and the `zepy/` sources. Git marks
  modified files yellow, new files green, and deleted files red; folders
  take the strongest status of the files inside them. Source Control lists
  Dirty or Unpushed files; click a row or Review for the concatenated diff
- Open files stay in tabs; click a tab to switch, × to close, `gt` / `gT`
  for next / previous
- The Codex pane on the right resumes Zepy's saved conversation for this repo.
  Ctrl+Enter sends; a selection in the editor is attached. Tool calls and
  assistant updates from a live CLI turn show in the pane. The transcript
  follows the live edge unless you scroll up; your own turns pin the
  viewport. Click ✦ to hide it. Drag the divider on the explorer right edge
  or Codex left edge to resize those panes; the widths are remembered.
- Ctrl/Cmd+P quick-opens a file; Ctrl/Cmd+Shift+P opens the command palette;
  Ctrl/Cmd+Shift+F searches files (Enter runs the query, click a hit to open)
- Ctrl/Cmd+\\ splits the editor; click a pane to focus it
- Ctrl/Cmd+S saves the current file; the tab shows ● while dirty
- Disk changes reload the buffer when the tab is clean
- Git gutter marks added, changed, and deleted lines; blame is in the status bar
- Ctrl/Cmd+Z undoes; Ctrl/Cmd+Shift+Z or Ctrl/Cmd+Y redoes
- Python and Markdown files get syntax colors on the GPU glyphs
- Ctrl/Cmd+F opens find; F3 / Shift+F3 (or the arrows) step through matches
- Ctrl/Cmd+H focuses replace; Replace / All (or Enter / Ctrl+Enter) write the buffer
- Vim modes: Escape for NORMAL, `i`/`a`/`o` for INSERT. `hjkl`, `wbe`, `0^$`,
  `gg`/`G`, `gH` (HEAD in split), `f`/`t`/`F`/`T` (`;` / `,`), `%`, `x`,
  `dd`/`yy`/`p`, `J`, `u`, `zw` (wrap),
  `r`/`s`/`S`/`~`/`./`/`>>`/`<<`/`diw`/`ci"`/`ci(`/`di[`, `/` `n` `N` `*`,
  `{` `}`, `zz`/`za`, `m{a-z}` / `` `{a-z} ``, Ctrl-O / Ctrl-I, `"ay` / `"ap`,
  and `v`/`V`/Ctrl-V (visual block) work in NORMAL. `:w` writes the file;
  `:e path` opens one; `:n` / `:N` switch tabs; `:123` goes to a line;
  `:noh` clears search. Arrows, mouse, find, and save still work. The status
  bar shows the mode.

## Test

On POSIX systems, the Node test runner uses `ps` to clean up child processes
after a timeout or interruption (`procps` supplies it on most Linux systems).

```bash
uv run pytest -q
uv run pytest -q --pyjs-target=web --pyjs-browser=managed
uv run pytest -q --pyjs-target=node
```

Zepy is licensed under the [MIT license](LICENSE). Third-party attribution is in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Release builds and publication are documented in [RELEASING.md](RELEASING.md).
