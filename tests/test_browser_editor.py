from typing import cast

import pytest
from pyjs import js
from pyjs.testing.webgpu import assert_webgpu_render, require_webgpu_adapter
from pyjs.web.dom import document, window
from pyjs.web.domx import canvas, div, textarea
from pyjs.web.events import KeyboardEvent, WheelEvent
from pyjs.web.html import HTMLElement

from zepy.editor.browser.gpu_text_editor import GpuTextEditor, create_gpu_text_editor
from zepy.editor.common.core.position import Position
from zepy.editor.common.vim import MODE_INSERT, MODE_NORMAL, MODE_VISUAL_BLOCK

pytestmark = pytest.mark.pyjs_web


@js
async def test_gpu_editor_backing_store_matches_device_pixels():
    await require_webgpu_adapter()
    stage = canvas()
    stage.setAttribute("style", "display:block; width:320px; height:200px")
    field = textarea()
    document.body.append(stage)
    document.body.append(field)
    editor = await create_gpu_text_editor(stage, field, "Hi")
    if editor is None:
        raise RuntimeError("expected GPU editor")
    ratio = max(window.devicePixelRatio, 1.0)
    assert stage.width == int(320.0 * ratio)
    assert stage.height == int(200.0 * ratio)
    assert editor.glyphs.rasterizer.device_pixel_ratio == ratio


@js
async def test_gpu_editor_vertical_scrollbar_tracks_a_long_file():
    await require_webgpu_adapter()
    stage = canvas()
    stage.setAttribute("style", "display:block; width:320px; height:160px")
    field = textarea()
    vthumb = div({"data-testid": "vthumb"})
    vtrack = div(
        {"data-testid": "vtrack", "style": "height:160px;width:10px;position:relative"},
        vthumb,
    )
    hthumb = div({"data-testid": "hthumb"})
    htrack = div(
        {"data-testid": "htrack", "style": "height:10px;width:320px;position:relative"},
        hthumb,
    )
    document.body.append(stage)
    document.body.append(field)
    document.body.append(vtrack)
    document.body.append(htrack)
    rows: list[str] = []
    index = 0
    while index < 80:
        rows.append("line")
        index = index + 1
    editor = await create_gpu_text_editor(stage, field, "\n".join(rows))
    if editor is None:
        raise RuntimeError("expected GPU editor")
    editor.attach_scrollbars(
        cast(HTMLElement, vtrack),
        cast(HTMLElement, vthumb),
        cast(HTMLElement, htrack),
        cast(HTMLElement, hthumb),
    )
    editor.render()
    assert editor.max_scroll() > 0.0
    assert vthumb.getAttribute("hidden") is None
    style = vthumb.getAttribute("style") or ""
    assert "height:" in style
    editor.scroll_y = editor.max_scroll()
    editor.render()
    bottom = vthumb.getAttribute("style") or ""
    assert "top:" in bottom


@js
async def test_gpu_editor_renders_hello_zepy():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 400
    stage.setAttribute("style", "display:block; width:640px; height:400px")
    field = textarea()
    document.body.setAttribute("style", "margin:0; background:#111827")
    document.body.append(stage)
    editor = await create_gpu_text_editor(stage, field, "Hello, Zepy")
    if editor is None:
        raise RuntimeError("expected GPU editor")
    assert editor.buffer.get_line_content(1) == "Hello, Zepy"
    editor.render()
    await assert_webgpu_render(editor.device, stage, "hello_zepy")


@js
async def test_gpu_editor_inserts_typed_text():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 400
    field = textarea()
    document.body.append(stage)
    editor = await create_gpu_text_editor(stage, field, "Hi")
    if editor is None:
        raise RuntimeError("expected GPU editor")
    editor.cursor = editor.buffer.get_position_at(editor.buffer.get_length())
    editor.insert("!")
    editor.insert("\n")
    editor.insert("Z")
    assert editor.buffer.get_value() == "Hi!\nZ"
    editor.backspace()
    assert editor.buffer.get_value() == "Hi!\n"
    editor.render()
    await assert_webgpu_render(editor.device, stage, "typed_text")


@js
async def test_gpu_editor_undoes_and_redoes_inserts():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 400
    field = textarea()
    document.body.append(stage)
    editor = await create_gpu_text_editor(stage, field, "Hi")
    if editor is None:
        raise RuntimeError("expected GPU editor")
    editor.cursor = editor.buffer.get_position_at(editor.buffer.get_length())
    editor.insert("!")
    assert editor.buffer.get_value() == "Hi!"
    editor.undo()
    assert editor.buffer.get_value() == "Hi"
    editor.redo()
    assert editor.buffer.get_value() == "Hi!"


@js
async def test_gpu_editor_scrolls_on_mouse_wheel():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 200
    field = textarea()
    document.body.append(stage)
    document.body.append(field)
    rows: list[str] = []
    index = 0
    while index < 80:
        rows.append("line")
        index = index + 1
    editor = await create_gpu_text_editor(stage, field, "\n".join(rows))
    if editor is None:
        raise RuntimeError("expected GPU editor")
    assert editor.max_scroll() > 0.0
    editor.scroll_y = 0.0
    field.dispatchEvent(WheelEvent("wheel", deltaY=240.0, deltaMode=0, cancelable=True))
    assert editor.scroll_y > 0.0


@js
async def test_gpu_editor_opens_a_document_with_line_numbers():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 400
    field = textarea()
    document.body.append(stage)
    editor = await create_gpu_text_editor(stage, field, "")
    if editor is None:
        raise RuntimeError("expected GPU editor")
    editor.open_document("notes.txt", "alpha\nbeta\ngamma")
    assert editor.path == "notes.txt"
    assert editor.buffer.get_line_count() == 3
    editor.anchor = editor.buffer.get_position_at(0)
    editor.cursor = editor.buffer.get_position_at(5)
    editor.render()
    await assert_webgpu_render(editor.device, stage, "opened_file")


@js
async def test_gpu_editor_highlights_python():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 400
    field = textarea()
    document.body.setAttribute("style", "margin:0; background:#111827")
    document.body.append(stage)
    editor = await create_gpu_text_editor(stage, field, "")
    if editor is None:
        raise RuntimeError("expected GPU editor")
    editor.open_document(
        "hello.py",
        'def greet(name):\n    # hi\n    return "Zepy"\n',
    )
    assert editor.path == "hello.py"
    editor.render()
    await assert_webgpu_render(editor.device, stage, "python_highlight")


@js
async def test_gpu_editor_finds_the_next_match():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 400
    field = textarea()
    document.body.append(stage)
    editor = await create_gpu_text_editor(stage, field, "")
    if editor is None:
        raise RuntimeError("expected GPU editor")
    editor.open_document("notes.txt", "aaa x aaa")
    editor.set_find_query("aaa")
    assert len(editor.find_matches) == 2
    assert editor.find_index == 0
    assert editor.cursor.column == 4
    editor.find_next()
    assert editor.find_index == 1
    assert editor.cursor.line_number == 1
    assert editor.cursor.column == 10
    editor.find_next()
    assert editor.find_index == 0


@js
async def test_gpu_editor_replaces_current_and_all_matches():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 400
    field = textarea()
    document.body.append(stage)
    editor = await create_gpu_text_editor(stage, field, "")
    if editor is None:
        raise RuntimeError("expected GPU editor")
    editor.open_document("notes.txt", "aaa x aaa y aaa")
    editor.set_find_query("aaa")
    assert len(editor.find_matches) == 3
    editor.replace_current("bb")
    assert editor.buffer.get_value() == "bb x aaa y aaa"
    assert len(editor.find_matches) == 2
    editor.replace_all("cc")
    assert editor.buffer.get_value() == "bb x cc y cc"
    editor.undo()
    assert editor.buffer.get_value() == "bb x aaa y aaa"


@js
def press_editor(editor: GpuTextEditor, key: str) -> None:
    editor.input.dispatchEvent(KeyboardEvent("keydown", key=key, bubbles=True, cancelable=True))


@js
async def test_vim_hjkl_and_word_motions():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 400
    field = textarea()
    document.body.append(stage)
    editor = await create_gpu_text_editor(stage, field, "foo bar\nbaz")
    if editor is None:
        raise RuntimeError("expected GPU editor")
    assert editor.vim.mode == MODE_NORMAL
    assert editor.cursor.column == 1
    press_editor(editor, "l")
    assert editor.cursor.column == 2
    press_editor(editor, "w")
    assert editor.cursor.column == 5
    press_editor(editor, "j")
    assert editor.cursor.line_number == 2
    press_editor(editor, "0")
    assert editor.cursor.column == 1
    press_editor(editor, "$")
    assert editor.cursor.column == 3
    press_editor(editor, "g")
    press_editor(editor, "g")
    assert editor.cursor.line_number == 1


@js
async def test_vim_insert_escape_and_delete_char():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 400
    field = textarea()
    document.body.append(stage)
    editor = await create_gpu_text_editor(stage, field, "ab")
    if editor is None:
        raise RuntimeError("expected GPU editor")
    press_editor(editor, "i")
    assert editor.vim.mode == MODE_INSERT
    editor.insert("x")
    press_editor(editor, "Escape")
    assert editor.vim.mode == MODE_NORMAL
    assert editor.buffer.get_value() == "xab"
    press_editor(editor, "x")
    assert editor.buffer.get_value() == "ab"


@js
async def test_vim_find_char_and_percent():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 400
    field = textarea()
    document.body.append(stage)
    editor = await create_gpu_text_editor(stage, field, "foo (bar)")
    if editor is None:
        raise RuntimeError("expected GPU editor")
    press_editor(editor, "f")
    press_editor(editor, "b")
    assert editor.cursor.column == 6
    press_editor(editor, ";")
    assert editor.cursor.column == 6
    press_editor(editor, "0")
    press_editor(editor, "f")
    press_editor(editor, "(")
    press_editor(editor, "%")
    assert editor.cursor.column == 9


@js
async def test_vim_visual_line_yank_delete_and_join():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 400
    field = textarea()
    document.body.append(stage)
    editor = await create_gpu_text_editor(stage, field, "a\nb\nc")
    if editor is None:
        raise RuntimeError("expected GPU editor")
    press_editor(editor, "d")
    press_editor(editor, "d")
    assert editor.buffer.get_value() == "b\nc"
    press_editor(editor, "p")
    assert editor.buffer.get_value() == "b\na\nc"
    editor.open_document("t.txt", "a\nb\nc")
    press_editor(editor, "V")
    press_editor(editor, "y")
    assert editor.vim.mode == MODE_NORMAL
    press_editor(editor, "p")
    assert editor.buffer.get_value() == "a\na\nb\nc"
    editor.open_document("t.txt", "a\nb\nc")
    press_editor(editor, "V")
    press_editor(editor, "d")
    assert editor.buffer.get_value() == "b\nc"
    editor.open_document("t.txt", "foo\nbar")
    press_editor(editor, "J")
    assert editor.buffer.get_value() == "foo bar"


@js
async def test_vim_replace_dot_indent_and_word_object():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 400
    field = textarea()
    document.body.append(stage)
    editor = await create_gpu_text_editor(stage, field, "abc")
    if editor is None:
        raise RuntimeError("expected GPU editor")
    press_editor(editor, "r")
    press_editor(editor, "z")
    assert editor.buffer.get_value() == "zbc"
    press_editor(editor, ".")
    assert editor.buffer.get_value() == "zzc"
    editor.open_document("t.txt", "foo")
    press_editor(editor, ">")
    press_editor(editor, ">")
    assert editor.buffer.get_line_content(1) == "    foo"
    press_editor(editor, "d")
    press_editor(editor, "i")
    press_editor(editor, "w")
    assert "foo" not in editor.buffer.get_value()


@js
def press_ctrl(editor: GpuTextEditor, key: str) -> None:
    editor.input.dispatchEvent(
        KeyboardEvent(
            "keydown",
            key=key,
            ctrlKey=True,
            bubbles=True,
            cancelable=True,
        )
    )


@js
async def test_vim_visual_block_delete_and_yank():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 400
    field = textarea()
    document.body.append(stage)
    editor = await create_gpu_text_editor(stage, field, "aaa\nbbb\nccc")
    if editor is None:
        raise RuntimeError("expected GPU editor")
    press_ctrl(editor, "v")
    assert editor.vim.mode == MODE_VISUAL_BLOCK
    press_editor(editor, "l")
    press_editor(editor, "j")
    press_editor(editor, "d")
    assert editor.vim.mode == MODE_NORMAL
    assert editor.buffer.get_value() == "a\nb\nccc"
    editor.open_document("t.txt", "aaa\nbbb\nccc")
    press_ctrl(editor, "v")
    press_editor(editor, "l")
    press_editor(editor, "j")
    press_editor(editor, "y")
    assert editor.buffer.get_value() == "aaa\nbbb\nccc"
    assert editor.vim.yank == "aa\nbb"
    assert editor.vim.yank_block


@js
async def test_vim_quote_and_bracket_text_objects():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 400
    field = textarea()
    document.body.append(stage)
    editor = await create_gpu_text_editor(stage, field, 'say "hi" now')
    if editor is None:
        raise RuntimeError("expected GPU editor")
    press_editor(editor, "f")
    press_editor(editor, "h")
    press_editor(editor, "c")
    press_editor(editor, "i")
    press_editor(editor, '"')
    assert editor.buffer.get_value() == 'say "" now'
    press_editor(editor, "Escape")
    editor.open_document("t.txt", "x[ab]y")
    press_editor(editor, "f")
    press_editor(editor, "a")
    press_editor(editor, "d")
    press_editor(editor, "i")
    press_editor(editor, "[")
    assert editor.buffer.get_value() == "x[]y"


@js
async def test_vim_marks_registers_jumps_and_ex():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 400
    field = textarea()
    document.body.append(stage)
    editor = await create_gpu_text_editor(stage, field, "one\ntwo\nthree")
    if editor is None:
        raise RuntimeError("expected GPU editor")
    press_editor(editor, "m")
    press_editor(editor, "a")
    press_editor(editor, "G")
    assert editor.cursor.line_number == 3
    press_editor(editor, "`")
    press_editor(editor, "a")
    assert editor.cursor.line_number == 1
    press_ctrl(editor, "o")
    assert editor.cursor.line_number == 3
    editor.open_document("t.txt", "alpha\nbeta")
    press_editor(editor, '"')
    press_editor(editor, "a")
    press_editor(editor, "y")
    press_editor(editor, "y")
    press_editor(editor, "j")
    press_editor(editor, '"')
    press_editor(editor, "a")
    press_editor(editor, "p")
    assert editor.buffer.get_value() == "alpha\nbeta\nalpha"
    editor.open_document("t.txt", "a\nb\nc")
    press_editor(editor, ":")
    press_editor(editor, "2")
    press_editor(editor, "Enter")
    assert editor.cursor.line_number == 2
    editor.set_find_query("b")
    assert editor.find_query == "b"
    press_editor(editor, ":")
    press_editor(editor, "n")
    press_editor(editor, "o")
    press_editor(editor, "h")
    press_editor(editor, "Enter")
    assert editor.find_query == ""
    editor._run_ex("e src/hello.py")
    assert editor.pending_open == "src/hello.py"


@js
async def test_newline_indent_horizontal_scroll_and_folds():
    await require_webgpu_adapter()
    stage = canvas()
    stage.width = 640
    stage.height = 400
    field = textarea()
    document.body.append(stage)
    editor = await create_gpu_text_editor(stage, field, "    foo")
    if editor is None:
        raise RuntimeError("expected GPU editor")
    editor.cursor = editor.buffer.get_position_at(editor.buffer.get_length())
    editor.insert("\n")
    assert editor.buffer.get_value() == "    foo\n    "
    editor.clip = "Z"
    editor.insert(editor.clip)
    assert editor.buffer.get_value() == "    foo\n    Z"
    editor.open_document("t.txt", "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    editor.cursor = Position(1, 40)
    editor.ensure_visible()
    assert editor.scroll_x >= 0.0
    editor.scroll_x = 40.0
    editor.render()
    assert editor.scroll_x == 40.0
    editor.open_document("t.py", "def f():\n    x = 1\n    y = 2\nz = 3")
    press_editor(editor, "z")
    press_editor(editor, "a")
    assert len(editor.fold_starts) == 1
    assert editor.fold_starts[0] == 1
    press_editor(editor, "j")
    assert editor.cursor.line_number == 4
