from typing import Final

import pytest
from pyjs import JS, js
from pyjs.testing.web import bubbling_click, mount, selector_count, wait_for_frames
from pyjs.testing.webgpu import require_webgpu_adapter
from pyjs.web.dom import document, localStorage
from pyjs.web.domx import require_element
from pyjs.web.events import Event, KeyboardEvent, MouseEvent, WheelEvent

from zepy.app import App
from zepy.editor.common.core.position import Position

pytestmark = pytest.mark.pyjs_web

TREE: Final[JS] = (
    "["
    '{"name":"src","path":"src","kind":"dir","depth":0,"content":"","git":"mod"},'
    '{"name":"hello.py","path":"src/hello.py","kind":"file","depth":1,'
    '"content":"print(1)","git":"mod"},'
    '{"name":"notes.txt","path":"src/notes.txt","kind":"file","depth":1,'
    '"content":"aaa","git":""},'
    '{"name":"new.py","path":"src/new.py","kind":"file","depth":1,'
    '"content":"","git":"untracked"}'
    "]"
)


@js
def mounted_app() -> App:
    app = App(TREE)
    mount(app)
    return app


@js
async def wait_for_editor(app: App) -> None:
    frames = 0
    while app.editor is None and frames < 90:
        await wait_for_frames(1)
        frames = frames + 1
    if app.editor is None:
        raise RuntimeError("expected GPU editor after initialize")


@js
def test_explorer_shows_files_and_folders():
    app = mounted_app()

    assert selector_count(app, "[data-testid='explorer']") == 1
    assert selector_count(app, "[data-kind='dir']") == 1
    assert selector_count(app, "[data-kind='file']") == 3
    assert "hello.py" in require_element(app, "[data-path='src/hello.py']").textContent


@js
def test_explorer_colors_git_changes_and_parent_folders():
    app = mounted_app()
    changed = require_element(app, "[data-path='src/hello.py']")
    folder = require_element(app, "[data-path='src']")
    clean = require_element(app, "[data-path='src/notes.txt']")
    added = require_element(app, "[data-path='src/new.py']")
    assert changed.getAttribute("data-git") == "mod"
    assert folder.getAttribute("data-git") == "mod"
    assert clean.getAttribute("data-git") == ""
    assert added.getAttribute("data-git") == "untracked"
    changed_class = changed.getAttribute("class")
    folder_class = folder.getAttribute("class")
    added_class = added.getAttribute("class")
    clean_class = clean.getAttribute("class")
    if changed_class is None or folder_class is None or added_class is None or clean_class is None:
        raise RuntimeError("expected explorer item classes")
    assert "text-[#e2c08d]" in changed_class
    assert "text-[#e2c08d]" in folder_class
    assert "text-[#73c991]" in added_class
    assert "text-zinc-300" in clean_class


@js
def test_explorer_and_chat_use_themed_scrollbars():
    app = mounted_app()
    assert selector_count(app, "[data-testid='explorer-scroll']") == 1
    assert selector_count(app, "[data-slot='message-scroller-viewport']") == 1
    assert selector_count(app, "[data-testid='editor-vscroll']") == 1
    assert selector_count(app, "[data-slot='button-group']") == 1
    assert selector_count(app, "[data-slot='resizable-handle']") >= 2


@js
async def test_chat_log_stays_scrolled_to_the_latest_message():
    app = mounted_app()
    app.chat_log.viewport.style.setProperty("height", "80px")
    app.chat_log.viewport.style.setProperty("max-height", "80px")
    app._append_chat("user", "first\n\n\n\n\nmore")
    app._append_chat("assistant", "second\n\n\n\n\nmore")
    app._append_chat("user", "third\n\n\n\n\nmore")
    await wait_for_frames(4)
    assert selector_count(app, "[data-slot='message']") >= 1
    assert selector_count(app, "[data-slot='bubble']") >= 1
    assert app.chat_log.mode == "anchored-to-message" or app.chat_log.is_at_latest()


@js
async def test_chat_log_keeps_place_when_not_following():
    app = mounted_app()
    app.chat_log.viewport.style.setProperty("height", "80px")
    app.chat_log.viewport.style.setProperty("max-height", "80px")
    app._append_chat("user", "first\n\n\n\n\nmore")
    app._append_chat("assistant", "second\n\n\n\n\nmore")
    app._append_chat("user", "third\n\n\n\n\nmore")
    await wait_for_frames(4)
    app.chat_log.viewport.dispatchEvent(
        WheelEvent("wheel", deltaY=-80, bubbles=True, cancelable=True)
    )
    await wait_for_frames(2)
    assert not app.chat_log.is_at_latest()
    place = app.chat_log.viewport.scrollTop
    app._append_chat("assistant", "later\n\n\n\n\nmore")
    await wait_for_frames(4)
    assert app.chat_log.viewport.scrollTop == place
    assert not app.chat_log.is_at_latest()


@js
def test_codex_chat_pane_toggles():
    app = mounted_app()
    assert not app.chat_pane.hasAttribute("hidden")
    bubbling_click(require_element(app, "[data-testid='activity-chat']"))
    assert app.chat_pane.hasAttribute("hidden")
    bubbling_click(require_element(app, "[data-testid='activity-chat']"))
    assert not app.chat_pane.hasAttribute("hidden")
    assert selector_count(app, "[data-testid='chat-input']") == 1
    assert selector_count(app, "[data-testid='chat-send']") == 1


@js
async def test_sidebar_and_chat_panes_resize_by_dragging_dividers():
    localStorage.removeItem("zepy-sidebar-width")
    localStorage.removeItem("zepy-chat-width")
    app = mounted_app()
    await wait_for_frames(8)
    assert selector_count(app, "[data-testid='sidebar-split']") == 1
    assert selector_count(app, "[data-testid='chat-split']") == 1
    sidebar = require_element(app, "[data-testid='sidebar']")
    chat = require_element(app, "[data-testid='chat-pane']")
    assert sidebar.style.width == "240px"
    assert chat.style.width == "320px"

    require_element(app, "[data-testid='sidebar-split']").dispatchEvent(
        MouseEvent("mousedown", bubbles=True, cancelable=True, clientX=240)
    )
    document.dispatchEvent(MouseEvent("mousemove", bubbles=True, clientX=300))
    document.dispatchEvent(MouseEvent("mouseup", bubbles=True, clientX=300))
    assert sidebar.style.width == "300px"
    assert localStorage.getItem("zepy-sidebar-width") == "300"

    require_element(app, "[data-testid='chat-split']").dispatchEvent(
        MouseEvent("mousedown", bubbles=True, cancelable=True, clientX=800)
    )
    document.dispatchEvent(MouseEvent("mousemove", bubbles=True, clientX=860))
    document.dispatchEvent(MouseEvent("mouseup", bubbles=True, clientX=860))
    assert chat.style.width == "260px"
    assert localStorage.getItem("zepy-chat-width") == "260"

    bubbling_click(require_element(app, "[data-testid='activity-chat']"))
    assert app.chat_split.hasAttribute("hidden")
    bubbling_click(require_element(app, "[data-testid='activity-chat']"))
    assert not app.chat_split.hasAttribute("hidden")


@js
def test_source_control_has_scope_toggles():
    app = mounted_app()
    bubbling_click(require_element(app, "[data-testid='activity-scm']"))
    assert require_element(app, "[data-testid='scope-dirty']").getAttribute("data-active") == "true"
    assert (
        require_element(app, "[data-testid='scope-unpushed']").getAttribute("data-active")
        == "false"
    )
    assert selector_count(app, "[data-testid='review-all']") == 1


@js
def test_source_control_lists_changed_files():
    app = mounted_app()
    assert app.scm_pane.hasAttribute("hidden")
    bubbling_click(require_element(app, "[data-testid='activity-scm']"))
    assert not app.scm_pane.hasAttribute("hidden")
    assert app.explorer_pane.hasAttribute("hidden")
    assert app.sidebar_title.textContent == "Source Control"
    assert selector_count(app, "[data-testid='scm-item']") == 2
    changed = require_element(app, "[data-testid='scm-item'][data-path='src/hello.py']")
    added = require_element(app, "[data-testid='scm-item'][data-path='src/new.py']")
    assert changed.getAttribute("data-git") == "mod"
    assert added.getAttribute("data-git") == "untracked"
    assert "M  src/hello.py" in changed.textContent
    bubbling_click(require_element(app, "[data-testid='activity-explorer']"))
    assert not app.explorer_pane.hasAttribute("hidden")
    assert app.scm_pane.hasAttribute("hidden")


@js
def test_clicking_a_file_opens_it_in_the_tab():
    app = mounted_app()
    bubbling_click(require_element(app, "[data-path='src/hello.py']"))

    assert app.tab_label.textContent == "hello.py"
    assert "src/hello.py" in app.title_label.textContent


@js
def test_clicking_a_folder_hides_and_shows_its_files():
    app = mounted_app()
    bubbling_click(require_element(app, "[data-path='src']"))
    assert selector_count(app, "[data-path='src/hello.py']") == 0

    bubbling_click(require_element(app, "[data-path='src']"))
    assert selector_count(app, "[data-path='src/hello.py']") == 1


@js
async def test_explorer_keeps_its_files_after_initialize():
    app = mounted_app()
    await wait_for_frames(30)

    assert selector_count(app, "[data-testid='explorer']") == 1
    assert selector_count(app, "[data-kind='file']") == 3
    assert selector_count(app, "[data-path='src/hello.py']") == 1


@js
async def test_clicking_a_file_loads_it_into_the_editor():
    await require_webgpu_adapter()
    app = mounted_app()
    await wait_for_editor(app)
    bubbling_click(require_element(app, "[data-path='src/hello.py']"))
    await wait_for_frames(1)
    editor = app.editor
    if editor is None:
        raise RuntimeError("expected GPU editor after initialize")
    assert editor.path == "src/hello.py"
    assert editor.buffer.get_value() == "print(1)"


@js
async def test_selecting_lines_shows_a_comment_bar_for_codex():
    await require_webgpu_adapter()
    app = mounted_app()
    await wait_for_editor(app)
    editor = app.editor
    if editor is None:
        raise RuntimeError("expected GPU editor after initialize")
    editor.open_document("src/hello.py", "alpha\nbeta\ngamma\n")
    editor.anchor = Position(1, 1)
    editor.set_cursor(Position(3, 2), True)
    app.sync_status()
    assert not app.comment_bar.hasAttribute("hidden")
    assert "hello.py:1-3" in app.comment_label.textContent
    bubbling_click(require_element(app, "[data-testid='comment-ask']"))
    await wait_for_frames(1)
    assert not app.comment_chip.hasAttribute("hidden")
    assert "Attached hello.py:1-3" in app.comment_chip_label.textContent
    payload = app._selection_prompt("what changed?")
    assert payload["path"] == "src/hello.py"
    assert payload["line"] == 1
    assert payload["end_line"] == 3
    assert "1| alpha" in payload["selection"]
    assert "3| gamma" in payload["selection"]
    assert payload["text"] == "what changed?"
    bubbling_click(require_element(app, "[data-testid='comment-clear']"))
    assert app.comment_bar.hasAttribute("hidden")
    assert app.comment_snippet == ""


@js
async def test_typing_marks_the_tab_dirty_and_undo_clears_it():
    await require_webgpu_adapter()
    app = mounted_app()
    await wait_for_editor(app)
    bubbling_click(require_element(app, "[data-path='src/hello.py']"))
    await wait_for_frames(1)
    editor = app.editor
    if editor is None:
        raise RuntimeError("expected GPU editor after initialize")
    assert app.tab_label.getAttribute("data-dirty") == "false"
    editor.insert("!")
    app.sync_status()
    assert app.tab_label.getAttribute("data-dirty") == "true"
    assert "● " in app.tab_label.textContent
    app.input.dispatchEvent(
        KeyboardEvent("keydown", key="z", ctrlKey=True, bubbles=True, cancelable=True)
    )
    await wait_for_frames(1)
    assert app.tab_label.getAttribute("data-dirty") == "false"
    assert app.tab_label.textContent == "hello.py"
    assert editor.buffer.get_value() == "print(1)"


@js
async def test_find_widget_lists_and_advances_matches():
    await require_webgpu_adapter()
    app = mounted_app()
    await wait_for_editor(app)
    bubbling_click(require_element(app, "[data-path='src/hello.py']"))
    await wait_for_frames(1)
    editor = app.editor
    if editor is None:
        raise RuntimeError("expected GPU editor after initialize")
    assert app.find_bar.hasAttribute("hidden")
    app.input.dispatchEvent(
        KeyboardEvent("keydown", key="f", ctrlKey=True, bubbles=True, cancelable=True)
    )
    await wait_for_frames(1)
    assert not app.find_bar.hasAttribute("hidden")
    app.find_field.value = "t"
    app.find_field.dispatchEvent(Event("input", bubbles=True))
    await wait_for_frames(1)
    assert len(editor.find_matches) == 1
    assert "1 of 1" in app.find_count.textContent
    bubbling_click(require_element(app, "[data-testid='find-close']"))
    await wait_for_frames(1)
    assert app.find_bar.hasAttribute("hidden")
    assert editor.find_query == ""


@js
async def test_replace_all_rewrites_every_match():
    await require_webgpu_adapter()
    app = mounted_app()
    await wait_for_editor(app)
    editor = app.editor
    if editor is None:
        raise RuntimeError("expected GPU editor after initialize")
    editor.open_document("src/hello.py", "aaa x aaa")
    app.show_find()
    app.find_field.value = "aaa"
    app.find_field.dispatchEvent(Event("input", bubbles=True))
    await wait_for_frames(1)
    app.replace_field.value = "bb"
    bubbling_click(require_element(app, "[data-testid='replace-all']"))
    await wait_for_frames(1)
    assert editor.buffer.get_value() == "bb x bb"
    assert app.tab_label.getAttribute("data-dirty") == "true"


@js
async def test_status_bar_shows_vim_mode():
    await require_webgpu_adapter()
    app = mounted_app()
    await wait_for_editor(app)
    assert app.status_mode.textContent == "NORMAL"
    app.input.dispatchEvent(KeyboardEvent("keydown", key="i", bubbles=True, cancelable=True))
    await wait_for_frames(1)
    assert app.status_mode.textContent == "INSERT"
    app.input.dispatchEvent(KeyboardEvent("keydown", key="Escape", bubbles=True, cancelable=True))
    await wait_for_frames(1)
    assert app.status_mode.textContent == "NORMAL"


@js
async def test_colon_w_saves():
    await require_webgpu_adapter()
    app = mounted_app()
    await wait_for_editor(app)
    editor = app.editor
    if editor is None:
        raise RuntimeError("expected GPU editor after initialize")
    editor.open_document("src/hello.py", "print(1)")
    app.sync_status()
    assert app.command_bar.hasAttribute("hidden")
    app.input.dispatchEvent(KeyboardEvent("keydown", key=":", bubbles=True, cancelable=True))
    await wait_for_frames(1)
    assert not app.command_bar.hasAttribute("hidden")
    app.input.dispatchEvent(KeyboardEvent("keydown", key="w", bubbles=True, cancelable=True))
    await wait_for_frames(1)
    assert app.command_text.textContent == ":w"
    app.input.dispatchEvent(KeyboardEvent("keydown", key="Enter", bubbles=True, cancelable=True))
    await wait_for_frames(1)
    assert app.command_bar.hasAttribute("hidden")
    assert app.status_mode.textContent == "NORMAL"


@js
async def test_opening_two_files_keeps_both_tabs():
    await require_webgpu_adapter()
    app = mounted_app()
    await wait_for_editor(app)
    bubbling_click(require_element(app, "[data-path='src/hello.py']"))
    await wait_for_frames(1)
    bubbling_click(require_element(app, "[data-path='src/notes.txt']"))
    await wait_for_frames(1)
    assert selector_count(app, "[data-testid='tab']") == 2
    editor = app.editor
    if editor is None:
        raise RuntimeError("expected GPU editor after initialize")
    assert editor.path == "src/notes.txt"
    assert editor.buffer.get_value() == "aaa"
    bubbling_click(require_element(app, "[data-path='src/hello.py'][data-testid='tab']"))
    await wait_for_frames(1)
    editor = app.editor
    if editor is None:
        raise RuntimeError("expected GPU editor after initialize")
    assert editor.path == "src/hello.py"
    assert editor.buffer.get_value() == "print(1)"


@js
async def test_command_palette_opens_from_the_keyboard():
    await require_webgpu_adapter()
    app = mounted_app()
    await wait_for_editor(app)
    assert app.palette.hasAttribute("hidden")
    app.input.dispatchEvent(
        KeyboardEvent(
            "keydown",
            key="P",
            ctrlKey=True,
            shiftKey=True,
            bubbles=True,
            cancelable=True,
        )
    )
    await wait_for_frames(1)
    assert not app.palette.hasAttribute("hidden")
    assert selector_count(app, "[data-testid='palette-item']") >= 3
    app.command_palette.input.dispatchEvent(
        KeyboardEvent("keydown", key="Escape", bubbles=True, cancelable=True)
    )
    await wait_for_frames(1)
    assert app.palette.hasAttribute("hidden")


@js
async def test_quick_open_lists_files():
    await require_webgpu_adapter()
    app = mounted_app()
    await wait_for_editor(app)
    assert app.quick_panel.hasAttribute("hidden")
    app.input.dispatchEvent(
        KeyboardEvent(
            "keydown",
            key="p",
            ctrlKey=True,
            bubbles=True,
            cancelable=True,
        )
    )
    await wait_for_frames(1)
    assert not app.quick_panel.hasAttribute("hidden")
    assert selector_count(app, "[data-testid='quick-open-item']") >= 2
    app.quick_command.input.value = "hello"
    app.quick_command.input.dispatchEvent(Event("input", bubbles=True))
    await wait_for_frames(1)
    assert selector_count(app, "[data-testid='quick-open-item']:not([hidden])") == 1
    app.quick_command.input.dispatchEvent(
        KeyboardEvent("keydown", key="Enter", bubbles=True, cancelable=True)
    )
    frames = 0
    editor = app.editor
    while frames < 30 and (editor is None or editor.path != "src/hello.py"):
        await wait_for_frames(1)
        editor = app.editor
        frames = frames + 1
    if editor is None:
        raise RuntimeError("expected GPU editor after initialize")
    assert editor.path == "src/hello.py"


@js
async def test_search_panel_opens_from_the_keyboard():
    await require_webgpu_adapter()
    app = mounted_app()
    await wait_for_editor(app)
    assert app.search_panel.hasAttribute("hidden")
    app.input.dispatchEvent(
        KeyboardEvent(
            "keydown",
            key="F",
            ctrlKey=True,
            shiftKey=True,
            bubbles=True,
            cancelable=True,
        )
    )
    await wait_for_frames(1)
    assert not app.search_panel.hasAttribute("hidden")
    app.search_command.input.dispatchEvent(
        KeyboardEvent("keydown", key="Escape", bubbles=True, cancelable=True)
    )
    await wait_for_frames(1)
    assert app.search_panel.hasAttribute("hidden")


@js
async def test_split_editor_opens_a_second_pane():
    await require_webgpu_adapter()
    app = mounted_app()
    await wait_for_editor(app)
    assert app.pane_b.hasAttribute("hidden")
    app.input.dispatchEvent(
        KeyboardEvent(
            "keydown",
            key="\\",
            ctrlKey=True,
            bubbles=True,
            cancelable=True,
        )
    )
    frames = 0
    while app.editor_b is None and frames < 90:
        await wait_for_frames(1)
        frames = frames + 1
    assert not app.pane_b.hasAttribute("hidden")
    assert app.split_open
    if app.editor_b is None:
        raise RuntimeError("expected split GPU editor")
    assert app.focused_split == 1
