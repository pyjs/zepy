from collections.abc import Callable
from typing import Final

from pyjs import JS, js
from pyjs.javascript import JSON, JSONObject, encodeURIComponent
from pyjs.web.dom import Element, Node, document, localStorage, location, window
from pyjs.web.domx import CustomElement, button, canvas, div, input, ref, tag, textarea, tw
from pyjs.web.events import Event, KeyboardEvent, MouseEvent
from pyjs.web.html import HTMLCanvasElement, HTMLElement
from pyjs.web.timers import setInterval
from pyjs.web.ui.button import ButtonGroup
from pyjs.web.ui.command import Command, CommandItem, CommandShortcut
from pyjs.web.ui.input_group import InputGroup, InputGroupAddon
from pyjs.web.ui.message_scroller import MessageScroller
from pyjs.web.ui.resizable import ResizableHandle

from zepy.desktop.api import fetch, is_desktop
from zepy.editor.browser.gpu_text_editor import (
    GpuTextEditor,
    HistoryStep,
    create_gpu_text_editor,
)
from zepy.editor.common.comment import line_span_label, numbered_snippet
from zepy.editor.common.core.position import Position
from zepy.editor.common.review_nav import (
    extract_hunk,
    locate_review_target,
    next_hunk_line,
    next_review_header_line,
)
from zepy.editor.common.vim import (
    MODE_COMMAND,
    MODE_INSERT,
    MODE_VISUAL,
    MODE_VISUAL_BLOCK,
    MODE_VISUAL_LINE,
)
from zepy.services.client import read_file, search_files, workspace_tree, write_file
from zepy.services.types import FileEntry
from zepy.workbench_chat import ChatLine, sync_chat_log

SCROLL_CSS: Final[JS] = (
    "[data-scroll='theme']{scrollbar-width:thin;scrollbar-color:#4e4e4e #252526;}"
    "[data-scroll='theme']::-webkit-scrollbar{width:10px;height:10px;}"
    "[data-scroll='theme']::-webkit-scrollbar-track{background:#252526;}"
    "[data-scroll='theme']::-webkit-scrollbar-thumb{"
    "background:#4e4e4e;border-radius:6px;border:2px solid #252526;}"
    "[data-scroll='theme']::-webkit-scrollbar-thumb:hover{background:#6a6a6a;}"
    "[data-scroll='theme']::-webkit-scrollbar-corner{background:#252526;}"
    "[data-testid='chat-composer']{"
    "background:#3c3c3c;border-color:#555555;box-shadow:none;}"
    "[data-testid='chat-input']{color:#d4d4d4;}"
    "[data-testid='chat-input']::placeholder{color:#c8c8c8;opacity:1;}"
    "[data-testid='explorer-scroll'],"
    "[data-testid='scm-scroll'],"
    "[data-testid='chat-log'] [data-slot='message-scroller-viewport']{"
    "overflow-y:scroll;}"
)


class DebugBreakAsk(JSONObject):
    path: str
    line: int


class DebugFrame(JSONObject):
    name: str
    path: str
    line: int


class DebugVariable(JSONObject):
    name: str
    value: str


class DebugBreakpoint(JSONObject):
    path: str
    line: int
    resolved: int


class DebugState(JSONObject):
    running: bool
    paused: bool
    frames: list[DebugFrame]
    variables: list[DebugVariable]
    breakpoints: list[DebugBreakpoint]
    revision: int
    error: str


class GitMark(JSONObject):
    line: int
    kind: str


class GitBlameLine(JSONObject):
    line: int
    author: str
    summary: str


class GitPayload(JSONObject):
    path: str
    gutter: list[GitMark]
    blame: list[GitBlameLine]


class GitStatusItem(JSONObject):
    path: str
    git: str
    plus: int
    minus: int


class GitStatusPayload(JSONObject):
    scope: str
    tree: list[GitStatusItem]
    changes: list[GitStatusItem]
    plus: int
    minus: int
    stamp: str


class ReviewFile(JSONObject):
    path: str
    git: str
    start_line: int
    end_line: int
    plus: int
    minus: int
    orig: str


class ReviewPayload(JSONObject):
    path: str
    content: str
    scope: str
    files: list[ReviewFile]
    viewed: list[str]
    plus: int
    minus: int
    stamp: str


class GitDiffPayload(JSONObject):
    path: str
    scope: str
    content: str
    git: str


class ViewedAsk(JSONObject):
    path: str
    viewed: bool


class ChatHistoryPayload(JSONObject):
    session_id: str
    messages: list[ChatLine]
    idle: bool
    stamp: str
    queued: int
    partial: str


class ChatAsk(JSONObject):
    text: str
    path: str
    selection: str
    line: int
    end_line: int
    flush: bool


class LineComment(JSONObject):
    path: str
    text: str
    line: int
    end_line: int
    snippet: str


class ChatReply(JSONObject):
    session_id: str
    text: str
    queued: bool
    idle: bool


@js
class OpenTab:
    def __init__(self, path: str, name: str, content: str, saved: str):
        self.path = path
        self.name = name
        self.content = content
        self.saved = saved
        self.line = 1
        self.column = 1
        self.undo: list[HistoryStep] = []
        self.redo: list[HistoryStep] = []


@js
class App(CustomElement):
    debug_revision: int
    debug_busy: bool
    editor: GpuTextEditor | None
    editor_b: GpuTextEditor | None
    primary: GpuTextEditor | None
    entries: list[FileEntry]
    collapsed: list[str]
    saved_content: str
    tab_name: str
    tabs: list[OpenTab]
    active_tab: int
    split_open: bool
    focused_split: int
    quick_hits: list[int]
    quick_index: int
    poll_busy: bool
    git_changes: list[GitStatusItem]
    sidebar_view: str
    chat_messages: list[ChatLine]
    chat_session: str
    chat_busy: bool
    chat_open: bool
    git_scope: str
    review_files: list[ReviewFile]
    viewed_paths: list[str]
    chat_stamp: str
    hide_ws: bool
    review_wide: bool
    review_plus: int
    review_minus: int
    review_return_line: int
    review_return_path: str
    git_stamp: str
    chat_partial: str
    chat_idle: bool
    sidebar_width: int
    chat_width: int
    drag_kind: str
    drag_origin: int
    drag_start_width: int
    comment_path: str
    comment_snippet: str
    comment_start: int
    comment_end: int
    comment_held: bool
    search_query: str
    chat_rendered_count: int
    chat_rendered_partial: str

    def __init__(self, tree_json: str = "[]"):
        super().__init__()
        self.editor = None
        self.editor_b = None
        self.primary = None
        loaded: list[FileEntry] = JSON.parse(tree_json)
        self.entries = loaded
        self.collapsed = []
        self.saved_content = ""
        self.tab_name = "untitled"
        self.tabs = []
        self.active_tab = -1
        self.split_open = False
        self.focused_split = 0
        self.quick_hits = []
        self.quick_index = 0
        self.poll_busy = False
        self.git_changes = []
        self.sidebar_view = "explorer"
        self.chat_messages = []
        self.chat_session = ""
        self.chat_busy = False
        self.chat_open = True
        self.git_scope = "dirty"
        self.review_files = []
        self.viewed_paths = []
        self.chat_stamp = ""
        self.hide_ws = False
        self.review_wide = False
        self.review_plus = 0
        self.review_minus = 0
        self.review_return_line = 0
        self.review_return_path = ""
        self.git_stamp = ""
        self.chat_partial = ""
        self.chat_idle = True
        self.sidebar_width = 240
        self.chat_width = 320
        self.drag_kind = ""
        self.drag_origin = 0
        self.drag_start_width = 0
        self.comment_path = ""
        self.comment_snippet = ""
        self.comment_start = 0
        self.comment_end = 0
        self.comment_held = False
        self.search_query = ""
        self.chat_rendered_count = -1
        self.chat_rendered_partial = ""
        self.title_label = ref(tag("span", tw("text-xs tracking-wide text-zinc-400"), "ZEPY"))
        self.tab_label = ref(
            tag(
                "span",
                tw("text-xs text-zinc-200"),
                {"data-testid": "tab-label", "data-dirty": "false", "hidden": ""},
                "untitled",
            )
        )
        self.tab_strip = ref(
            div(
                tw("flex h-full min-w-0 flex-1 items-stretch overflow-x-auto"),
                {"data-testid": "tabs", "data-scroll": "theme"},
            )
        )
        self.debug_revision = -1
        self.debug_busy = False
        self.debug_toggle = ref(button(
            tw("flex h-10 w-10 items-center justify-center text-xs text-zinc-200"),
            {"data-testid": "activity-debug", "title": "Run and debug Python", "hidden": ""}, "▷",
        ))
        self.debug_start = ref(button({"data-testid": "debug-start"}, "Start Zepy"))
        self.debug_break = ref(button({"data-testid": "debug-breakpoint"}, "Toggle breakpoint at cursor"))
        self.debug_continue = ref(button({"data-testid": "debug-continue"}, "Continue"))
        self.debug_step = ref(button({"data-testid": "debug-step"}, "Step over"))
        self.debug_into = ref(button({"data-testid": "debug-into"}, "Step into"))
        self.debug_out = ref(button({"data-testid": "debug-out"}, "Step out"))
        self.debug_pause = ref(button({"data-testid": "debug-pause"}, "Pause"))
        self.debug_stop = ref(button({"data-testid": "debug-stop"}, "Stop"))
        self.debug_status = ref(tag("div", tw("px-3 py-1 text-xs text-zinc-200"),
            {"data-testid": "debug-status"}, "Set a breakpoint in Python, then start a second Zepy window."))
        self.debug_frames = ref(tag("div", tw("min-w-0 flex-1 overflow-auto px-3"), {"data-testid": "debug-frames", "data-scroll": "theme"}))
        self.debug_variables = ref(tag("div", tw("min-w-0 flex-1 overflow-auto px-3"), {"data-testid": "debug-variables", "data-scroll": "theme"}))
        self.debug_breakpoints = ref(tag("div", tw("min-w-0 flex-1 overflow-auto px-3"), {"data-testid": "debug-breakpoints", "data-scroll": "theme"}))
        self.debug_panel = ref(tag("section", tw("flex h-56 shrink-0 flex-col border-t border-zinc-700 bg-[#252526] text-xs text-zinc-200"),
            {"data-testid": "debug-panel", "hidden": ""},
            tag("div", tw("flex flex-wrap gap-3 border-b border-zinc-700 px-3 py-2 [&>button]:rounded [&>button]:px-1 [&>button:hover]:bg-zinc-600"),
                self.debug_start, self.debug_break, self.debug_continue, self.debug_step,
                self.debug_into, self.debug_out, self.debug_pause, self.debug_stop),
            self.debug_status,
            tag("div", tw("flex min-h-0 flex-1 gap-2 pb-2"), self.debug_frames, self.debug_variables, self.debug_breakpoints),
        ))
        self.debug_toggle.addEventListener("click", self.toggle_debug)
        self.debug_start.addEventListener("click", self.start_debug)
        self.debug_break.addEventListener("click", self.break_debug)
        self.debug_continue.addEventListener("click", self.continue_debug)
        self.debug_step.addEventListener("click", self.step_debug)
        self.debug_into.addEventListener("click", self.into_debug)
        self.debug_out.addEventListener("click", self.out_debug)
        self.debug_pause.addEventListener("click", self.pause_debug)
        self.debug_stop.addEventListener("click", self.stop_debug)
        self.debug_frames.addEventListener("click", self.debug_frame_click)
        self.status_mode = ref(tag("span", {"data-testid": "vim-mode"}, "NORMAL"))
        self.status_cursor = ref(tag("span", "Ln 1, Col 1"))
        self.status_file = ref(tag("span", "plaintext"))
        self.status_git = ref(tag("span", {"data-testid": "git-blame"}, ""))
        self.status_scope = ref(tag("span", {"data-testid": "review-scope"}, "dirty"))
        self.tree_list = ref(
            div(
                tw("flex flex-col gap-0.5 px-1 py-1"),
                {"data-testid": "explorer"},
                *self._visible_buttons(),
            )
        )
        self.stage = ref(
            canvas(
                {
                    "width": "960",
                    "height": "640",
                    "data-testid": "editor-canvas",
                    "style": (
                        "display:block; width:100%; height:100%; background:#1e1e1e; cursor:text"
                    ),
                }
            )
        )
        self.input = ref(
            textarea(
                {
                    "spellcheck": "false",
                    "autocomplete": "off",
                    "autocapitalize": "off",
                    "data-testid": "editor-input",
                    "style": (
                        "position:absolute; inset:0; width:100%; height:100%; "
                        "opacity:0; resize:none; margin:0; border:0; padding:0; "
                        "overflow:hidden; background:transparent; color:transparent; "
                        "caret-color:transparent; outline:none; font:16px monospace"
                    ),
                }
            )
        )
        self.vthumb = ref(
            div(
                tw(
                    "absolute right-0 w-[10px] rounded-sm bg-[#4e4e4e] hover:bg-[#6a6a6a]"
                ),
                {"data-testid": "editor-vthumb"},
            )
        )
        self.vscroll = ref(
            div(
                tw("absolute right-0 top-0 z-20 h-full w-[10px] bg-[#1e1e1e]"),
                {"data-testid": "editor-vscroll"},
                self.vthumb,
            )
        )
        self.hthumb = ref(
            div(
                tw(
                    "absolute bottom-0 h-[10px] rounded-sm bg-[#4e4e4e] hover:bg-[#6a6a6a]"
                ),
                {"data-testid": "editor-hthumb"},
            )
        )
        self.hscroll = ref(
            div(
                tw("absolute bottom-0 left-0 z-20 h-[10px] bg-[#1e1e1e]"),
                {
                    "data-testid": "editor-hscroll",
                    "style": "right:10px",
                },
                self.hthumb,
            )
        )
        self.pane = ref(
            div(
                tw("relative min-h-0 min-w-0 flex-1"),
                {"data-testid": "editor-pane"},
                self.stage,
                self.input,
                self.vscroll,
                self.hscroll,
            )
        )
        self.stage_b = ref(
            canvas(
                {
                    "width": "480",
                    "height": "640",
                    "data-testid": "editor-canvas-b",
                    "style": (
                        "display:block; width:100%; height:100%; background:#1e1e1e; cursor:text"
                    ),
                }
            )
        )
        self.input_b = ref(
            textarea(
                {
                    "spellcheck": "false",
                    "autocomplete": "off",
                    "autocapitalize": "off",
                    "data-testid": "editor-input-b",
                    "style": (
                        "position:absolute; inset:0; width:100%; height:100%; "
                        "opacity:0; resize:none; margin:0; border:0; padding:0; "
                        "overflow:hidden; background:transparent; color:transparent; "
                        "caret-color:transparent; outline:none; font:16px monospace"
                    ),
                }
            )
        )
        self.vthumb_b = ref(
            div(
                tw(
                    "absolute right-0 w-[10px] rounded-sm bg-[#4e4e4e] hover:bg-[#6a6a6a]"
                ),
                {"data-testid": "editor-vthumb-b"},
            )
        )
        self.vscroll_b = ref(
            div(
                tw("absolute right-0 top-0 z-20 h-full w-[10px] bg-[#1e1e1e]"),
                {"data-testid": "editor-vscroll-b"},
                self.vthumb_b,
            )
        )
        self.hthumb_b = ref(
            div(
                tw(
                    "absolute bottom-0 h-[10px] rounded-sm bg-[#4e4e4e] hover:bg-[#6a6a6a]"
                ),
                {"data-testid": "editor-hthumb-b"},
            )
        )
        self.hscroll_b = ref(
            div(
                tw("absolute bottom-0 left-0 z-20 h-[10px] bg-[#1e1e1e]"),
                {
                    "data-testid": "editor-hscroll-b",
                    "style": "right:10px",
                },
                self.hthumb_b,
            )
        )
        self.pane_b = ref(
            div(
                tw("relative min-h-0 min-w-0 flex-1 border-l border-zinc-800"),
                {"data-testid": "editor-pane-b"},
                self.stage_b,
                self.input_b,
                self.vscroll_b,
                self.hscroll_b,
            )
        )
        self.pane_b.setAttribute("hidden", "")
        self.find_field = ref(
            input(
                {
                    "type": "text",
                    "placeholder": "Find",
                    "data-testid": "find-input",
                    "style": (
                        "width:12rem;border:1px solid #3c3c3c;background:#3c3c3c;"
                        "color:#cccccc;padding:2px 8px;font:12px monospace;outline:none"
                    ),
                }
            )
        )
        self.find_count = ref(
            tag(
                "span",
                tw("min-w-[4.5rem] px-1 text-[11px] text-zinc-400"),
                {"data-testid": "find-count"},
                "No results",
            )
        )
        self.find_prev_button = ref(
            button(
                tw("px-1.5 text-xs text-zinc-300 hover:bg-zinc-700"),
                {"type": "button", "data-testid": "find-prev", "title": "Previous match"},
                "↑",
            )
        )
        self.find_next_button = ref(
            button(
                tw("px-1.5 text-xs text-zinc-300 hover:bg-zinc-700"),
                {"type": "button", "data-testid": "find-next", "title": "Next match"},
                "↓",
            )
        )
        self.find_close_button = ref(
            button(
                tw("px-1.5 text-xs text-zinc-300 hover:bg-zinc-700"),
                {"type": "button", "data-testid": "find-close", "title": "Close"},
                "×",
            )
        )
        self.replace_field = ref(
            input(
                {
                    "type": "text",
                    "placeholder": "Replace",
                    "data-testid": "replace-input",
                    "style": (
                        "width:12rem;border:1px solid #3c3c3c;background:#3c3c3c;"
                        "color:#cccccc;padding:2px 8px;font:12px monospace;outline:none"
                    ),
                }
            )
        )
        self.replace_button = ref(
            button(
                tw("px-1.5 text-[11px] text-zinc-300 hover:bg-zinc-700"),
                {"type": "button", "data-testid": "replace-one"},
                "Replace",
            )
        )
        self.replace_all_button = ref(
            button(
                tw("px-1.5 text-[11px] text-zinc-300 hover:bg-zinc-700"),
                {"type": "button", "data-testid": "replace-all"},
                "All",
            )
        )
        self.comment_label = ref(
            tag(
                "span",
                tw("px-1 text-[11px] text-zinc-300"),
                {"data-testid": "comment-range"},
                "",
            )
        )
        self.comment_ask = ref(
            button(
                tw("rounded px-1.5 text-[11px] text-zinc-100 bg-[#0e639c] hover:bg-[#1177bb]"),
                {
                    "type": "button",
                    "data-testid": "comment-ask",
                    "title": "Ask Codex about these lines",
                },
                "Ask Codex",
            )
        )
        self.comment_clear = ref(
            button(
                tw("px-1.5 text-xs text-zinc-300 hover:bg-zinc-700"),
                {
                    "type": "button",
                    "data-testid": "comment-clear",
                    "title": "Clear selection comment",
                },
                "×",
            )
        )
        self.comment_bar = ref(
            div(
                tw(
                    "absolute left-3 top-2 z-10 flex items-center gap-1 rounded "
                    "border border-zinc-700 bg-[#252526] px-2 py-1 shadow-md"
                ),
                {"data-testid": "comment-bar"},
                self.comment_label,
                self.comment_ask,
                self.comment_clear,
            )
        )
        self.comment_chip_label = ref(
            tag("span", tw("truncate"), {"data-testid": "comment-chip-label"}, "")
        )
        self.comment_chip_clear = ref(
            button(
                tw("px-1 text-[10px] text-zinc-400 hover:text-zinc-200"),
                {"type": "button", "data-testid": "comment-chip-clear"},
                "×",
            )
        )
        self.comment_chip = ref(
            div(
                tw(
                    "mb-1 flex items-center justify-between gap-1 rounded "
                    "bg-[#3c3c3c] px-2 py-1 text-[10px] text-zinc-300"
                ),
                {"data-testid": "comment-chip"},
                self.comment_chip_label,
                self.comment_chip_clear,
            )
        )
        self.find_bar = ref(
            div(
                tw(
                    "absolute right-3 top-2 z-10 flex flex-col gap-1 rounded "
                    "border border-zinc-700 bg-[#252526] px-2 py-1 shadow-md"
                ),
                {"data-testid": "find-widget"},
                div(
                    tw("flex items-center gap-1"),
                    self.find_field,
                    self.find_count,
                    self.find_prev_button,
                    self.find_next_button,
                    self.find_close_button,
                ),
                div(
                    tw("flex items-center gap-1"),
                    self.replace_field,
                    self.replace_button,
                    self.replace_all_button,
                ),
            )
        )
        self.activity_explorer = ref(
            tag(
                "span",
                tw(
                    "flex h-10 w-10 items-center justify-center border-l-2 "
                    "border-transparent text-sm text-zinc-500 "
                    "data-[active=true]:border-zinc-100 data-[active=true]:text-zinc-100"
                ),
                {
                    "title": "Explorer",
                    "data-testid": "activity-explorer",
                    "data-active": "true",
                },
                "☰",
            )
        )
        self.activity_scm = ref(
            tag(
                "span",
                tw(
                    "flex h-10 w-10 items-center justify-center border-l-2 "
                    "border-transparent text-sm text-zinc-500 "
                    "data-[active=true]:border-zinc-100 data-[active=true]:text-zinc-100"
                ),
                {
                    "title": "Source Control",
                    "data-testid": "activity-scm",
                    "data-active": "false",
                },
                "⎇",
            )
        )
        self.activity_search = ref(
            tag(
                "span",
                tw("flex h-10 w-10 items-center justify-center text-sm text-zinc-500"),
                {"title": "Search", "data-testid": "activity-search"},
                "⌕",
            )
        )
        self.activity_chat = ref(
            tag(
                "span",
                tw(
                    "flex h-10 w-10 items-center justify-center border-l-2 "
                    "border-transparent text-sm text-zinc-500 "
                    "data-[active=true]:border-zinc-100 data-[active=true]:text-zinc-100"
                ),
                {
                    "title": "Codex",
                    "data-testid": "activity-chat",
                    "data-active": "true",
                },
                "✦",
            )
        )
        self.sidebar_title = ref(
            tag(
                "div",
                tw("px-4 py-2 text-[10px] font-semibold uppercase tracking-widest text-zinc-400"),
                {"data-testid": "sidebar-title"},
                "Explorer",
            )
        )
        self.scm_list = ref(
            div(
                tw("flex flex-col gap-0.5 px-1 py-1"),
                {"data-testid": "scm-list"},
            )
        )
        self.scope_dirty = ref(
            button(
                tw(
                    "rounded px-2 py-0.5 text-[11px] text-zinc-400 "
                    "data-[active=true]:bg-[#37373d] data-[active=true]:text-zinc-100"
                ),
                {
                    "type": "button",
                    "data-slot": "button",
                    "data-testid": "scope-dirty",
                    "data-active": "true",
                },
                "Dirty",
            )
        )
        self.scope_unpushed = ref(
            button(
                tw(
                    "rounded px-2 py-0.5 text-[11px] text-zinc-400 "
                    "data-[active=true]:bg-[#37373d] data-[active=true]:text-zinc-100"
                ),
                {
                    "type": "button",
                    "data-slot": "button",
                    "data-testid": "scope-unpushed",
                    "data-active": "false",
                },
                "Unpushed",
            )
        )
        self.review_all = ref(
            button(
                tw("rounded px-2 py-0.5 text-[11px] text-zinc-200 hover:bg-zinc-700"),
                {"type": "button", "data-slot": "button", "data-testid": "review-all"},
                "Review",
            )
        )
        self.hide_ws_button = ref(
            button(
                tw(
                    "rounded px-2 py-0.5 text-[11px] text-zinc-400 "
                    "data-[active=true]:bg-[#37373d] data-[active=true]:text-zinc-100"
                ),
                {
                    "type": "button",
                    "data-slot": "button",
                    "data-testid": "hide-ws",
                    "data-active": "false",
                },
                "-w",
            )
        )
        self.wide_button = ref(
            button(
                tw(
                    "rounded px-2 py-0.5 text-[11px] text-zinc-400 "
                    "data-[active=true]:bg-[#37373d] data-[active=true]:text-zinc-100"
                ),
                {
                    "type": "button",
                    "data-slot": "button",
                    "data-testid": "review-wide",
                    "data-active": "false",
                },
                "U10",
            )
        )
        self.explorer_pane = ref(
            div(
                tw("min-h-0 flex-1 overflow-hidden"),
                {"data-testid": "explorer-pane"},
                div(
                    tw("h-full min-h-0 overflow-y-scroll"),
                    {"data-testid": "explorer-scroll", "data-scroll": "theme"},
                    self.tree_list,
                ),
            )
        )
        self.scm_pane = ref(
            div(
                tw("flex min-h-0 flex-1 flex-col overflow-hidden"),
                {"data-testid": "scm-pane"},
                tag(
                    "div",
                    tw("border-b border-zinc-800 px-2 py-1"),
                    ButtonGroup(
                        self.scope_dirty,
                        self.scope_unpushed,
                        self.review_all,
                        self.hide_ws_button,
                        self.wide_button,
                    ),
                ),
                div(
                    tw("min-h-0 flex-1 overflow-y-scroll"),
                    {"data-testid": "scm-scroll", "data-scroll": "theme"},
                    self.scm_list,
                ),
            )
        )
        self.chat_log = ref(
            MessageScroller(
                label="Codex",
                auto_scroll=True,
            )
        )
        self.chat_log.setAttribute("data-testid", "chat-log")
        self.chat_log.setAttribute("style", "flex:1;min-height:0")
        self.chat_input = ref(
            textarea(
                {
                    "data-testid": "chat-input",
                    "data-slot": "input-group-control",
                    "placeholder": "Ask Codex about this file…",
                    "style": (
                        "width:100%;min-height:4.5rem;resize:none;border:0;"
                        "background:transparent;color:#d4d4d4;padding:8px;"
                        "font:12px sans-serif;outline:none"
                    ),
                }
            )
        )
        self.chat_send = ref(
            button(
                tw("rounded px-2 py-1 text-[11px] text-zinc-100 bg-[#0e639c] hover:bg-[#1177bb]"),
                {"type": "button", "data-testid": "chat-send"},
                "Send",
            )
        )
        self.chat_composer = ref(
            InputGroup(
                self.chat_input,
                InputGroupAddon(self.chat_send, align="block-end"),
            )
        )
        self.chat_composer.setAttribute("data-testid", "chat-composer")
        self.chat_status = ref(
            tag(
                "div", tw("px-2 py-1 text-[10px] text-zinc-500"), {"data-testid": "chat-status"}, ""
            )
        )
        self.chat_pane = ref(
            tag(
                "aside",
                tw("flex min-h-0 shrink-0 flex-col overflow-hidden bg-[#252526]"),
                {"data-testid": "chat-pane"},
                tag(
                    "div",
                    tw(
                        "px-3 py-2 text-[10px] font-semibold uppercase tracking-widest "
                        "text-zinc-400"
                    ),
                    "Codex",
                ),
                self.chat_log,
                self.chat_status,
                tag(
                    "div",
                    tw("border-t border-zinc-800 p-2"),
                    self.comment_chip,
                    self.chat_composer,
                ),
            )
        )
        self.sidebar = ref(
            tag(
                "aside",
                tw("flex min-h-0 shrink-0 flex-col overflow-hidden bg-[#252526]"),
                {"data-testid": "sidebar"},
                self.sidebar_title,
                self.explorer_pane,
                self.scm_pane,
            )
        )
        sidebar_handle = ResizableHandle()
        sidebar_handle.setAttribute("data-testid", "sidebar-split")
        sidebar_handle.setAttribute("title", "Resize sidebar")
        sidebar_handle.setAttribute("data-direction", "horizontal")
        self.sidebar_split = ref(sidebar_handle.element)
        chat_handle = ResizableHandle()
        chat_handle.setAttribute("data-testid", "chat-split")
        chat_handle.setAttribute("title", "Resize Codex")
        chat_handle.setAttribute("data-direction", "horizontal")
        self.chat_split = ref(chat_handle.element)
        self._apply_pane_widths()
        self.tree_list.addEventListener("click", self.on_tree_click)
        self.tab_strip.addEventListener("click", self.on_tab_click)
        self.find_field.addEventListener("input", self.on_find_input)
        self.find_field.addEventListener("keydown", self.on_find_keydown)
        self.find_prev_button.addEventListener("click", self.on_find_prev)
        self.find_next_button.addEventListener("click", self.on_find_next)
        self.find_close_button.addEventListener("click", self.on_find_close)
        self.replace_field.addEventListener("keydown", self.on_replace_keydown)
        self.replace_button.addEventListener("click", self.on_replace_one)
        self.replace_all_button.addEventListener("click", self.on_replace_all)
        self.activity_search.addEventListener("click", self.on_find)
        self.activity_explorer.addEventListener("click", self.show_explorer)
        self.activity_scm.addEventListener("click", self.show_scm)
        self.activity_chat.addEventListener("click", self.toggle_chat)
        self.chat_send.addEventListener("click", self.on_chat_send)
        self.chat_input.addEventListener("keydown", self.on_chat_keydown)
        self.scm_list.addEventListener("click", self.on_scm_click)
        self.scope_dirty.addEventListener("click", self.on_scope_dirty)
        self.scope_unpushed.addEventListener("click", self.on_scope_unpushed)
        self.review_all.addEventListener("click", self.on_review_all)
        self.hide_ws_button.addEventListener("click", self.on_toggle_ws)
        self.wide_button.addEventListener("click", self.on_toggle_wide)
        self.sidebar_split.addEventListener("mousedown", self.on_sidebar_split_down)
        self.chat_split.addEventListener("mousedown", self.on_chat_split_down)
        document.addEventListener("mousemove", self.on_split_move)
        document.addEventListener("mouseup", self.on_split_up)
        self.scm_pane.setAttribute("hidden", "")
        self.find_bar.setAttribute("hidden", "")
        self.comment_bar.setAttribute("hidden", "")
        self.comment_chip.setAttribute("hidden", "")
        self.comment_ask.addEventListener("click", self.on_comment_ask)
        self.comment_clear.addEventListener("click", self.on_comment_clear)
        self.comment_chip_clear.addEventListener("click", self.on_comment_clear)
        self.command_text = ref(
            tag("span", tw("font-mono text-xs text-zinc-200"), {"data-testid": "vim-command"}, ":")
        )
        self.command_bar = ref(
            div(
                tw(
                    "absolute bottom-0 left-0 right-0 z-10 flex items-center "
                    "border-t border-zinc-700 bg-[#1e1e1e] px-2 py-0.5"
                ),
                {"data-testid": "vim-command-bar"},
                self.command_text,
            )
        )
        self.command_bar.setAttribute("hidden", "")
        self.command_palette = ref(
            Command(
                self._palette_command_item(0),
                self._palette_command_item(1),
                self._palette_command_item(2),
                self._palette_command_item(3),
                self._palette_command_item(4),
                self._palette_command_item(5),
                self._palette_command_item(6),
                self._palette_command_item(7),
                self._palette_command_item(8),
                self._palette_command_item(9),
                self._palette_command_item(10),
                placeholder="Run command",
            )
        )
        self.command_palette.input.setAttribute("data-testid", "palette-input")
        self.palette = ref(
            div(
                tw("absolute left-4 top-12 z-20 w-96 shadow-lg"),
                {"data-testid": "palette"},
                self.command_palette,
            )
        )
        self.search_command = ref(
            Command(
                placeholder="Search files",
                enter_selects=False,
            )
        )
        self.search_command.input.setAttribute("data-testid", "search-input")
        self.search_command.empty.textContent = "Press Enter to search"
        self.search_panel = ref(
            div(
                tw("absolute left-4 top-12 z-20 w-[28rem] shadow-lg"),
                {"data-testid": "search-panel"},
                self.search_command,
            )
        )
        self.palette_hits: list[int] = []
        self.palette_index = 0
        self.command_palette.addEventListener("command-select", self.on_palette_select)
        self.command_palette.addEventListener("command-cancel", self.on_palette_cancel)
        self.search_command.addEventListener("command-submit", self.on_search_submit)
        self.search_command.addEventListener("command-select", self.on_search_select)
        self.search_command.addEventListener("command-cancel", self.on_search_cancel)
        self.quick_command = ref(Command(placeholder="Open file"))
        self.quick_command.input.setAttribute("data-testid", "quick-open-input")
        self.quick_panel = ref(
            div(
                tw("absolute left-4 top-12 z-20 w-[28rem] shadow-lg"),
                {"data-testid": "quick-open"},
                self.quick_command,
            )
        )
        self.quick_command.addEventListener("command-select", self.on_quick_select)
        self.quick_command.addEventListener("command-cancel", self.on_quick_cancel)
        self.palette.setAttribute("hidden", "")
        self.search_panel.setAttribute("hidden", "")
        self.quick_panel.setAttribute("hidden", "")
        tag(
            self,
            tw("flex h-screen min-h-0 flex-col bg-[#1e1e1e] text-zinc-200 font-sans"),
            tag("style", SCROLL_CSS),
            tag(
                "header",
                tw(
                    "flex h-9 shrink-0 items-center justify-between border-b "
                    "border-zinc-800 bg-[#3c3c3c] px-3"
                ),
                self.title_label,
                tag("span", tw("text-[10px] uppercase tracking-widest text-zinc-500"), "PyJS"),
            ),
            tag(
                "div",
                tw("flex min-h-0 flex-1 overflow-hidden"),
                tag(
                    "nav",
                    tw(
                        "flex w-12 shrink-0 flex-col items-center gap-1 border-r "
                        "border-zinc-800 bg-[#333333] py-2"
                    ),
                    {"aria-label": "Activity bar"},
                    self.activity_explorer,
                    self.activity_scm,
                    self.activity_search,
                    self.activity_chat,
                    self.debug_toggle,
                ),
                self.sidebar,
                self.sidebar_split,
                tag(
                    "section",
                    tw("flex min-w-0 min-h-0 flex-1 flex-col bg-[#1e1e1e]"),
                    tag(
                        "div",
                        tw("flex h-9 shrink-0 items-center border-b border-zinc-800 bg-[#2d2d2d]"),
                        self.tab_strip,
                        self.tab_label,
                    ),
                    tag(
                        "div",
                        tw("relative min-h-0 flex-1"),
                        tag(
                            "div",
                            tw("flex h-full min-h-0 min-w-0"),
                            self.pane,
                            self.pane_b,
                        ),
                        self.find_bar,
                        self.comment_bar,
                        self.command_bar,
                        self.palette,
                        self.search_panel,
                        self.quick_panel,
                    ),
                    self.debug_panel,
                ),
                self.chat_split,
                self.chat_pane,
            ),
            tag(
                "footer",
                tw(
                    "relative z-10 flex h-6 shrink-0 items-center justify-between border-t "
                    "border-zinc-800 bg-[#007acc] px-3 text-[11px] text-white"
                ),
                {"data-testid": "status-bar"},
                tag(
                    "span",
                    tw("flex gap-3"),
                    self.status_mode,
                    self.status_cursor,
                ),
                tag(
                    "span",
                    tw("flex gap-4"),
                    self.status_scope,
                    self.status_git,
                    self.status_file,
                    tag("span", "UTF-8"),
                ),
            ),
        )

    def toggle_debug(self, event: Event) -> None:
        if self.debug_panel.hasAttribute("hidden"):
            self.debug_panel.removeAttribute("hidden")
        else:
            self.debug_panel.setAttribute("hidden", "")
        self._resize_editors()

    async def _debug_request(self, route: str, body: str = "") -> None:
        response = await fetch("/api/debug/" + route, {"method": "POST", "body": body})
        text = await response.text()
        if not response.ok:
            self.debug_status.textContent = text
            return
        state: DebugState = JSON.parse(text)
        if state["revision"] == self.debug_revision:
            return
        self.debug_revision = state["revision"]
        status = "Ready — set a Python breakpoint, then start Zepy."
        if state["running"]:
            status = "Running — use the second Zepy window to trigger your breakpoint."
        if state["paused"]:
            status = "Paused in Python — inspect locals or step through the source."
        if state["error"] != "":
            status = state["error"]
        self.debug_status.textContent = status
        self.debug_frames.replaceChildren(tag("div", tw("mb-1 font-semibold"), "Call stack"))
        self.debug_variables.replaceChildren(tag("div", tw("mb-1 font-semibold"), "Local variables"))
        self.debug_breakpoints.replaceChildren(tag("div", tw("mb-1 font-semibold"), "Python breakpoints"))
        for frame in state["frames"]:
            self.debug_frames.append(button(tw("block w-full truncate py-0.5 text-left hover:bg-zinc-700"),
                {"data-path": frame["path"], "data-line": str(frame["line"])},
                frame["name"] + " — " + frame["path"] + ":" + str(frame["line"])))
        for variable in state["variables"]:
            self.debug_variables.append(tag("div", tw("break-all py-0.5"), variable["name"] + " = " + variable["value"]))
        for breakpoint in state["breakpoints"]:
            self.debug_breakpoints.append(tag("div", tw("break-all py-0.5"),
                "● " + breakpoint["path"] + ":" + str(breakpoint["resolved"])))
        if state["paused"] and len(state["frames"]) > 0:
            frame = state["frames"][0]
            if frame["path"] != "" and not frame["path"].startswith(".."):
                await self._debug_reveal(frame["path"], frame["line"])

    async def _debug_reveal(self, path: str, line: int) -> None:
        await self.open_path(path)
        if self.editor is not None:
            self.editor.set_cursor(Position(line, 1), False)
            self.editor._center_cursor()
            self.sync_status()

    async def debug_frame_click(self, event: Event) -> None:
        item = self._tree_item_from_event(event)
        if item is None:
            return
        path = item.getAttribute("data-path")
        line = item.getAttribute("data-line")
        if path is not None and path != "" and line is not None and not path.startswith(".."):
            await self._debug_reveal(path, int(line))

    async def start_debug(self, event: Event) -> None:
        await self._debug_request("start")

    async def break_debug(self, event: Event) -> None:
        if self.editor is not None:
            await self._debug_request("breakpoint", JSON.stringify(DebugBreakAsk(path=self.editor.path, line=self.editor.cursor.line_number)))

    async def continue_debug(self, event: Event) -> None:
        await self._debug_request("action", '{"action":"continue"}')

    async def step_debug(self, event: Event) -> None:
        await self._debug_request("action", '{"action":"stepOver"}')

    async def into_debug(self, event: Event) -> None:
        await self._debug_request("action", '{"action":"stepInto"}')

    async def out_debug(self, event: Event) -> None:
        await self._debug_request("action", '{"action":"stepOut"}')

    async def pause_debug(self, event: Event) -> None:
        await self._debug_request("action", '{"action":"pause"}')

    async def stop_debug(self, event: Event) -> None:
        await self._debug_request("action", '{"action":"stop"}')

    async def _poll_debug(self) -> None:
        if self.debug_busy:
            return
        self.debug_busy = True
        try:
            await self._debug_request("state")
        finally:
            self.debug_busy = False

    def _hidden(self, path: str) -> bool:
        index = 0
        while index < len(self.collapsed):
            prefix = self.collapsed[index]
            if path != prefix and path.startswith(prefix + "/"):
                return True
            index = index + 1
        return False

    def _is_collapsed(self, path: str) -> bool:
        index = 0
        while index < len(self.collapsed):
            if self.collapsed[index] == path:
                return True
            index = index + 1
        return False

    def _tree_button(self, entry: FileEntry) -> Element:
        indent = 8 + entry["depth"] * 12
        marker = ""
        if entry["kind"] == "dir":
            if self._is_collapsed(entry["path"]):
                marker = "▸ "
            else:
                marker = "▾ "
        git = entry["git"]
        current = ""
        if self.editor is not None:
            current = self.editor.path
        active = current == entry["path"]
        attrs = {
            "type": "button",
            "data-path": entry["path"],
            "data-kind": entry["kind"],
            "data-git": git,
            "data-active": "true" if active else "false",
            "data-testid": "tree-" + entry["path"],
            "style": "padding-left:" + str(indent) + "px",
        }
        label = marker + entry["name"]
        return button(
            tw(
                "flex w-full truncate rounded-sm px-1 py-0.5 text-left text-xs "
                "text-zinc-300 hover:bg-zinc-700 data-[active=true]:bg-zinc-700 "
                "data-[git=mod]:text-[#e2c08d] data-[git=ren]:text-[#e2c08d] "
                "data-[git=copy]:text-[#e2c08d] data-[git=add]:text-[#81b88b] "
                "data-[git=untracked]:text-[#73c991] data-[git=del]:text-[#c74e39] "
                "data-[git=conflict]:text-[#e4676b]"
            ),
            attrs,
            label,
        )

    def _visible_buttons(self) -> list[Element]:
        items: list[Element] = []
        index = 0
        while index < len(self.entries):
            entry = self.entries[index]
            if not self._hidden(entry["path"]):
                items.append(self._tree_button(entry))
            index = index + 1
        return items

    def _render_tree(self) -> None:
        self.tree_list.replaceChildren()
        buttons = self._visible_buttons()
        index = 0
        while index < len(buttons):
            self.tree_list.append(buttons[index])
            index = index + 1

    def _expand_ancestors(self, path: str) -> None:
        kept: list[str] = []
        index = 0
        while index < len(self.collapsed):
            prefix = self.collapsed[index]
            if path != prefix and not path.startswith(prefix + "/"):
                kept.append(prefix)
            index = index + 1
        self.collapsed = kept

    def _reveal_open_file(self) -> None:
        path = ""
        if self.editor is not None:
            path = self.editor.path
        if path == "" or path.startswith("review:"):
            return
        self._expand_ancestors(path)
        self._render_tree()
        item = self.tree_list.querySelector("[data-path='" + path + "']")
        if item is not None:
            item.scrollIntoView(block="center")

    def _apply_git_items(self, items: list[GitStatusItem]) -> bool:
        changed = False
        index = 0
        while index < len(self.entries):
            entry = self.entries[index]
            path = entry["path"]
            kind = ""
            walk = 0
            while walk < len(items):
                if items[walk]["path"] == path:
                    kind = items[walk]["git"]
                    break
                walk = walk + 1
            if entry["git"] != kind:
                entry["git"] = kind
                changed = True
            index = index + 1
        return changed

    async def _refresh_git_tree(self) -> None:
        response = await fetch("/api/git-status?scope=" + self.git_scope + self._review_query())
        if not response.ok:
            return
        payload: GitStatusPayload = JSON.parse(await response.text())
        changed = self._apply_git_items(payload["tree"])
        self.git_changes = payload["changes"]
        self.review_plus = payload["plus"]
        self.review_minus = payload["minus"]
        old_stamp = self.git_stamp
        self.git_stamp = payload["stamp"]
        if changed:
            self._render_tree()
        self._render_scm()
        self.sync_status()
        if self._is_review_doc() and old_stamp != "" and old_stamp != self.git_stamp:
            await self.reload_review_keeping_cursor()

    def _review_query(self) -> str:
        extra = ""
        if self.hide_ws:
            extra = extra + "&ws=1"
        if self.review_wide:
            extra = extra + "&context=wide"
        return extra

    def _sync_scope_buttons(self) -> None:
        if self.git_scope == "unpushed":
            self.scope_dirty.setAttribute("data-active", "false")
            self.scope_unpushed.setAttribute("data-active", "true")
        else:
            self.scope_dirty.setAttribute("data-active", "true")
            self.scope_unpushed.setAttribute("data-active", "false")

    async def set_git_scope(self, scope: str) -> None:
        self.git_scope = scope
        localStorage.setItem("zepy-git-scope", scope)
        self._sync_scope_buttons()
        await self._refresh_git_tree()

    async def on_scope_dirty(self, event: Event) -> None:
        await self.set_git_scope("dirty")

    async def on_scope_unpushed(self, event: Event) -> None:
        await self.set_git_scope("unpushed")

    def _is_virtual_path(self, path: str) -> bool:
        if path == "untitled":
            return True
        if path[0:7] == "review:":
            return True
        return path[0:5] == "head:"

    def _is_review_doc(self) -> bool:
        if self.editor is None:
            return False
        return self.editor.path.startswith("review:")

    def _review_lines(self) -> list[str]:
        if self.editor is None:
            empty: list[str] = []
            return empty
        return self.editor.buffer.get_value().split("\n")

    async def open_review(self) -> None:
        response = await fetch("/api/review?scope=" + self.git_scope + self._review_query())
        if not response.ok:
            return
        payload: ReviewPayload = JSON.parse(await response.text())
        self.review_files = payload["files"]
        self.viewed_paths = payload["viewed"]
        self.review_plus = payload["plus"]
        self.review_minus = payload["minus"]
        self.git_stamp = payload["stamp"]
        if self.editor is None:
            return
        self._stash_active()
        self.editor.open_document(payload["path"], payload["content"])
        self.saved_content = payload["content"]
        name = "review"
        if self.git_scope == "unpushed":
            name = "unpushed"
        existing = self._index_of_path(payload["path"])
        if existing >= 0:
            self._load_tab(existing)
        elif self._untitled_is_disposable():
            self.tabs[0] = OpenTab(payload["path"], name, payload["content"], payload["content"])
            self._load_tab(0)
        else:
            self.tabs.append(OpenTab(payload["path"], name, payload["content"], payload["content"]))
            self._load_tab(len(self.tabs) - 1)
        self.show_scm()
        self.sync_status()

    async def on_review_all(self, event: Event) -> None:
        await self.open_review()

    async def reload_review_keeping_cursor(self) -> None:
        path = ""
        offset = 0
        if self.editor is not None:
            path, _line = locate_review_target(
                self._review_lines(), self.editor.cursor.line_number
            )
            index = 0
            while index < len(self.review_files):
                item = self.review_files[index]
                if item["path"] == path:
                    offset = self.editor.cursor.line_number - item["start_line"]
                    break
                index = index + 1
        await self.open_review()
        if path == "" or self.editor is None:
            return
        index = 0
        while index < len(self.review_files):
            item = self.review_files[index]
            if item["path"] == path:
                dest = item["start_line"] + offset
                dest = min(dest, item["end_line"])
                dest = max(dest, item["start_line"])
                self.editor.set_cursor(Position(dest, 1), False)
                self.editor.ensure_visible()
                self.editor.render()
                return
            index = index + 1

    def _jump_review_path(self, path: str) -> None:
        if self.editor is None:
            return
        index = 0
        while index < len(self.review_files):
            item = self.review_files[index]
            if item["path"] == path:
                self.editor.set_cursor(Position(item["start_line"], 1), False)
                self.editor.ensure_visible()
                self.editor.render()
                return
            index = index + 1

    def review_next_file(self, reverse: bool) -> None:
        if self.editor is None:
            return
        dest = next_review_header_line(
            self._review_lines(), self.editor.cursor.line_number, reverse
        )
        if dest < 1:
            return
        self.editor.set_cursor(Position(dest, 1), False)
        self.editor.ensure_visible()
        self.editor.render()
        path, _line = locate_review_target(self._review_lines(), dest)
        if path != "":
            self._mark_viewed(path)

    def _mark_viewed(self, path: str) -> None:
        if path in self.viewed_paths:
            return
        self.viewed_paths.append(path)
        payload = ViewedAsk(path=path, viewed=True)
        fetch(
            "/api/review/viewed",
            {
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": JSON.stringify(payload),
            },
        )

    async def jump_review_to_file(self) -> None:
        if self.editor is None:
            return
        path, line = locate_review_target(self._review_lines(), self.editor.cursor.line_number)
        if path == "":
            return
        self.review_return_path = self.editor.path
        self.review_return_line = self.editor.cursor.line_number
        self._mark_viewed(path)
        await self.open_path(path)
        if self.editor is not None and line > 0:
            self.editor.set_cursor(Position(line, 1), False)
            self.editor.ensure_visible()
            self.editor.render()

    async def on_review_jump(self, event: Event) -> None:
        await self.jump_review_to_file()

    def on_review_next(self, event: Event) -> None:
        self.review_next_file(False)

    def on_review_prev(self, event: Event) -> None:
        self.review_next_file(True)

    def review_next_hunk(self, reverse: bool) -> None:
        if self.editor is None:
            return
        dest = next_hunk_line(self._review_lines(), self.editor.cursor.line_number, reverse)
        if dest < 1:
            return
        self.editor.set_cursor(Position(dest, 1), False)
        self.editor.ensure_visible()
        self.editor.render()

    def on_review_next_hunk(self, event: Event) -> None:
        self.review_next_hunk(False)

    def on_review_prev_hunk(self, event: Event) -> None:
        self.review_next_hunk(True)

    async def on_review_back(self, event: Event) -> None:
        if self.review_return_path == "":
            await self.open_review()
            return
        await self.open_review()
        if self.editor is not None and self.review_return_line > 0:
            self.editor.set_cursor(Position(self.review_return_line, 1), False)
            self.editor.ensure_visible()
            self.editor.render()

    def on_toggle_viewed(self, event: Event) -> None:
        if self.editor is None:
            return
        path, _line = locate_review_target(self._review_lines(), self.editor.cursor.line_number)
        if path == "":
            return
        if path in self.viewed_paths:
            kept: list[str] = []
            index = 0
            while index < len(self.viewed_paths):
                if self.viewed_paths[index] != path:
                    kept.append(self.viewed_paths[index])
                index = index + 1
            self.viewed_paths = kept
            payload = ViewedAsk(path=path, viewed=False)
            fetch(
                "/api/review/viewed",
                {
                    "method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body": JSON.stringify(payload),
                },
            )
            return
        self._mark_viewed(path)

    def _clear_comment_pin(self) -> None:
        self.comment_path = ""
        self.comment_snippet = ""
        self.comment_start = 0
        self.comment_end = 0
        self.comment_held = False
        self.comment_bar.setAttribute("hidden", "")
        self.comment_chip.setAttribute("hidden", "")
        self.chat_input.setAttribute("placeholder", "Ask Codex about this file…")

    def _pin_comment(self, path: str, snippet: str, start: int, end: int, held: bool) -> None:
        self.comment_path = path
        self.comment_snippet = snippet
        self.comment_start = start
        self.comment_end = end
        self.comment_held = held
        if snippet == "":
            self._clear_comment_pin()
            return
        label = line_span_label(path, start, end)
        self.comment_label.textContent = label
        self.comment_chip_label.textContent = "Attached " + label
        self.comment_bar.removeAttribute("hidden")
        self.comment_chip.removeAttribute("hidden")
        self.chat_input.setAttribute("placeholder", "Comment on " + label + "…")

    def _pin_comment_from_editor(self, held: bool) -> bool:
        if self.editor is None:
            return False
        span = self.editor.selection_lines()
        start = span[0]
        end = span[1]
        if start < 1:
            return False
        snippet = numbered_snippet(self.editor.selected_line_text(), start)
        if snippet == "":
            return False
        self._pin_comment(self.editor.path, snippet, start, end, held)
        return True

    def _sync_comment_bar(self) -> None:
        if self.editor is None:
            if not self.comment_held:
                self._clear_comment_pin()
            return
        if self._pin_comment_from_editor(self.comment_held):
            return
        if self.comment_held and self.comment_snippet != "":
            self.comment_bar.removeAttribute("hidden")
            self.comment_chip.removeAttribute("hidden")
            return
        self._clear_comment_pin()

    def on_comment_clear(self, event: Event) -> None:
        self._clear_comment_pin()
        if self.editor is not None:
            self.editor.anchor = None
            self.editor.render()
            self.editor.focus()

    async def on_comment_ask(self, event: Event) -> None:
        pinned = self._pin_comment_from_editor(True)
        if not pinned:
            if self._is_review_doc():
                await self.on_review_ask(event)
            return
        if not self.chat_open:
            self.toggle_chat()
        self.comment_held = True
        self._sync_comment_bar()
        self.chat_input.focus()
        typed = self.chat_input.value.strip()
        if typed != "":
            await self.send_chat(typed)

    async def on_review_ask(self, event: Event) -> None:
        if self.editor is None:
            return
        hunk = extract_hunk(self._review_lines(), self.editor.cursor.line_number)
        if hunk == "":
            return
        path, line = locate_review_target(self._review_lines(), self.editor.cursor.line_number)
        snippet = numbered_snippet(hunk, line)
        self._pin_comment(path, snippet, line, line, True)
        await self.send_chat("Explain this hunk:")

    async def on_toggle_ws(self, event: Event) -> None:
        self.hide_ws = not self.hide_ws
        if self.hide_ws:
            self.hide_ws_button.setAttribute("data-active", "true")
        else:
            self.hide_ws_button.setAttribute("data-active", "false")
        flag = "0"
        if self.hide_ws:
            flag = "1"
        localStorage.setItem("zepy-hide-ws", flag)
        await self._refresh_git_tree()
        if self._is_review_doc():
            await self.open_review()

    async def on_toggle_wide(self, event: Event) -> None:
        self.review_wide = not self.review_wide
        if self.review_wide:
            self.wide_button.setAttribute("data-active", "true")
        else:
            self.wide_button.setAttribute("data-active", "false")
        if self._is_review_doc():
            await self.open_review()

    def _git_mark(self, git: str) -> str:
        if git == "mod":
            return "M"
        if git == "ren":
            return "R"
        if git == "copy":
            return "C"
        if git == "add":
            return "A"
        if git == "untracked":
            return "U"
        if git == "del":
            return "D"
        if git == "conflict":
            return "C"
        return " "

    def _scm_button(self, path: str, git: str, plus: int, minus: int) -> Element:
        attrs = {
            "type": "button",
            "data-path": path,
            "data-git": git,
            "data-testid": "scm-item",
        }
        label = self._git_mark(git) + "  " + path
        if plus > 0 or minus > 0:
            label = label + "  +" + str(plus) + " -" + str(minus)
        if git == "mod" or git == "ren" or git == "copy":
            return button(
                tw(
                    "flex w-full truncate rounded-sm px-1 py-0.5 text-left text-xs "
                    "text-[#e2c08d] hover:bg-zinc-700"
                ),
                attrs,
                label,
            )
        if git == "add":
            return button(
                tw(
                    "flex w-full truncate rounded-sm px-1 py-0.5 text-left text-xs "
                    "text-[#81b88b] hover:bg-zinc-700"
                ),
                attrs,
                label,
            )
        if git == "untracked":
            return button(
                tw(
                    "flex w-full truncate rounded-sm px-1 py-0.5 text-left text-xs "
                    "text-[#73c991] hover:bg-zinc-700"
                ),
                attrs,
                label,
            )
        if git == "del":
            return button(
                tw(
                    "flex w-full truncate rounded-sm px-1 py-0.5 text-left text-xs "
                    "text-[#c74e39] hover:bg-zinc-700"
                ),
                attrs,
                label,
            )
        if git == "conflict":
            return button(
                tw(
                    "flex w-full truncate rounded-sm px-1 py-0.5 text-left text-xs "
                    "text-[#e4676b] hover:bg-zinc-700"
                ),
                attrs,
                label,
            )
        return button(
            tw(
                "flex w-full truncate rounded-sm px-1 py-0.5 text-left text-xs "
                "text-zinc-300 hover:bg-zinc-700"
            ),
            attrs,
            label,
        )

    def _render_scm(self) -> None:
        self.scm_list.replaceChildren()
        count = 0
        if len(self.git_changes) > 0:
            index = 0
            while index < len(self.git_changes):
                item = self.git_changes[index]
                self.scm_list.append(
                    self._scm_button(item["path"], item["git"], item["plus"], item["minus"])
                )
                count = count + 1
                index = index + 1
        else:
            index = 0
            while index < len(self.entries):
                entry = self.entries[index]
                if entry["kind"] == "file" and entry["git"] != "":
                    self.scm_list.append(self._scm_button(entry["path"], entry["git"], 0, 0))
                    count = count + 1
                index = index + 1
        if count == 0:
            self.scm_list.append(tag("div", tw("px-2 py-2 text-xs text-zinc-500"), "No changes"))

    def show_explorer(self, event: Event | None = None) -> None:
        self.sidebar_view = "explorer"
        self.explorer_pane.removeAttribute("hidden")
        self.scm_pane.setAttribute("hidden", "")
        self.sidebar_title.textContent = "Explorer"
        self.activity_explorer.setAttribute("data-active", "true")
        self.activity_scm.setAttribute("data-active", "false")

    def show_scm(self, event: Event | None = None) -> None:
        self.sidebar_view = "scm"
        self.explorer_pane.setAttribute("hidden", "")
        self.scm_pane.removeAttribute("hidden")
        self.sidebar_title.textContent = "Source Control"
        self.activity_explorer.setAttribute("data-active", "false")
        self.activity_scm.setAttribute("data-active", "true")
        self._render_scm()

    async def on_scm_click(self, event: Event) -> None:
        current = event.target
        path = ""
        while current is not None:
            if isinstance(current, Element):
                hit = current.getAttribute("data-path")
                if hit is not None:
                    path = hit
                    break
            if not isinstance(current, Node):
                return
            current = current.parentElement
        if path == "":
            return
        await self.open_review()
        self._jump_review_path(path)

    def _render_chat(self) -> None:
        sync_chat_log(
            self.chat_log,
            self.chat_messages,
            self.chat_partial,
            self.chat_rendered_count,
            self.chat_rendered_partial,
        )
        self.chat_rendered_count = len(self.chat_messages)
        self.chat_rendered_partial = self.chat_partial
        status = "Codex"
        if self.chat_busy:
            status = "Codex · thinking"
        elif not self.chat_idle:
            status = "Codex · streaming"
        self.chat_status.textContent = status
        self.chat_status.title = self.chat_session

    def toggle_chat(self, event: Event | None = None) -> None:
        if self.chat_open:
            self.chat_open = False
            self.chat_pane.setAttribute("hidden", "")
            self.chat_split.setAttribute("hidden", "")
            self.activity_chat.setAttribute("data-active", "false")
            localStorage.setItem("zepy-chat-open", "0")
            self._resize_editors()
            return
        self.chat_open = True
        self.chat_pane.removeAttribute("hidden")
        self.chat_split.removeAttribute("hidden")
        self.activity_chat.setAttribute("data-active", "true")
        localStorage.setItem("zepy-chat-open", "1")
        self.chat_input.focus()
        self._resize_editors()

    def _clamp_int(self, value: int, lo: int, hi: int) -> int:
        if value < lo:
            return lo
        if value > hi:
            return hi
        return value

    def _read_stored_width(self, key: str, fallback: int, lo: int, hi: int) -> int:
        raw = localStorage.getItem(key)
        if raw is None or raw == "":
            return fallback
        index = 0
        while index < len(raw):
            ch = raw[index]
            if ch < "0" or ch > "9":
                return fallback
            index = index + 1
        return self._clamp_int(int(raw), lo, hi)

    def _apply_pane_widths(self) -> None:
        self.sidebar.style.width = str(self.sidebar_width) + "px"
        self.chat_pane.style.width = str(self.chat_width) + "px"
        if self.chat_open:
            self.chat_split.removeAttribute("hidden")
        else:
            self.chat_split.setAttribute("hidden", "")
        self._resize_editors()

    def _store_pane_widths(self) -> None:
        localStorage.setItem("zepy-sidebar-width", str(self.sidebar_width))
        localStorage.setItem("zepy-chat-width", str(self.chat_width))

    def _set_drag_cursor(self, grabbing: bool) -> None:
        if grabbing:
            document.body.style.setProperty("cursor", "col-resize")
            document.body.style.setProperty("user-select", "none")
            return
        document.body.style.setProperty("cursor", "")
        document.body.style.setProperty("user-select", "")

    def on_sidebar_split_down(self, event: MouseEvent) -> None:
        event.preventDefault()
        self.drag_kind = "sidebar"
        self.drag_origin = event.clientX
        self.drag_start_width = self.sidebar_width
        self._set_drag_cursor(True)

    def on_chat_split_down(self, event: MouseEvent) -> None:
        event.preventDefault()
        self.drag_kind = "chat"
        self.drag_origin = event.clientX
        self.drag_start_width = self.chat_width
        self._set_drag_cursor(True)

    def on_split_move(self, event: Event) -> None:
        if self.drag_kind == "":
            return
        if not isinstance(event, MouseEvent):
            return
        delta = event.clientX - self.drag_origin
        if self.drag_kind == "sidebar":
            self.sidebar_width = self._clamp_int(self.drag_start_width + delta, 160, 560)
        else:
            self.chat_width = self._clamp_int(self.drag_start_width - delta, 200, 720)
        self._apply_pane_widths()

    def on_split_up(self, event: Event) -> None:
        if self.drag_kind == "":
            return
        self.drag_kind = ""
        self._set_drag_cursor(False)
        self._store_pane_widths()
        self._resize_editors()

    def _append_chat(self, role: str, text: str) -> None:
        self.chat_messages.append(ChatLine(role=role, text=text))
        self._render_chat()

    async def load_chat(self) -> None:
        response = await fetch("/api/chat")
        if not response.ok:
            self._render_chat()
            return
        payload: ChatHistoryPayload = JSON.parse(await response.text())
        self.chat_session = payload["session_id"]
        self.chat_idle = payload["idle"]
        redraw = False
        if payload["stamp"] != self.chat_stamp or len(self.chat_messages) != len(
            payload["messages"]
        ):
            self.chat_stamp = payload["stamp"]
            self.chat_messages = payload["messages"]
            redraw = True
        if payload["partial"] != self.chat_partial:
            self.chat_partial = payload["partial"]
            redraw = True
        if redraw:
            self._render_chat()
        # The host drains queued Codex turns independently of UI polling.

    def _selection_prompt(self, text: str) -> ChatAsk:
        path = self.comment_path
        selection = self.comment_snippet
        line = self.comment_start
        end_line = self.comment_end
        if selection == "" and self.editor is not None:
            path = self.editor.path
            span = self.editor.selection_lines()
            line = span[0]
            end_line = span[1]
            selection = numbered_snippet(self.editor.selected_line_text(), line)
            if selection == "":
                selection = self.editor.selected_text()
                line = self.editor.cursor.line_number
                end_line = line
        return ChatAsk(
            text=text,
            path=path,
            selection=selection,
            line=line,
            end_line=end_line,
            flush=False,
        )

    async def send_chat(self, text: str) -> None:
        if self.chat_busy:
            return
        prompt = text.strip()
        payload = self._selection_prompt(prompt)
        if prompt == "" and payload["selection"] == "":
            return
        self.chat_busy = True
        shown = prompt
        if shown == "":
            shown = line_span_label(payload["path"], payload["line"], payload["end_line"])
        self._append_chat("user", shown)
        self.chat_input.value = ""
        self._render_chat()
        if payload["selection"] != "":
            note_text = prompt
            if note_text == "":
                note_text = "(shared lines)"
            note = LineComment(
                path=payload["path"],
                text=note_text,
                line=payload["line"],
                end_line=payload["end_line"],
                snippet=payload["selection"],
            )
            fetch(
                "/api/review/comment",
                {
                    "method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body": JSON.stringify(note),
                },
            )
        response = await fetch(
            "/api/chat",
            {
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": JSON.stringify(payload),
            },
        )
        reply = "Codex did not respond."
        if response.ok:
            body: ChatReply = JSON.parse(await response.text())
            self.chat_session = body["session_id"]
            reply = body["text"]
        else:
            error_body: ChatReply = JSON.parse(await response.text())
            reply = error_body["text"]
        if reply != "":
            self._append_chat("assistant", reply)
        self.chat_busy = False
        if response.ok:
            await self.load_chat()
        self._render_chat()
        if payload["selection"] != "":
            self.comment_held = True
            self._sync_comment_bar()

    async def on_chat_send(self, event: Event) -> None:
        await self.send_chat(self.chat_input.value)

    async def on_chat_keydown(self, event: KeyboardEvent) -> None:
        if event.key == "Enter" and (event.ctrlKey or event.metaKey):
            event.preventDefault()
            await self.send_chat(self.chat_input.value)

    def _basename(self, path: str) -> str:
        parts = path.split("/")
        return parts[len(parts) - 1]

    def _stash_active(self) -> None:
        if self.editor is None:
            return
        if self.active_tab < 0 or self.active_tab >= len(self.tabs):
            return
        tab = self.tabs[self.active_tab]
        tab.content = self.editor.buffer.get_value()
        tab.path = self.editor.path
        tab.name = self._basename(tab.path)
        tab.line = self.editor.cursor.line_number
        tab.column = self.editor.cursor.column
        tab.undo = self.editor._undo
        tab.redo = self.editor._redo

    def _index_of_path(self, path: str) -> int:
        index = 0
        while index < len(self.tabs):
            if self.tabs[index].path == path:
                return index
            index = index + 1
        return -1

    def _load_tab(self, index: int) -> None:
        if index < 0 or index >= len(self.tabs):
            return
        self.active_tab = index
        tab = self.tabs[index]
        self.tab_name = tab.name
        self.saved_content = tab.saved
        if self.editor is not None:
            self.editor.open_document(tab.path, tab.content)
            self.editor._undo = tab.undo
            self.editor._redo = tab.redo
            self.editor.cursor = Position(tab.line, tab.column)
            self.editor.anchor = None
            self.editor.clear_find()
            self.editor.render()
            self.editor.focus()
        self.title_label.textContent = "ZEPY — " + tab.path
        shown = tab.name
        if self.editor is not None and self.editor.wrap:
            shown = shown + "  wrap"
        self.status_file.textContent = shown
        self._render_tabs()
        self.sync_status()
        self._reveal_open_file()

    def _tab_button(self, tab: OpenTab, index: int) -> Element:
        dirty = tab.content != tab.saved
        if self.editor is not None and index == self.active_tab:
            dirty = self.editor.buffer.get_value() != tab.saved
        label = tab.name
        if dirty:
            label = "● " + label
        active = "false"
        dirty_attr = "false"
        if dirty:
            dirty_attr = "true"
        closer = button(
            tw("ml-1 px-0.5 text-[10px] text-zinc-500 hover:text-zinc-200"),
            {
                "type": "button",
                "data-path": tab.path,
                "data-action": "close",
                "data-testid": "tab-close",
            },
            "×",
        )
        attrs = {
            "data-path": tab.path,
            "data-active": active,
            "data-dirty": dirty_attr,
            "data-testid": "tab",
        }
        if index == self.active_tab:
            attrs["data-active"] = "true"
            return div(
                tw(
                    "flex h-full shrink-0 items-center gap-1 border-r border-zinc-800 "
                    "border-t-2 border-t-blue-400 bg-[#1e1e1e] px-3 text-xs text-zinc-200"
                ),
                attrs,
                tag("span", label),
                closer,
            )
        return div(
            tw(
                "flex h-full shrink-0 items-center gap-1 border-r border-zinc-800 "
                "px-3 text-xs text-zinc-300 hover:bg-[#2a2a2a]"
            ),
            attrs,
            tag("span", label),
            closer,
        )

    def _render_tabs(self) -> None:
        self.tab_strip.replaceChildren()
        index = 0
        while index < len(self.tabs):
            self.tab_strip.append(self._tab_button(self.tabs[index], index))
            index = index + 1

    def _untitled_is_disposable(self) -> bool:
        if len(self.tabs) != 1:
            return False
        tab = self.tabs[0]
        if tab.path != "untitled":
            return False
        return tab.content == tab.saved

    def close_tab(self, path: str) -> None:
        self._stash_active()
        index = self._index_of_path(path)
        if index < 0:
            return
        kept: list[OpenTab] = []
        walk = 0
        while walk < len(self.tabs):
            if walk != index:
                kept.append(self.tabs[walk])
            walk = walk + 1
        self.tabs = kept
        if len(self.tabs) == 0:
            blank = "Hello, Zepy\n\nOpen a file from the explorer."
            self.tabs.append(OpenTab("untitled", "untitled", blank, blank))
            self._load_tab(0)
            return
        next_index = index
        if next_index >= len(self.tabs):
            next_index = len(self.tabs) - 1
        self._load_tab(next_index)

    def next_tab(self) -> None:
        if len(self.tabs) < 2:
            return
        self._stash_active()
        index = self.active_tab + 1
        if index >= len(self.tabs):
            index = 0
        self._load_tab(index)

    def prev_tab(self) -> None:
        if len(self.tabs) < 2:
            return
        self._stash_active()
        index = self.active_tab - 1
        if index < 0:
            index = len(self.tabs) - 1
        self._load_tab(index)

    def on_tab_next(self, event: Event) -> None:
        self.next_tab()

    def on_tab_prev(self, event: Event) -> None:
        self.prev_tab()

    def on_tab_click(self, event: Event) -> None:
        current = event.target
        action = ""
        path = ""
        while current is not None:
            if isinstance(current, Element):
                if current.getAttribute("data-action") == "close":
                    close_path = current.getAttribute("data-path")
                    if close_path is None:
                        return
                    action = "close"
                    path = close_path
                    break
                tab_path = current.getAttribute("data-path")
                if tab_path is not None and current.getAttribute("data-testid") == "tab":
                    path = tab_path
                    break
            if not isinstance(current, Node):
                return
            current = current.parentElement
        if path == "":
            return
        if action == "close":
            self.close_tab(path)
            return
        self._stash_active()
        index = self._index_of_path(path)
        if index >= 0:
            self._load_tab(index)

    def _toggle_collapsed(self, path: str) -> None:
        kept: list[str] = []
        found = False
        index = 0
        while index < len(self.collapsed):
            current = self.collapsed[index]
            if current == path:
                found = True
            else:
                kept.append(current)
            index = index + 1
        if not found:
            kept.append(path)
        self.collapsed = kept
        self._render_tree()

    def _tree_item_from_event(self, event: Event) -> Element | None:
        current = event.target
        while current is not None:
            if isinstance(current, Element):
                path = current.getAttribute("data-path")
                if path is not None:
                    return current
            if not isinstance(current, Node):
                return None
            current = current.parentElement
        return None

    async def on_tree_click(self, event: Event) -> None:
        element = self._tree_item_from_event(event)
        if element is None:
            return
        path = element.getAttribute("data-path")
        kind = element.getAttribute("data-kind")
        if path is None or kind is None:
            return
        if kind == "dir":
            self._toggle_collapsed(path)
            return
        await self.open_path(path)

    def _local_content(self, path: str) -> str | None:
        index = 0
        while index < len(self.entries):
            entry = self.entries[index]
            if entry["path"] == path:
                return entry["content"]
            index = index + 1
        return None

    async def open_path(self, path: str) -> None:
        self._stash_active()
        existing = self._index_of_path(path)
        if existing >= 0:
            self._load_tab(existing)
            if self.editor is not None:
                await self._load_git(self.editor)
            return
        content = self._local_content(path)
        mtime = 0.0
        if content is None:
            payload = await read_file(path)
            if payload is None:
                return
            content = payload["content"]
            mtime = payload["mtime"]
        name = self._basename(path)
        tab = OpenTab(path, name, content, content)
        if self._untitled_is_disposable():
            self.tabs[0] = tab
            self._load_tab(0)
        else:
            self.tabs.append(tab)
            self._load_tab(len(self.tabs) - 1)
        if self.editor is not None:
            self.editor.disk_mtime = mtime
            await self._load_git(self.editor)

    def _store_local_content(self, path: str, content: str) -> None:
        index = 0
        while index < len(self.entries):
            entry = self.entries[index]
            if entry["path"] == path:
                entry["content"] = content
                return
            index = index + 1

    def _sync_tab(self) -> None:
        name = self.tab_name
        dirty = False
        if self.editor is not None:
            dirty = self.editor.buffer.get_value() != self.saved_content
        if dirty:
            self.tab_label.textContent = "● " + name
            self.tab_label.setAttribute("data-dirty", "true")
        else:
            self.tab_label.textContent = name
            self.tab_label.setAttribute("data-dirty", "false")
        self._render_tabs()

    def sync_status(self, event: Event | None = None) -> None:
        self._sync_tab()
        self._sync_comment_bar()
        if self.editor is None:
            return
        mode = self.editor.vim.mode
        if mode == MODE_INSERT:
            self.status_mode.textContent = "INSERT"
            self.command_bar.setAttribute("hidden", "")
        elif mode == MODE_VISUAL_BLOCK:
            self.status_mode.textContent = "V-BLOCK"
            self.command_bar.setAttribute("hidden", "")
        elif mode == MODE_VISUAL or mode == MODE_VISUAL_LINE:
            self.status_mode.textContent = "VISUAL"
            self.command_bar.setAttribute("hidden", "")
        elif mode == MODE_COMMAND:
            prefix = self.editor.vim.command_kind
            if prefix == "":
                prefix = ":"
            self.status_mode.textContent = prefix
            self.command_text.textContent = prefix + self.editor.vim.command
            self.command_bar.removeAttribute("hidden")
        else:
            self.status_mode.textContent = "NORMAL"
            self.command_bar.setAttribute("hidden", "")
        cursor = self.editor.cursor
        self.status_cursor.textContent = (
            "Ln " + str(cursor.line_number) + ", Col " + str(cursor.column)
        )
        blame = self.editor.blame_at_cursor()
        self.status_git.textContent = blame
        file_label = self.tab_name
        if self.editor.wrap:
            file_label = file_label + "  wrap"
        self.status_file.textContent = file_label
        scope = self.git_scope
        if self.review_plus > 0 or self.review_minus > 0:
            scope = scope + " +" + str(self.review_plus) + " -" + str(self.review_minus)
        self.status_scope.textContent = scope

    async def save(self) -> None:
        if self.editor is None:
            return
        path = self.editor.path
        if self._is_virtual_path(path):
            return
        content = self.editor.buffer.get_value()
        saved = await write_file(path, content)
        if saved is None:
            return
        self.saved_content = content
        self._store_local_content(path, content)
        if self.active_tab >= 0 and self.active_tab < len(self.tabs):
            self.tabs[self.active_tab].saved = content
            self.tabs[self.active_tab].content = content
        if self.editor is not None:
            self.editor.disk_mtime = saved["mtime"]
            await self._load_git(self.editor)
        await self._refresh_git_tree()
        self.sync_status()

    async def on_save(self, event: Event) -> None:
        await self.save()

    def _sync_find_count(self) -> None:
        if (
            self.editor is None
            or self.editor.find_query == ""
            or len(self.editor.find_matches) == 0
        ):
            self.find_count.textContent = "No results"
            return
        current = self.editor.find_index + 1
        self.find_count.textContent = str(current) + " of " + str(len(self.editor.find_matches))

    def show_find(self, focus_replace: bool = False) -> None:
        self.find_bar.removeAttribute("hidden")
        seed = ""
        if self.editor is not None:
            seed = self.editor.selected_text()
            if seed != "":
                self.find_field.value = seed
                self.editor.set_find_query(seed)
            elif self.find_field.value != "":
                self.editor.set_find_query(self.find_field.value)
        self._sync_find_count()
        if focus_replace:
            self.replace_field.focus()
        else:
            self.find_field.focus()

    def close_find(self) -> None:
        self.find_bar.setAttribute("hidden", "")
        if self.editor is not None:
            self.editor.clear_find()
            self.editor.focus()
        self.find_count.textContent = "No results"

    def on_find(self, event: Event) -> None:
        self.show_find()

    def on_replace(self, event: Event) -> None:
        self.show_find(True)

    def on_find_input(self, event: Event) -> None:
        if self.editor is None:
            return
        self.editor.set_find_query(self.find_field.value)
        self._sync_find_count()

    def on_find_keydown(self, event: KeyboardEvent) -> None:
        if event.key == "Escape":
            event.preventDefault()
            self.close_find()
            return
        if event.key == "Enter" or event.key == "F3":
            event.preventDefault()
            if self.editor is None:
                return
            if event.shiftKey:
                self.editor.find_previous()
            else:
                self.editor.find_next()
            self._sync_find_count()

    def on_find_prev(self, event: Event) -> None:
        if self.editor is None:
            return
        self.editor.find_previous()
        self._sync_find_count()

    def on_find_next(self, event: Event) -> None:
        if self.editor is None:
            return
        self.editor.find_next()
        self._sync_find_count()

    def on_find_close(self, event: Event) -> None:
        self.close_find()

    def _replace_one(self) -> None:
        if self.editor is None:
            return
        if self.editor.find_query == "" and self.find_field.value != "":
            self.editor.set_find_query(self.find_field.value)
        self.editor.replace_current(self.replace_field.value)
        self._sync_find_count()
        self.sync_status()

    def _replace_all(self) -> None:
        if self.editor is None:
            return
        if self.editor.find_query == "" and self.find_field.value != "":
            self.editor.set_find_query(self.find_field.value)
        self.editor.replace_all(self.replace_field.value)
        self._sync_find_count()
        self.sync_status()

    def on_replace_one(self, event: Event) -> None:
        self._replace_one()

    def on_replace_all(self, event: Event) -> None:
        self._replace_all()

    def _palette_label(self, index: int) -> str:
        if index == 0:
            return "Save"
        if index == 1:
            return "Find"
        if index == 2:
            return "Replace"
        if index == 3:
            return "Next Tab"
        if index == 4:
            return "Previous Tab"
        if index == 5:
            return "Close Tab"
        if index == 6:
            return "Search in Files"
        if index == 7:
            return "Quick Open"
        if index == 8:
            return "Split Editor"
        if index == 9:
            return "Source Control"
        if index == 10:
            return "Toggle Codex Chat"
        return ""

    def _palette_shortcut(self, index: int) -> str:
        if index == 0:
            return "Ctrl+S"
        if index == 1:
            return "Ctrl+F"
        if index == 2:
            return "Ctrl+H"
        if index == 6:
            return "Ctrl+Shift+F"
        if index == 7:
            return "Ctrl+P"
        if index == 8:
            return "Ctrl+\\"
        return ""

    def _palette_command_item(self, index: int) -> CommandItem:
        label = self._palette_label(index)
        shortcut = self._palette_shortcut(index)
        if shortcut == "":
            item = CommandItem(label, label)
        else:
            item = CommandItem(label, label, CommandShortcut(shortcut))
        item.setAttribute("data-command", str(index))
        item.setAttribute("data-testid", "palette-item")
        return item

    def show_palette(self, event: Event) -> None:
        self.search_panel.setAttribute("hidden", "")
        self.quick_panel.setAttribute("hidden", "")
        self.palette.removeAttribute("hidden")
        self.command_palette.input.value = ""
        self.command_palette.search(Event("input"))
        self.command_palette.input.focus()

    def hide_palette(self) -> None:
        self.palette.setAttribute("hidden", "")
        if self.editor is not None:
            self.editor.focus()

    def on_palette_cancel(self, event: Event) -> None:
        self.hide_palette()

    async def on_palette_select(self, event: Event) -> None:
        item = self.command_palette.highlighted_item()
        if item is None:
            return
        raw = item.getAttribute("data-command")
        if raw is None:
            return
        await self._run_palette(int(raw))

    async def _run_palette(self, index: int) -> None:
        self.hide_palette()
        if index == 0:
            await self.save()
        elif index == 1:
            self.show_find()
        elif index == 2:
            self.show_find(True)
        elif index == 3:
            self.next_tab()
        elif index == 4:
            self.prev_tab()
        elif index == 5:
            if self.active_tab >= 0 and self.active_tab < len(self.tabs):
                self.close_tab(self.tabs[self.active_tab].path)
        elif index == 6:
            self.show_search(Event("zepy-search-files"))
        elif index == 7:
            self.show_quick(Event("zepy-quick-open"))
        elif index == 8:
            await self.on_split(Event("zepy-split"))
        elif index == 9:
            self.show_scm()
        elif index == 10:
            self.toggle_chat()

    def show_search(self, event: Event) -> None:
        self.palette.setAttribute("hidden", "")
        self.quick_panel.setAttribute("hidden", "")
        self.search_panel.removeAttribute("hidden")
        self.search_query = ""
        self.search_command.input.value = ""
        self.search_command.empty.textContent = "Press Enter to search"
        self.search_command.replace_items()
        self.search_command.input.focus()

    def hide_search(self) -> None:
        self.search_panel.setAttribute("hidden", "")
        if self.editor is not None:
            self.editor.focus()

    def on_search_cancel(self, event: Event) -> None:
        self.hide_search()

    async def run_search(self) -> None:
        query = self.search_command.input.value
        self.search_query = query
        hits = await search_files(query)
        if hits is None:
            self.search_command.empty.textContent = "No results found."
            self.search_command.replace_items()
            return
        rows: list[CommandItem] = []
        index = 0
        while index < len(hits):
            hit = hits[index]
            label = hit["path"] + ":" + str(hit["line"]) + "  " + hit["text"]
            item = CommandItem(label, label)
            item.setAttribute("data-path", hit["path"])
            item.setAttribute("data-line", str(hit["line"]))
            item.setAttribute("data-testid", "search-hit")
            rows.append(item)
            index = index + 1
        if len(rows) == 0:
            self.search_command.empty.textContent = "No results found."
        self.search_command.replace_items(*rows)

    async def on_search_submit(self, event: Event) -> None:
        item = self.search_command.highlighted_item()
        query = self.search_command.input.value
        if item is not None and query == self.search_query and query != "":
            await self._open_search_hit(item)
            return
        await self.run_search()

    async def on_search_select(self, event: Event) -> None:
        item = self.search_command.highlighted_item()
        if item is None:
            return
        await self._open_search_hit(item)

    async def _open_search_hit(self, item: Element) -> None:
        path = item.getAttribute("data-path")
        raw_line = item.getAttribute("data-line")
        if path is None or path == "":
            return
        line = 1
        if raw_line is not None:
            line = int(raw_line)
        self.hide_search()
        await self.open_path(path)
        if self.editor is not None:
            self.editor.cursor = Position(line, 1)
            self.editor.ensure_visible()
            self.editor.render()
            self.sync_status()

    def on_replace_keydown(self, event: KeyboardEvent) -> None:
        if event.key == "Escape":
            event.preventDefault()
            self.close_find()
            return
        if event.key == "Enter":
            event.preventDefault()
            if event.ctrlKey or event.metaKey:
                self._replace_all()
            else:
                self._replace_one()

    def _bind_editor_events(self, canvas: Element) -> None:
        canvas.addEventListener("zepy-change", self.sync_status)
        canvas.addEventListener("zepy-save", self.on_save)
        canvas.addEventListener("zepy-find", self.on_find)
        canvas.addEventListener("zepy-replace", self.on_replace)
        canvas.addEventListener("zepy-tab-next", self.on_tab_next)
        canvas.addEventListener("zepy-tab-prev", self.on_tab_prev)
        canvas.addEventListener("zepy-palette", self.show_palette)
        canvas.addEventListener("zepy-search-files", self.show_search)
        canvas.addEventListener("zepy-quick-open", self.show_quick)
        canvas.addEventListener("zepy-split", self.on_split)
        canvas.addEventListener("zepy-open-path", self.on_open_path)
        canvas.addEventListener("zepy-open-head", self.on_open_head)
        canvas.addEventListener("zepy-review-jump", self.on_review_jump)
        canvas.addEventListener("zepy-review-next", self.on_review_next)
        canvas.addEventListener("zepy-review-prev", self.on_review_prev)
        canvas.addEventListener("zepy-review-next-hunk", self.on_review_next_hunk)
        canvas.addEventListener("zepy-review-prev-hunk", self.on_review_prev_hunk)
        canvas.addEventListener("zepy-review-back", self.on_review_back)
        canvas.addEventListener("zepy-review-viewed", self.on_toggle_viewed)
        canvas.addEventListener("zepy-review-ask", self.on_review_ask)
        canvas.addEventListener("zepy-comment-ask", self.on_comment_ask)

    def _attach_editor_scrollbars(
        self,
        editor: GpuTextEditor,
        vtrack: Element,
        vthumb: Element,
        htrack: Element,
        hthumb: Element,
    ) -> None:
        if (
            not isinstance(vtrack, HTMLElement)
            or not isinstance(vthumb, HTMLElement)
            or not isinstance(htrack, HTMLElement)
            or not isinstance(hthumb, HTMLElement)
        ):
            return
        editor.attach_scrollbars(vtrack, vthumb, htrack, hthumb)

    def _resize_editors(self) -> None:
        self._resize_one(self.stage, self.primary)
        if self.split_open:
            self._resize_one(self.stage_b, self.editor_b)

    def on_window_resize(self, event: Event) -> None:
        self._resize_editors()

    def disconnected(self) -> None:
        window.removeEventListener("resize", self._resize_callback)

    def reconnected(self) -> None:
        window.addEventListener("resize", self._resize_callback)
        self._resize_editors()

    def _resize_one(self, stage: Element, editor: GpuTextEditor | None) -> None:
        if editor is None:
            return
        if not isinstance(stage, HTMLCanvasElement):
            return
        editor.resize_backing_store()
        editor.render()

    def _focus_primary(self) -> None:
        editor = self.primary
        if editor is None:
            return
        self.editor = editor
        self.focused_split = 0
        self.sync_status()
        editor.focus()

    def _focus_split(self) -> None:
        editor = self.editor_b
        if editor is None:
            return
        self.editor = editor
        self.focused_split = 1
        self.sync_status()
        editor.focus()

    def on_pane_focus(self, event: Event) -> None:
        self._focus_primary()

    def on_pane_b_focus(self, event: Event) -> None:
        self._focus_split()

    async def on_split(self, event: Event) -> None:
        if self.split_open:
            self.split_open = False
            self.pane_b.setAttribute("hidden", "")
            self._focus_primary()
            self._resize_editors()
            return
        self.split_open = True
        self.pane_b.removeAttribute("hidden")
        if self.editor_b is None:
            self.editor_b = await create_gpu_text_editor(self.stage_b, self.input_b, "")
            if self.editor_b is not None:
                self._bind_editor_events(self.stage_b)
                self._attach_editor_scrollbars(
                    self.editor_b,
                    self.vscroll_b,
                    self.vthumb_b,
                    self.hscroll_b,
                    self.hthumb_b,
                )
                self.pane_b.addEventListener("mousedown", self.on_pane_b_focus)
        primary = self.primary
        split = self.editor_b
        if primary is None:
            self._resize_editors()
            return
        if split is None:
            self._resize_editors()
            return
        split.open_document(primary.path, primary.buffer.get_value())
        self._resize_editors()
        self._focus_split()

    def _render_quick(self) -> None:
        rows: list[CommandItem] = []
        index = 0
        shown = 0
        while index < len(self.entries) and shown < 80:
            entry = self.entries[index]
            if entry["kind"] == "file":
                item = CommandItem(entry["path"], entry["path"])
                item.setAttribute("data-path", entry["path"])
                item.setAttribute("data-testid", "quick-open-item")
                rows.append(item)
                shown = shown + 1
            index = index + 1
        self.quick_command.replace_items(*rows)

    def show_quick(self, event: Event) -> None:
        self.palette.setAttribute("hidden", "")
        self.search_panel.setAttribute("hidden", "")
        self.quick_panel.removeAttribute("hidden")
        self.quick_command.input.value = ""
        self.quick_index = 0
        self._render_quick()
        self.quick_command.input.focus()

    def hide_quick(self) -> None:
        self.quick_panel.setAttribute("hidden", "")
        if self.editor is not None:
            self.editor.focus()

    def on_quick_cancel(self, event: Event) -> None:
        self.hide_quick()

    async def on_quick_select(self, event: Event) -> None:
        item = self.quick_command.highlighted_item()
        if item is None:
            return
        path = item.getAttribute("data-path")
        if path is None or path == "":
            return
        self.hide_quick()
        await self.open_path(path)

    async def on_open_path(self, event: Event) -> None:
        source = self.editor
        if source is None:
            return
        path = source.pending_open
        source.pending_open = ""
        if path == "":
            return
        await self.open_path(path)

    async def on_open_head(self, event: Event) -> None:
        if self.editor is None:
            return
        path = self.editor.path
        if path.startswith("review:"):
            path, _line = locate_review_target(
                self._review_lines(), self.editor.cursor.line_number
            )
        if path == "" or self._is_virtual_path(path):
            return
        payload = await read_file(path, "HEAD")
        if payload is None:
            return
        if not self.split_open:
            await self.on_split(event)
        split = self.editor_b
        if split is None:
            return
        split.open_document("head:" + path, payload["content"])
        self._focus_split()

    async def _load_git(self, editor: GpuTextEditor) -> None:
        path = editor.path
        if self._is_virtual_path(path):
            editor.set_git([], [], [])
            editor.render()
            return
        response = await fetch("/api/git?path=" + encodeURIComponent(path))
        if not response.ok:
            return
        payload: GitPayload = JSON.parse(await response.text())
        last = editor.buffer.get_line_count()
        kinds: list[int] = []
        authors: list[str] = []
        summaries: list[str] = []
        line = 1
        while line <= last:
            kinds.append(0)
            authors.append("")
            summaries.append("")
            line = line + 1
        gi = 0
        while gi < len(payload["gutter"]):
            mark = payload["gutter"][gi]
            ln = mark["line"]
            if ln >= 1 and ln <= last:
                kind = 0
                raw = mark["kind"]
                if raw == "add":
                    kind = 1
                elif raw == "mod":
                    kind = 2
                elif raw == "del":
                    kind = 3
                kinds[ln - 1] = kind
            gi = gi + 1
        bi = 0
        while bi < len(payload["blame"]):
            row = payload["blame"][bi]
            ln = row["line"]
            if ln >= 1 and ln <= last:
                authors[ln - 1] = row["author"]
                summaries[ln - 1] = row["summary"]
            bi = bi + 1
        editor.set_git(kinds, authors, summaries)
        editor.render()
        self.sync_status()

    async def _poll_one(self, editor: GpuTextEditor | None) -> None:
        if editor is None:
            return
        path = editor.path
        if self._is_virtual_path(path):
            return
        payload = await read_file(path)
        if payload is None:
            return
        mtime = payload["mtime"]
        if mtime == 0 or mtime == editor.disk_mtime:
            if editor.disk_mtime == 0:
                editor.disk_mtime = mtime
            return
        dirty = editor.buffer.get_value() != self.saved_content
        if self.focused_split == 1:
            dirty = False
            if (
                self.active_tab >= 0
                and self.active_tab < len(self.tabs)
                and editor.path == self.tabs[self.active_tab].path
            ):
                dirty = editor.buffer.get_value() != self.tabs[self.active_tab].saved
        else:
            dirty = editor.buffer.get_value() != self.saved_content
        editor.disk_mtime = mtime
        if dirty:
            return
        editor.open_document(path, payload["content"])
        editor.disk_mtime = mtime
        if editor is self.editor:
            self.saved_content = payload["content"]
            self._store_local_content(path, payload["content"])
            if (
                self.active_tab >= 0
                and self.active_tab < len(self.tabs)
                and self.tabs[self.active_tab].path == path
            ):
                self.tabs[self.active_tab].content = payload["content"]
                self.tabs[self.active_tab].saved = payload["content"]
        await self._load_git(editor)
        self.sync_status()

    async def _poll_disk(self) -> None:
        if self.poll_busy:
            return
        self.poll_busy = True
        await self._poll_one(self.primary)
        if self.split_open:
            await self._poll_one(self.editor_b)
        await self._refresh_git_tree()
        await self.load_chat()
        self.poll_busy = False

    async def initialize(self):
        self._resize_callback: Callable[[Event], None] = self.on_window_resize
        self.debug_revision = -1
        self.debug_busy = False
        # Hydration skips _create(), so constructor fields like entries and
        # collapsed are missing until this runs. Rebuild the tree from the
        # server when the API is available; keep the constructor tree in tests.
        self.collapsed = []
        self.tab_name = "untitled"
        self.saved_content = "Hello, Zepy\n\nOpen a file from the explorer."
        self.palette_hits = []
        self.palette_index = 0
        self.quick_hits = []
        self.quick_index = 0
        self.split_open = False
        self.focused_split = 0
        self.poll_busy = False
        self.git_changes = []
        self.sidebar_view = "explorer"
        self.git_scope = "dirty"
        stored_scope = localStorage.getItem("zepy-git-scope")
        if stored_scope == "unpushed":
            self.git_scope = "unpushed"
        self.review_files = []
        self.viewed_paths = []
        self.chat_stamp = ""
        self.hide_ws = localStorage.getItem("zepy-hide-ws") == "1"
        self.review_wide = False
        self.review_plus = 0
        self.review_minus = 0
        self.review_return_line = 0
        self.review_return_path = ""
        self.git_stamp = ""
        self.chat_partial = ""
        self.chat_idle = True
        self.sidebar_width = self._read_stored_width("zepy-sidebar-width", 240, 160, 560)
        self.chat_width = self._read_stored_width("zepy-chat-width", 320, 200, 720)
        self.drag_kind = ""
        self.drag_origin = 0
        self.drag_start_width = 0
        self.comment_path = ""
        self.comment_snippet = ""
        self.comment_start = 0
        self.comment_end = 0
        self.comment_held = False
        self.search_query = ""
        self.chat_rendered_count = -1
        self.chat_rendered_partial = ""
        self.chat_messages = []
        self.chat_session = ""
        self.chat_busy = False
        self.chat_open = True
        if "debugTarget=1" in location.search or localStorage.getItem("zepy-chat-open") == "0":
            self.chat_open = False
        self.editor_b = None
        self.primary = None
        window.addEventListener("resize", self._resize_callback)
        self.scm_pane.setAttribute("hidden", "")
        if self.chat_open:
            self.chat_pane.removeAttribute("hidden")
            self.chat_split.removeAttribute("hidden")
            self.activity_chat.setAttribute("data-active", "true")
        else:
            self.chat_pane.setAttribute("hidden", "")
            self.chat_split.setAttribute("hidden", "")
            self.activity_chat.setAttribute("data-active", "false")
        self._apply_pane_widths()
        self._clear_comment_pin()
        if self.hide_ws:
            self.hide_ws_button.setAttribute("data-active", "true")
        self._sync_scope_buttons()
        self.explorer_pane.removeAttribute("hidden")
        self.activity_explorer.setAttribute("data-active", "true")
        self.activity_scm.setAttribute("data-active", "false")
        self.sidebar_title.textContent = "Explorer"
        self.tabs = []
        self.tabs.append(
            OpenTab(
                "untitled",
                "untitled",
                self.saved_content,
                self.saved_content,
            )
        )
        self.active_tab = 0
        self._render_tabs()
        loaded = await workspace_tree()
        if loaded is not None:
            self.entries = loaded
            self._render_tree()
        self._bind_editor_events(self.stage)
        self.pane.addEventListener("mousedown", self.on_pane_focus)
        self.editor = await create_gpu_text_editor(self.stage, self.input, self.saved_content)
        self.primary = self.editor
        if self.editor is None:
            self.status_cursor.textContent = "WebGPU unavailable"
            return
        self._attach_editor_scrollbars(
            self.editor, self.vscroll, self.vthumb, self.hscroll, self.hthumb
        )
        if self.active_tab >= 0 and self.active_tab < len(self.tabs):
            tab = self.tabs[self.active_tab]
            if tab.path != "untitled":
                self._load_tab(self.active_tab)
        self._resize_editors()
        self.sync_status()
        query = location.search
        if "review=unpushed" in query:
            await self.set_git_scope("unpushed")
            await self.open_review()
        elif "review=dirty" in query:
            await self.open_review()
        self.editor.focus()
        await self.load_chat()
        await self._refresh_git_tree()
        setInterval(self._poll_disk, 2500)
        if is_desktop() and "debugTarget=1" not in location.search:
            self.debug_toggle.removeAttribute("hidden")
            setInterval(self._poll_debug, 350)


def main(tree_json: str = "[]"):
    return App(tree_json)


__all__ = ["App", "main"]
