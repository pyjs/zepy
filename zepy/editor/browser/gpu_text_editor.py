"""GPU editor with a piece buffer, glyph atlas, and caret rendering."""

from pyjs import js
from pyjs.web.events import Event, InputEvent, KeyboardEvent, MouseEvent, WheelEvent
from pyjs.web.html import HTMLCanvasElement, HTMLElement, HTMLTextAreaElement
from pyjs.web.webgpu import (
    GPUCanvasConfiguration,
    GPUColor,
    GPUDevice,
    GPURenderPassColorAttachment,
    GPURenderPassDescriptor,
    get_webgpu_context,
)

from zepy.base.common.lifecycle import Disposable
from zepy.editor.browser.environment import get_clipboard, get_document, get_gpu
from zepy.editor.browser.gpu.glyph_renderer import GlyphRenderer
from zepy.editor.browser.gpu.gpu_utils import device_pixel_ratio
from zepy.editor.browser.gpu.rectangle_renderer import RectangleRenderer
from zepy.editor.common.core.position import Position
from zepy.editor.common.core.range import Range
from zepy.editor.common.folds import (
    fold_end,
    hidden_flags,
    innermost_fold_start,
    line_at_view_index,
    visible_count_before,
    visible_line_count,
)
from zepy.editor.common.model.piece_tree_text_buffer.piece_tree_base import PieceTreeBase
from zepy.editor.common.search import find_ranges
from zepy.editor.common.tokenize import has_suffix, language_from_path
from zepy.editor.common.vim import (
    MODE_COMMAND,
    MODE_INSERT,
    MODE_NORMAL,
    MODE_VISUAL,
    MODE_VISUAL_BLOCK,
    MODE_VISUAL_LINE,
    VimState,
    bracket_span,
    clamp_normal,
    digit_value,
    ex_is_edit,
    ex_is_line_number,
    ex_is_next,
    ex_is_nohl,
    ex_is_prev,
    ex_is_write,
    ex_line_number,
    find_char,
    first_nonblank_column,
    first_word,
    letter_index,
    match_bracket,
    quote_span,
    rest_after_word,
    reverse_find_kind,
    toggle_case_char,
    word_back,
    word_end,
    word_forward,
    word_span,
)
from zepy.editor.common.wrap import (
    line_at_visual_row,
    visual_line_count,
    visual_rows_before,
    wrap_col_of_column,
    wrap_row_of_column,
)


@js
class HistoryStep:
    def __init__(self, value: str, line: int, column: int):
        self.value = value
        self.line = line
        self.column = column


@js
class GpuTextEditor(Disposable):
    def __init__(
        self,
        canvas: HTMLCanvasElement,
        input: HTMLTextAreaElement,
        device: GPUDevice,
        buffer: PieceTreeBase,
        glyphs: GlyphRenderer,
        rectangles: RectangleRenderer,
    ):
        super().__init__()
        self.canvas = canvas
        self.input = input
        self.device = device
        self.buffer = buffer
        self.glyphs = glyphs
        self.rectangles = rectangles
        self.cursor = Position(1, 1)
        self.anchor: Position | None = None
        self.scroll_y = 0.0
        self.scroll_x = 0.0
        self.path = "untitled"
        self._undo: list[HistoryStep] = []
        self._redo: list[HistoryStep] = []
        self.find_query = ""
        self.find_matches: list[Range] = []
        self.find_index = -1
        self.vim = VimState()
        self.fold_starts: list[int] = []
        self.fold_ends: list[int] = []
        self.git_kind: list[int] = []
        self.git_author: list[str] = []
        self.git_summary: list[str] = []
        self.clip = ""
        self.pending_open = ""
        self.disk_mtime = 0.0
        self.wrap = False
        self.selecting = False
        self._context = get_webgpu_context(canvas)
        self._format = get_gpu().getPreferredCanvasFormat()
        self._dpr = device_pixel_ratio()
        self._vtrack: HTMLElement | None = None
        self._vthumb: HTMLElement | None = None
        self._htrack: HTMLElement | None = None
        self._hthumb: HTMLElement | None = None
        self._bar_drag = ""
        self._bar_origin = 0.0
        self._bar_scroll = 0.0

    @staticmethod
    async def create(
        canvas: HTMLCanvasElement,
        input: HTMLTextAreaElement,
        initial: str = "Hello, Zepy",
    ) -> GpuTextEditor | None:
        if get_gpu() is None:
            return None
        adapter = await get_gpu().requestAdapter()
        if adapter is None:
            return None
        device = await adapter.requestDevice()
        context = get_webgpu_context(canvas)
        format = get_gpu().getPreferredCanvasFormat()
        context.configure(GPUCanvasConfiguration(device, format))
        glyphs = await GlyphRenderer.create(
            device,
            canvas,
            context,
            format,
            16.0,
            "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "
            '"Liberation Mono", "DejaVu Sans Mono", monospace',
            "#d4d4d4",
        )
        rectangles = await RectangleRenderer.create(device, canvas, context, format)
        buffer = PieceTreeBase(initial)
        editor = GpuTextEditor(canvas, input, device, buffer, glyphs, rectangles)
        editor._bind_input()
        editor.resize_backing_store()
        editor.render()
        return editor

    def _bind_input(self) -> None:
        self.input.addEventListener("keydown", self.on_keydown)
        self.input.addEventListener("beforeinput", self.on_before_input)
        self.input.addEventListener("mousedown", self.on_mouse_down)
        self.input.addEventListener("wheel", self.on_wheel, passive=False)
        self.canvas.addEventListener("mousedown", self.on_mouse_down)
        self.canvas.addEventListener("wheel", self.on_wheel, passive=False)
        get_document().addEventListener("mousemove", self.on_mouse_move)
        get_document().addEventListener("mouseup", self.on_mouse_up)

    def focus(self) -> None:
        self.input.focus()

    def resize_backing_store(self) -> None:
        ratio = device_pixel_ratio()
        self._dpr = ratio
        width = int(float(self.canvas.clientWidth) * ratio)
        height = int(float(self.canvas.clientHeight) * ratio)
        if width < 32 or height < 32:
            return
        if self.canvas.width == width and self.canvas.height == height:
            return
        self.canvas.width = width
        self.canvas.height = height
        self._context.configure(GPUCanvasConfiguration(self.device, self._format))
        self.sync_scrollbars()

    def _notify(self) -> None:
        self.canvas.dispatchEvent(Event("zepy-change"))

    def selection_range(self) -> Range:
        if self.anchor is None:
            return Range(
                self.cursor.line_number,
                self.cursor.column,
                self.cursor.line_number,
                self.cursor.column,
            )
        return Range(
            self.anchor.line_number,
            self.anchor.column,
            self.cursor.line_number,
            self.cursor.column,
        )

    def set_cursor(self, position: Position, extend: bool) -> None:
        if not extend:
            self.anchor = None
        elif self.anchor is None:
            self.anchor = Position(self.cursor.line_number, self.cursor.column)
        self.cursor = position
        self.ensure_visible()

    def open_document(self, path: str, text: str) -> None:
        self.path = path
        self.buffer.set_value(text)
        self.cursor = Position(1, 1)
        self.anchor = None
        self.scroll_y = 0.0
        self.scroll_x = 0.0
        self._undo = []
        self._redo = []
        self.fold_starts = []
        self.fold_ends = []
        self.git_kind = []
        self.git_author = []
        self.git_summary = []
        self.pending_open = ""
        self.disk_mtime = 0.0
        self.wrap = False
        if path.startswith("review:") or has_suffix(path, ".diff"):
            self.wrap = True
        self.vim.mode = MODE_NORMAL
        self.vim.reset_pending()
        self._rebuild_find()
        self.cursor = clamp_normal(self.buffer, self.cursor)
        self.render()
        self._notify()

    def selected_text(self) -> str:
        selected = self.selection_range()
        if selected.is_empty():
            return ""
        start = self.buffer.get_offset_at(selected.start_line_number, selected.start_column)
        end = self.buffer.get_offset_at(selected.end_line_number, selected.end_column)
        return self.buffer.get_value()[start:end]

    def selection_lines(self) -> tuple[int, int]:
        selected = self.selection_range()
        if selected.is_empty():
            return (0, 0)
        start = selected.start_line_number
        end = selected.end_line_number
        if selected.end_column == 1 and end > start:
            end = end - 1
        return (start, end)

    def selected_line_text(self) -> str:
        span = self.selection_lines()
        start = span[0]
        end = span[1]
        if start < 1:
            return ""
        parts: list[str] = []
        line = start
        last = self.buffer.get_line_count()
        while line <= end and line <= last:
            parts.append(self.buffer.get_line_content(line))
            line = line + 1
        return "\n".join(parts)

    def _rebuild_find(self) -> None:
        self.find_matches = find_ranges(self.buffer, self.find_query)
        if len(self.find_matches) == 0:
            self.find_index = -1
            return
        if self.find_index >= len(self.find_matches):
            self.find_index = 0

    def set_find_query(self, query: str) -> None:
        self.find_query = query
        self._rebuild_find()
        if len(self.find_matches) == 0:
            self.render()
            self._notify()
            return
        cursor_off = self.buffer.get_offset_at(self.cursor.line_number, self.cursor.column)
        chosen = 0
        index = 0
        while index < len(self.find_matches):
            match = self.find_matches[index]
            start_off = self.buffer.get_offset_at(match.start_line_number, match.start_column)
            if start_off >= cursor_off:
                chosen = index
                break
            index = index + 1
        self.reveal_match(chosen)

    def clear_find(self) -> None:
        self.find_query = ""
        self.find_matches = []
        self.find_index = -1
        self.render()

    def reveal_match(self, index: int) -> None:
        count = len(self.find_matches)
        if count == 0:
            self.find_index = -1
            self.render()
            self._notify()
            return
        if index < 0:
            index = count - 1
        if index >= count:
            index = 0
        self.find_index = index
        match = self.find_matches[index]
        self.anchor = match.get_start_position()
        self.cursor = match.get_end_position()
        self.ensure_visible()
        self.render()
        self._notify()

    def find_next(self) -> None:
        if self.find_query != "" and len(self.find_matches) == 0:
            self._rebuild_find()
        if len(self.find_matches) == 0:
            return
        self.reveal_match(self.find_index + 1)

    def find_previous(self) -> None:
        if self.find_query != "" and len(self.find_matches) == 0:
            self._rebuild_find()
        if len(self.find_matches) == 0:
            return
        self.reveal_match(self.find_index - 1)

    def replace_current(self, replacement: str) -> None:
        if self.find_query == "":
            return
        if len(self.find_matches) == 0:
            self._rebuild_find()
        if self.find_index < 0 or self.find_index >= len(self.find_matches):
            return
        match = self.find_matches[self.find_index]
        keep = self.find_index
        self._record()
        self.buffer.apply_edits(match, replacement)
        self._rebuild_find()
        if len(self.find_matches) == 0:
            start = match.get_start_position()
            start_off = self.buffer.get_offset_at(start.line_number, start.column)
            self.anchor = None
            self.cursor = self.buffer.get_position_at(start_off + len(replacement))
            self.ensure_visible()
            self.render()
            self._notify()
            return
        if keep >= len(self.find_matches):
            keep = 0
        self.reveal_match(keep)

    def replace_all(self, replacement: str) -> None:
        if self.find_query == "":
            return
        self._rebuild_find()
        if len(self.find_matches) == 0:
            return
        self._record()
        index = len(self.find_matches) - 1
        while index >= 0:
            self.buffer.apply_edits(self.find_matches[index], replacement)
            index = index - 1
        self._rebuild_find()
        self.anchor = None
        self.render()
        self._notify()

    def enter_insert(self) -> None:
        self.vim.mode = MODE_INSERT
        self.vim.reset_pending()
        self._notify()

    def enter_command(self) -> None:
        self.vim.mode = MODE_COMMAND
        self.vim.command = ""
        self.vim.command_kind = ":"
        self.vim.reset_pending()
        self._notify()

    def enter_normal(self) -> None:
        from_insert = self.vim.mode == MODE_INSERT
        if from_insert and self.vim.block_insert != "":
            self._finish_block_insert()
        self.vim.mode = MODE_NORMAL
        self.vim.reset_pending()
        self.anchor = None
        if from_insert and self.cursor.column > 1:
            self.cursor = Position(self.cursor.line_number, self.cursor.column - 1)
        self.cursor = clamp_normal(self.buffer, self.cursor)
        self.render()
        self._notify()

    def enter_visual(self, linewise: bool) -> None:
        if linewise:
            self.vim.mode = MODE_VISUAL_LINE
            line = self.cursor.line_number
            self.anchor = Position(line, 1)
            length = self.buffer.get_line_length(line)
            self.cursor = Position(line, length + 1)
        else:
            self.vim.mode = MODE_VISUAL
            self.anchor = Position(self.cursor.line_number, self.cursor.column)
        self.vim.reset_pending()
        self.render()
        self._notify()

    def enter_visual_block(self) -> None:
        self.vim.mode = MODE_VISUAL_BLOCK
        self.anchor = Position(self.cursor.line_number, self.cursor.column)
        self.vim.reset_pending()
        self.render()
        self._notify()

    def _visual(self) -> bool:
        return (
            self.vim.mode == MODE_VISUAL
            or self.vim.mode == MODE_VISUAL_LINE
            or self.vim.mode == MODE_VISUAL_BLOCK
        )

    def _fold_flags(self) -> list[int]:
        return hidden_flags(self.buffer.get_line_count(), self.fold_starts, self.fold_ends)

    def _refresh_folds(self) -> None:
        starts: list[int] = []
        ends: list[int] = []
        index = 0
        while index < len(self.fold_starts):
            start = self.fold_starts[index]
            end = fold_end(self.buffer, start)
            if end > 0:
                starts.append(start)
                ends.append(end)
            index = index + 1
        self.fold_starts = starts
        self.fold_ends = ends

    def _line_hidden(self, line: int) -> bool:
        flags = self._fold_flags()
        if line < 1 or line > len(flags):
            return False
        return flags[line - 1] == 1

    def _next_visible(self, line: int) -> int:
        last = self.buffer.get_line_count()
        dest = line
        dest = max(dest, 1)
        dest = min(dest, last)
        while dest < last and self._line_hidden(dest):
            dest = dest + 1
        if self._line_hidden(dest):
            dest = dest - 1
            while dest > 1 and self._line_hidden(dest):
                dest = dest - 1
        return dest

    def _prev_visible(self, line: int) -> int:
        dest = line
        dest = max(dest, 1)
        while dest > 1 and self._line_hidden(dest):
            dest = dest - 1
        return dest

    def _reveal_line(self, line: int) -> None:
        kept_s: list[int] = []
        kept_e: list[int] = []
        index = 0
        while index < len(self.fold_starts):
            start = self.fold_starts[index]
            end = self.fold_ends[index]
            if line > start and line <= end:
                pass
            else:
                kept_s.append(start)
                kept_e.append(end)
            index = index + 1
        self.fold_starts = kept_s
        self.fold_ends = kept_e

    def _toggle_fold(self) -> None:
        self._refresh_folds()
        line = self.cursor.line_number
        index = 0
        while index < len(self.fold_starts):
            if self.fold_starts[index] == line:
                kept_s: list[int] = []
                kept_e: list[int] = []
                walk = 0
                while walk < len(self.fold_starts):
                    if walk != index:
                        kept_s.append(self.fold_starts[walk])
                        kept_e.append(self.fold_ends[walk])
                    walk = walk + 1
                self.fold_starts = kept_s
                self.fold_ends = kept_e
                self.render()
                self._notify()
                return
            index = index + 1
        start = innermost_fold_start(self.buffer, line)
        if start < 1:
            return
        end = fold_end(self.buffer, start)
        if end < 1:
            return
        self.fold_starts.append(start)
        self.fold_ends.append(end)
        self.cursor = Position(start, first_nonblank_column(self.buffer, start))
        self.render()
        self._notify()

    def _close_all_folds(self) -> None:
        starts: list[int] = []
        ends: list[int] = []
        last = self.buffer.get_line_count()
        line = 1
        while line <= last:
            end = fold_end(self.buffer, line)
            if end > 0:
                starts.append(line)
                ends.append(end)
                line = end
            line = line + 1
        self.fold_starts = starts
        self.fold_ends = ends
        if self._line_hidden(self.cursor.line_number):
            self.cursor = Position(
                self._prev_visible(self.cursor.line_number),
                self.cursor.column,
            )
        self.render()
        self._notify()

    def _open_all_folds(self) -> None:
        self.fold_starts = []
        self.fold_ends = []
        self.render()
        self._notify()

    def _leading_indent(self, line: int) -> str:
        text = self.buffer.get_line_content(line)
        index = 0
        while index < len(text) and (text[index] == " " or text[index] == "\t"):
            index = index + 1
        return text[0:index]

    def _text_object_span(self, key: str, around: bool) -> Range:
        if key == "w":
            return word_span(self.buffer, self.cursor, around)
        if key == '"' or key == "'" or key == "`":
            return quote_span(self.buffer, self.cursor, key, around)
        if key == "(" or key == ")" or key == "b":
            return bracket_span(self.buffer, self.cursor, "(", ")", around)
        if key == "[" or key == "]":
            return bracket_span(self.buffer, self.cursor, "[", "]", around)
        if key == "{" or key == "}" or key == "B":
            return bracket_span(self.buffer, self.cursor, "{", "}", around)
        return Range(0, 1, 0, 1)

    def _commit_yank(self, text: str, linewise: bool, block: bool) -> None:
        self.vim.yank = text
        self.vim.yank_linewise = linewise
        self.vim.yank_block = block
        idx = letter_index(self.vim.register_name)
        self.vim.register_name = ""
        if idx >= 0:
            self.vim.reg_text[idx] = text
            flag = 0
            if linewise:
                flag = 1
            self.vim.reg_linewise[idx] = flag

    def _load_register(self) -> None:
        idx = letter_index(self.vim.register_name)
        self.vim.register_name = ""
        if idx < 0:
            return
        self.vim.yank = self.vim.reg_text[idx]
        self.vim.yank_linewise = self.vim.reg_linewise[idx] == 1
        self.vim.yank_block = False

    def _record_jump(self) -> None:
        line = self.cursor.line_number
        col = self.cursor.column
        n = len(self.vim.jump_line)
        idx = self.vim.jump_index
        if idx >= 0 and idx < n:
            kept_l: list[int] = []
            kept_c: list[int] = []
            walk = 0
            while walk < idx:
                kept_l.append(self.vim.jump_line[walk])
                kept_c.append(self.vim.jump_col[walk])
                walk = walk + 1
            self.vim.jump_line = kept_l
            self.vim.jump_col = kept_c
            n = len(self.vim.jump_line)
        if n > 0 and self.vim.jump_line[n - 1] == line and self.vim.jump_col[n - 1] == col:
            self.vim.jump_index = n
            return
        self.vim.jump_line.append(line)
        self.vim.jump_col.append(col)
        if len(self.vim.jump_line) > 80:
            kept_l = []
            kept_c = []
            walk = len(self.vim.jump_line) - 80
            while walk < len(self.vim.jump_line):
                kept_l.append(self.vim.jump_line[walk])
                kept_c.append(self.vim.jump_col[walk])
                walk = walk + 1
            self.vim.jump_line = kept_l
            self.vim.jump_col = kept_c
        self.vim.jump_index = len(self.vim.jump_line)

    def _jump_back(self) -> None:
        n = len(self.vim.jump_line)
        if n == 0:
            return
        if self.vim.jump_index >= n:
            self.vim.jump_line.append(self.cursor.line_number)
            self.vim.jump_col.append(self.cursor.column)
            n = n + 1
            self.vim.jump_index = n - 1
        if self.vim.jump_index <= 0:
            self.vim.jump_index = 0
            dest_l = self.vim.jump_line[0]
            dest_c = self.vim.jump_col[0]
        else:
            self.vim.jump_index = self.vim.jump_index - 1
            dest_l = self.vim.jump_line[self.vim.jump_index]
            dest_c = self.vim.jump_col[self.vim.jump_index]
        self._reveal_line(dest_l)
        self.set_cursor(Position(dest_l, dest_c), False)
        self.cursor = clamp_normal(self.buffer, self.cursor)
        self.render()
        self._notify()

    def _jump_forward(self) -> None:
        n = len(self.vim.jump_line)
        if self.vim.jump_index + 1 >= n:
            return
        self.vim.jump_index = self.vim.jump_index + 1
        dest_l = self.vim.jump_line[self.vim.jump_index]
        dest_c = self.vim.jump_col[self.vim.jump_index]
        self._reveal_line(dest_l)
        self.set_cursor(Position(dest_l, dest_c), False)
        self.cursor = clamp_normal(self.buffer, self.cursor)
        self.render()
        self._notify()

    def set_git(self, kinds: list[int], authors: list[str], summaries: list[str]) -> None:
        self.git_kind = kinds
        self.git_author = authors
        self.git_summary = summaries

    def blame_at_cursor(self) -> str:
        line = self.cursor.line_number
        if line < 1 or line > len(self.git_author):
            return ""
        author = self.git_author[line - 1]
        summary = ""
        if line <= len(self.git_summary):
            summary = self.git_summary[line - 1]
        if author == "":
            return ""
        if summary == "":
            return author
        return author + "  " + summary

    def _run_ex(self, text: str) -> None:
        if ex_is_write(text):
            self.canvas.dispatchEvent(Event("zepy-save"))
            return
        if ex_is_nohl(text):
            self.clear_find()
            self._notify()
            return
        if ex_is_next(text):
            self.canvas.dispatchEvent(Event("zepy-tab-next"))
            return
        if ex_is_prev(text):
            self.canvas.dispatchEvent(Event("zepy-tab-prev"))
            return
        if ex_is_edit(text):
            path = rest_after_word(text)
            if path != "":
                self.pending_open = path
                self.canvas.dispatchEvent(Event("zepy-open-path"))
            return
        if ex_is_line_number(text):
            dest = ex_line_number(text)
            if dest >= 1:
                self._record_jump()
                self._reveal_line(dest)
                self._vim_go_line(dest)
                self.render()
                self._notify()
            return
        word = first_word(text)
        if word == "":
            return

    async def _copy_clipboard(self) -> None:
        text = self.selected_text()
        if text == "":
            text = self.buffer.get_line_content(self.cursor.line_number)
        self.clip = text
        board = get_clipboard()
        if board is None:
            return
        await board.writeText(text)

    async def _cut_clipboard(self) -> None:
        await self._copy_clipboard()
        if self.delete_selection():
            self.ensure_visible()
            self.render()
            self._notify()

    async def _paste_clipboard(self) -> None:
        text = self.clip
        board = get_clipboard()
        if board is not None:
            text = await board.readText()
        if text == "":
            return
        self.clip = text
        self.insert(text)
        self.render()
        self._notify()

    def _block_top(self) -> int:
        if self.anchor is None:
            return self.cursor.line_number
        if self.anchor.line_number < self.cursor.line_number:
            return self.anchor.line_number
        return self.cursor.line_number

    def _block_bot(self) -> int:
        if self.anchor is None:
            return self.cursor.line_number
        if self.anchor.line_number > self.cursor.line_number:
            return self.anchor.line_number
        return self.cursor.line_number

    def _block_left(self) -> int:
        if self.anchor is None:
            return self.cursor.column
        if self.anchor.column < self.cursor.column:
            return self.anchor.column
        return self.cursor.column

    def _block_right(self) -> int:
        if self.anchor is None:
            return self.cursor.column
        if self.anchor.column > self.cursor.column:
            return self.anchor.column
        return self.cursor.column

    def _block_slice(self, line: int, left: int, right: int) -> str:
        content = self.buffer.get_line_content(line)
        start_i = left - 1
        end_i = right
        start_i = max(start_i, 0)
        if start_i >= len(content):
            return ""
        end_i = min(end_i, len(content))
        return content[start_i:end_i]

    def _block_yank(self) -> None:
        top = self._block_top()
        bot = self._block_bot()
        left = self._block_left()
        right = self._block_right()
        text = ""
        line = top
        while line <= bot:
            if line > top:
                text = text + "\n"
            text = text + self._block_slice(line, left, right)
            line = line + 1
        self._commit_yank(text, False, True)

    def _block_delete(self) -> None:
        top = self._block_top()
        bot = self._block_bot()
        left = self._block_left()
        right = self._block_right()
        self._record()
        line = bot
        while line >= top:
            length = self.buffer.get_line_length(line)
            if length >= left:
                end_col = right + 1
                end_col = min(end_col, length + 1)
                self.buffer.apply_edits(Range(line, left, line, end_col), "")
            line = line - 1
        self.vim.mode = MODE_NORMAL
        self.anchor = None
        self.cursor = clamp_normal(self.buffer, Position(top, left))
        self.ensure_visible()
        self.render()
        self._notify()

    def _block_replace(self, ch: str) -> None:
        top = self._block_top()
        bot = self._block_bot()
        left = self._block_left()
        right = self._block_right()
        self._record()
        line = top
        while line <= bot:
            length = self.buffer.get_line_length(line)
            col = right
            while col >= left:
                if col <= length:
                    self.buffer.apply_edits(Range(line, col, line, col + 1), ch)
                col = col - 1
            line = line + 1
        self.vim.mode = MODE_NORMAL
        self.anchor = None
        self.cursor = clamp_normal(self.buffer, Position(top, left))
        self.render()
        self._notify()

    def _split_yank_lines(self) -> list[str]:
        lines: list[str] = []
        current = ""
        index = 0
        yank = self.vim.yank
        while index < len(yank):
            if yank[index] == "\n":
                lines.append(current)
                current = ""
            else:
                current = current + yank[index]
            index = index + 1
        lines.append(current)
        return lines

    def _block_paste(self, before: bool) -> None:
        parts = self._split_yank_lines()
        if len(parts) == 0:
            return
        self._record()
        start_line = self.cursor.line_number
        col = self.cursor.column
        if not before:
            col = col + 1
        index = 0
        while index < len(parts):
            line = start_line + index
            while self.buffer.get_line_count() < line:
                self.buffer.insert(self.buffer.get_length(), "\n")
            length = self.buffer.get_line_length(line)
            insert_col = col
            insert_col = min(insert_col, length + 1)
            offset = self.buffer.get_offset_at(line, insert_col)
            self.buffer.insert(offset, parts[index])
            index = index + 1
        self.anchor = None
        self.ensure_visible()
        self.render()
        self._notify()

    def _begin_block_insert(self, append: bool) -> None:
        top = self._block_top()
        bot = self._block_bot()
        left = self._block_left()
        right = self._block_right()
        col = right + 1
        if not append:
            col = left
        length = self.buffer.get_line_length(top)
        col = min(col, length + 1)
        self.vim.block_insert = "A"
        if not append:
            self.vim.block_insert = "I"
        self.vim.block_top = top
        self.vim.block_bot = bot
        self.vim.block_col = col
        self.vim.block_old_len = length
        self.anchor = None
        self.cursor = Position(top, col)
        self.enter_insert()

    def _finish_block_insert(self) -> None:
        if self.vim.block_insert == "":
            return
        top = self.vim.block_top
        bot = self.vim.block_bot
        col = self.vim.block_col
        new_len = self.buffer.get_line_length(top)
        inserted_len = new_len - self.vim.block_old_len
        self.vim.block_insert = ""
        if inserted_len <= 0:
            return
        line_text = self.buffer.get_line_content(top)
        start_i = col - 1
        start_i = max(start_i, 0)
        inserted = line_text[start_i : start_i + inserted_len]
        line = top + 1
        while line <= bot:
            length = self.buffer.get_line_length(line)
            insert_col = col
            insert_col = min(insert_col, length + 1)
            offset = self.buffer.get_offset_at(line, insert_col)
            self.buffer.insert(offset, inserted)
            line = line + 1

    def _vim_adjust_visual_line(self) -> None:
        if self.vim.mode != MODE_VISUAL_LINE or self.anchor is None:
            return
        start_line = self.anchor.line_number
        end_line = self.cursor.line_number
        if end_line < start_line:
            top = end_line
            bot = start_line
        else:
            top = start_line
            bot = end_line
        self.anchor = Position(top, 1)
        self.cursor = Position(bot, self.buffer.get_line_length(bot) + 1)

    def _text_between(self, start: Position, end: Position) -> str:
        a = self.buffer.get_offset_at(start.line_number, start.column)
        b = self.buffer.get_offset_at(end.line_number, end.column)
        if b < a:
            swap = a
            a = b
            b = swap
        return self.buffer.get_value()[a:b]

    def _ordered_range(self, start: Position, end: Position) -> Range:
        return Range(
            start.line_number,
            start.column,
            end.line_number,
            end.column,
        )

    def _linewise_range(self, start: Position, end: Position) -> Range:
        top = start.line_number
        bot = end.line_number
        if bot < top:
            swap = top
            top = bot
            bot = swap
        last = self.buffer.get_line_count()
        if bot < last:
            return Range(top, 1, bot + 1, 1)
        if top > 1:
            prev_len = self.buffer.get_line_length(top - 1)
            return Range(top - 1, prev_len + 1, bot, self.buffer.get_line_length(bot) + 1)
        return Range(top, 1, bot, self.buffer.get_line_length(bot) + 1)

    def _linewise_text(self, start: Position, end: Position) -> str:
        top = start.line_number
        bot = end.line_number
        if bot < top:
            swap = top
            top = bot
            bot = swap
        text = ""
        line = top
        while line <= bot:
            if line > top:
                text = text + "\n"
            text = text + self.buffer.get_line_content(line)
            line = line + 1
        return text

    def _lstrip_ws(self, text: str) -> str:
        index = 0
        while index < len(text) and (text[index] == " " or text[index] == "\t"):
            index = index + 1
        return text[index:]

    def _join_once(self) -> None:
        line = self.cursor.line_number
        if line >= self.buffer.get_line_count():
            return
        left = self.buffer.get_line_content(line)
        right = self.buffer.get_line_content(line + 1)
        stripped = self._lstrip_ws(right)
        sep = " "
        if len(left) == 0 or left[len(left) - 1] == " " or len(stripped) == 0:
            sep = ""
        start_col = len(left) + 1
        selected = Range(line, start_col, line + 1, len(right) + 1)
        self.buffer.apply_edits(selected, sep + stripped)
        self.cursor = clamp_normal(self.buffer, Position(line, start_col))
        self.anchor = None

    def _vim_join(self, count: int) -> None:
        joins = 1
        if count >= 2:
            joins = count - 1
        self._record()
        step = 0
        while step < joins:
            if self.cursor.line_number >= self.buffer.get_line_count():
                break
            self._join_once()
            step = step + 1
        self.vim.mode = MODE_NORMAL
        self.anchor = None
        self.ensure_visible()
        self.render()
        self._notify()

    def _remember_edit(self, kind: str, count: int, ch: str) -> None:
        if self.vim.replaying:
            return
        self.vim.last_edit = kind
        self.vim.last_edit_count = count
        self.vim.last_edit_char = ch
        self.vim.last_edit_op = self.vim.operator
        self.vim.last_edit_motion = ""

    def _indent_lines(self, top: int, bot: int, add: bool) -> None:
        if bot < top:
            swap = top
            top = bot
            bot = swap
        self._record()
        line = top
        while line <= bot:
            text = self.buffer.get_line_content(line)
            if add:
                next_text = "    " + text
            else:
                next_text = text
                if len(text) > 0 and text[0] == "\t":
                    next_text = text[1:]
                else:
                    stripped = 0
                    while stripped < len(text) and stripped < 4 and text[stripped] == " ":
                        stripped = stripped + 1
                    next_text = text[stripped:]
            selected = Range(line, 1, line, len(text) + 1)
            self.buffer.apply_edits(selected, next_text)
            line = line + 1
        self.cursor = clamp_normal(
            self.buffer, Position(top, first_nonblank_column(self.buffer, top))
        )
        self.anchor = None
        self.vim.mode = MODE_NORMAL
        self.ensure_visible()
        self.render()
        self._notify()

    def _replace_char(self, ch: str, count: int) -> None:
        if ch == "" or len(ch) != 1:
            return
        self._record()
        step = 0
        while step < count:
            length = self.buffer.get_line_length(self.cursor.line_number)
            if self.cursor.column > length or length < 1:
                break
            selected = Range(
                self.cursor.line_number,
                self.cursor.column,
                self.cursor.line_number,
                self.cursor.column + 1,
            )
            self.buffer.apply_edits(selected, ch)
            if self.cursor.column < length:
                self.cursor = Position(self.cursor.line_number, self.cursor.column + 1)
            step = step + 1
        self.cursor = clamp_normal(self.buffer, self.cursor)
        self.ensure_visible()
        self.render()
        self._notify()

    def _toggle_case(self, count: int) -> None:
        self._record()
        step = 0
        while step < count:
            length = self.buffer.get_line_length(self.cursor.line_number)
            if self.cursor.column > length or length < 1:
                break
            line = self.buffer.get_line_content(self.cursor.line_number)
            ch = line[self.cursor.column - 1]
            selected = Range(
                self.cursor.line_number,
                self.cursor.column,
                self.cursor.line_number,
                self.cursor.column + 1,
            )
            self.buffer.apply_edits(selected, toggle_case_char(ch))
            if self.cursor.column < length:
                self.cursor = Position(self.cursor.line_number, self.cursor.column + 1)
            step = step + 1
        self.cursor = clamp_normal(self.buffer, self.cursor)
        self.ensure_visible()
        self.render()
        self._notify()

    def _change_line(self, count: int) -> None:
        start = Position(self.cursor.line_number, 1)
        bot = self.cursor.line_number + count - 1
        last = self.buffer.get_line_count()
        bot = min(bot, last)
        end = Position(bot, self.buffer.get_line_length(bot) + 1)
        self.vim.operator = "c"
        self._apply_operator(start, end, False, False)

    def _paragraph_move(self, forward: bool, count: int, extend: bool) -> None:
        step = 0
        while step < count:
            line = self.cursor.line_number
            last = self.buffer.get_line_count()
            if forward:
                line = line + 1
                while line <= last and self.buffer.get_line_length(line) > 0:
                    line = line + 1
                while line <= last and self.buffer.get_line_length(line) == 0:
                    line = line + 1
            else:
                line = line - 1
                while line >= 1 and self.buffer.get_line_length(line) > 0:
                    line = line - 1
                while line >= 1 and self.buffer.get_line_length(line) == 0:
                    line = line - 1
            line = max(line, 1)
            line = min(line, last)
            self.set_cursor(Position(line, 1), extend)
            step = step + 1

    def _scroll_by_lines(self, lines: int) -> None:
        line_height = self.glyphs.line_height()
        self.scroll_y = self.scroll_y + float(lines) * line_height
        self.scroll_y = max(self.scroll_y, 0.0)
        self.scroll_y = min(self.scroll_y, self.max_scroll())
        flags = self._fold_flags()
        target_view = int(self.scroll_y / line_height)
        target_view = max(target_view, 0)
        target = line_at_view_index(flags, target_view)
        last = self.buffer.get_line_count()
        target = max(target, 1)
        target = min(target, last)
        self.cursor = clamp_normal(
            self.buffer,
            Position(target, first_nonblank_column(self.buffer, target)),
        )
        self.ensure_visible()
        self.render()
        self._notify()

    def _center_cursor(self) -> None:
        line_height = self.glyphs.line_height()
        view = float(self.canvas.height)
        flags = self._fold_flags()
        y = float(visible_count_before(self.cursor.line_number, flags)) * line_height
        self.scroll_y = y - view / 2.0
        self.scroll_y = max(self.scroll_y, 0.0)
        self.scroll_y = min(self.scroll_y, self.max_scroll())
        self.render()

    def _word_under_cursor(self) -> str:
        span = word_span(self.buffer, self.cursor, False)
        return self._text_between(span.get_start_position(), span.get_end_position())

    def enter_search(self) -> None:
        self.vim.mode = MODE_COMMAND
        self.vim.command = ""
        self.vim.command_kind = "/"
        self.vim.reset_pending()
        self._notify()

    def replay_last_edit(self) -> None:
        kind = self.vim.last_edit
        if kind == "" or self.vim.replaying:
            return
        self.vim.replaying = True
        count = self.vim.last_edit_count
        ch = self.vim.last_edit_char
        if kind == "x":
            step = 0
            while step < count:
                self._vim_delete_char()
                step = step + 1
        elif kind == "dd":
            self._vim_delete_line(count)
        elif kind == "p":
            self._vim_paste(False)
        elif kind == "P":
            self._vim_paste(True)
        elif kind == "J":
            self._vim_join(count)
        elif kind == "r":
            self._replace_char(ch, count)
        elif kind == "tilde":
            self._toggle_case(count)
        elif kind == "indent":
            bot = self.cursor.line_number + count - 1
            self._indent_lines(self.cursor.line_number, bot, True)
        elif kind == "unindent":
            bot = self.cursor.line_number + count - 1
            self._indent_lines(self.cursor.line_number, bot, False)
        elif kind == "s":
            step = 0
            while step < count:
                self._vim_delete_char()
                step = step + 1
            self.enter_insert()
        self.vim.replaying = False

    def _apply_operator(
        self, start: Position, end: Position, inclusive: bool, linewise: bool
    ) -> None:
        op = self.vim.operator
        self.vim.operator = ""
        if linewise:
            selected = self._linewise_range(start, end)
            text = self._linewise_text(start, end)
        else:
            if inclusive:
                off = self.buffer.get_offset_at(end.line_number, end.column) + 1
                limit = self.buffer.get_length()
                off = min(off, limit)
                end = self.buffer.get_position_at(off)
            selected = self._ordered_range(start, end)
            text = self._text_between(selected.get_start_position(), selected.get_end_position())
        self._commit_yank(text, linewise, False)
        if op == "y":
            self.vim.mode = MODE_NORMAL
            self.cursor = clamp_normal(self.buffer, start)
            self.anchor = None
            self.render()
            self._notify()
            return
        self._record()
        self.buffer.apply_edits(selected, "")
        self.cursor = clamp_normal(self.buffer, selected.get_start_position())
        self.anchor = None
        if op == "c":
            self.vim.mode = MODE_INSERT
        else:
            self.vim.mode = MODE_NORMAL
        self.ensure_visible()
        self.render()
        self._notify()

    def _vim_delete_char(self) -> None:
        length = self.buffer.get_line_length(self.cursor.line_number)
        if length < 1:
            return
        start = Position(self.cursor.line_number, self.cursor.column)
        end_off = self.buffer.get_offset_at(start.line_number, start.column) + 1
        end = self.buffer.get_position_at(end_off)
        self.vim.operator = "d"
        self._apply_operator(start, end, False, False)

    def _vim_delete_line(self, count: int) -> None:
        start = Position(self.cursor.line_number, 1)
        bot = self.cursor.line_number + count - 1
        last = self.buffer.get_line_count()
        bot = min(bot, last)
        end = Position(bot, 1)
        self.vim.operator = "d"
        self._apply_operator(start, end, False, True)

    def _vim_yank_line(self, count: int) -> None:
        start = Position(self.cursor.line_number, 1)
        bot = self.cursor.line_number + count - 1
        last = self.buffer.get_line_count()
        bot = min(bot, last)
        end = Position(bot, 1)
        self.vim.operator = "y"
        self._apply_operator(start, end, False, True)

    def _vim_paste(self, before: bool) -> None:
        self._load_register()
        if self.vim.yank == "":
            return
        if self.vim.yank_block:
            self._block_paste(before)
            return
        self._record()
        yank = self.vim.yank
        if self.vim.yank_linewise:
            if yank.endswith("\n"):
                yank = yank[0 : len(yank) - 1]
            line = self.cursor.line_number
            if before:
                offset = self.buffer.get_offset_at(line, 1)
                self.buffer.insert(offset, yank + "\n")
                self.cursor = Position(line, first_nonblank_column(self.buffer, line))
            else:
                col = self.buffer.get_line_length(line) + 1
                offset = self.buffer.get_offset_at(line, col)
                self.buffer.insert(offset, "\n" + yank)
                dest = line + 1
                self.cursor = Position(dest, first_nonblank_column(self.buffer, dest))
        else:
            offset = self.buffer.get_offset_at(self.cursor.line_number, self.cursor.column)
            if not before:
                length = self.buffer.get_line_length(self.cursor.line_number)
                if self.cursor.column <= length:
                    offset = offset + 1
            self.buffer.insert(offset, yank)
            self.cursor = clamp_normal(self.buffer, self.buffer.get_position_at(offset + len(yank)))
        self.anchor = None
        self.ensure_visible()
        self.render()
        self._notify()

    def _vim_open_line(self, above: bool) -> None:
        self._record()
        indent = self._leading_indent(self.cursor.line_number)
        if above:
            offset = self.buffer.get_offset_at(self.cursor.line_number, 1)
            self.buffer.insert(offset, indent + "\n")
            self.cursor = Position(self.cursor.line_number, len(indent) + 1)
        else:
            col = self.buffer.get_line_length(self.cursor.line_number) + 1
            offset = self.buffer.get_offset_at(self.cursor.line_number, col)
            self.buffer.insert(offset, "\n" + indent)
            self.cursor = Position(self.cursor.line_number + 1, len(indent) + 1)
        self.anchor = None
        self.enter_insert()
        self.ensure_visible()
        self.render()

    def _vim_move_h(self, extend: bool) -> None:
        if self.cursor.column > 1:
            self.set_cursor(Position(self.cursor.line_number, self.cursor.column - 1), extend)
        elif extend:
            self.set_cursor(self.cursor, True)

    def _vim_move_l(self, extend: bool) -> None:
        length = self.buffer.get_line_length(self.cursor.line_number)
        limit = length
        limit = max(limit, 1)
        if self.cursor.column < limit:
            self.set_cursor(Position(self.cursor.line_number, self.cursor.column + 1), extend)
        elif extend:
            self.set_cursor(self.cursor, True)

    def _vim_go_line(self, line: int) -> None:
        last = self.buffer.get_line_count()
        line = max(line, 1)
        line = min(line, last)
        self._reveal_line(line)
        col = first_nonblank_column(self.buffer, line)
        self.set_cursor(Position(line, col), False)
        self.cursor = clamp_normal(self.buffer, self.cursor)

    def _vim_apply_find(self, kind: str, ch: str, count: int, extend: bool) -> None:
        start = Position(self.cursor.line_number, self.cursor.column)
        dest = find_char(self.buffer, start, kind, ch, count)
        if dest.line_number < 1:
            return
        self.set_cursor(dest, extend)
        if self.vim.mode == MODE_VISUAL_LINE:
            self._vim_adjust_visual_line()
        if self.vim.operator != "":
            self._apply_operator(start, dest, True, False)
            return
        self.cursor = clamp_normal(self.buffer, self.cursor)
        self.render()
        self._notify()

    def handle_vim_key(self, key: str) -> bool:
        extend = self._visual()
        if self.vim.replace_pending:
            self.vim.replace_pending = False
            if len(key) == 1:
                if self.vim.mode == MODE_VISUAL_BLOCK:
                    self._block_replace(key)
                else:
                    count = self.vim.take_count()
                    self._replace_char(key, count)
                    self._remember_edit("r", count, key)
            return True
        if self.vim.mode == MODE_VISUAL_BLOCK:
            if key == "d" or key == "x":
                self._block_yank()
                self._block_delete()
                return True
            if key == "y":
                self._block_yank()
                self.enter_normal()
                return True
            if key == "c":
                top = self._block_top()
                bot = self._block_bot()
                left = self._block_left()
                self._block_yank()
                self._block_delete()
                self.vim.block_insert = "I"
                self.vim.block_top = top
                self.vim.block_bot = bot
                self.vim.block_col = left
                self.vim.block_old_len = self.buffer.get_line_length(top)
                self.cursor = Position(top, left)
                self.enter_insert()
                return True
            if key == "I":
                self._begin_block_insert(False)
                return True
            if key == "A":
                self._begin_block_insert(True)
                return True
            if key == "r":
                self.vim.replace_pending = True
                return True
            if key == "o":
                if self.anchor is not None:
                    swap = Position(self.cursor.line_number, self.cursor.column)
                    self.cursor = Position(self.anchor.line_number, self.anchor.column)
                    self.anchor = swap
                    self.render()
                    self._notify()
                return True
            if key == "v":
                self.enter_visual(False)
                return True
            if key == "V":
                self.enter_visual(True)
                return True
        if self.vim.mode == MODE_VISUAL or self.vim.mode == MODE_VISUAL_LINE:
            if key == "d" or key == "x":
                start = self.selection_range().get_start_position()
                end = self.selection_range().get_end_position()
                self.vim.operator = "d"
                self._apply_operator(start, end, False, self.vim.mode == MODE_VISUAL_LINE)
                return True
            if key == "y":
                start = self.selection_range().get_start_position()
                end = self.selection_range().get_end_position()
                self.vim.operator = "y"
                self._apply_operator(start, end, False, self.vim.mode == MODE_VISUAL_LINE)
                return True
            if key == "c":
                start = self.selection_range().get_start_position()
                end = self.selection_range().get_end_position()
                self.vim.operator = "c"
                self._apply_operator(start, end, False, self.vim.mode == MODE_VISUAL_LINE)
                return True
            if key == "J":
                sel = self.selection_range()
                self.cursor = Position(sel.start_line_number, 1)
                lines = sel.end_line_number - sel.start_line_number + 1
                self._vim_join(lines)
                return True
            if key == "v" or key == "V":
                self.enter_normal()
                return True
            if key == ">":
                sel = self.selection_range()
                self._indent_lines(sel.start_line_number, sel.end_line_number, True)
                self._remember_edit("indent", 1, "")
                return True
            if key == "<":
                sel = self.selection_range()
                self._indent_lines(sel.start_line_number, sel.end_line_number, False)
                self._remember_edit("unindent", 1, "")
                return True
            if key == "~":
                sel = self.selection_range()
                self._record()
                text = self._text_between(sel.get_start_position(), sel.get_end_position())
                flipped = ""
                index = 0
                while index < len(text):
                    flipped = flipped + toggle_case_char(text[index])
                    index = index + 1
                self.buffer.apply_edits(sel, flipped)
                self.vim.mode = MODE_NORMAL
                self.cursor = clamp_normal(self.buffer, sel.get_start_position())
                self.anchor = None
                self.render()
                self._notify()
                return True

        if self.vim.find_pending != "":
            kind = self.vim.find_pending
            self.vim.find_pending = ""
            if len(key) != 1:
                return True
            count = self.vim.take_count()
            self.vim.last_find_kind = kind
            self.vim.last_find_char = key
            self._vim_apply_find(kind, key, count, extend)
            return True

        if self.vim.register_pending:
            self.vim.register_pending = False
            idx = letter_index(key)
            if idx >= 0:
                self.vim.register_name = key
            return True
        if self.vim.mark_pending:
            self.vim.mark_pending = False
            idx = letter_index(key)
            if idx >= 0:
                self.vim.mark_line[idx] = self.cursor.line_number
                self.vim.mark_col[idx] = self.cursor.column
            return True
        if self.vim.jump_pending != "":
            kind = self.vim.jump_pending
            self.vim.jump_pending = ""
            idx = letter_index(key)
            if idx >= 0 and self.vim.mark_line[idx] >= 1:
                self._record_jump()
                line = self.vim.mark_line[idx]
                col = self.vim.mark_col[idx]
                if kind == "'":
                    col = first_nonblank_column(self.buffer, line)
                self._reveal_line(line)
                self.set_cursor(Position(line, col), False)
                self.cursor = clamp_normal(self.buffer, self.cursor)
                self.render()
                self._notify()
            return True

        digit = digit_value(key)
        if digit >= 0:
            if key == "0" and self.vim.count == 0:
                start = Position(self.cursor.line_number, self.cursor.column)
                self.set_cursor(Position(self.cursor.line_number, 1), extend)
                if self.vim.operator != "":
                    self._apply_operator(start, self.cursor, False, False)
                else:
                    self.render()
                    self._notify()
                return True
            self.vim.count = self.vim.count * 10 + digit
            self.vim.count = min(self.vim.count, 9999)
            return True

        if self.vim.g_pending:
            self.vim.g_pending = False
            if key == "g":
                count = self.vim.take_count()
                self._record_jump()
                self._vim_go_line(count)
                self.render()
                self._notify()
                return True
            if key == "H":
                self.canvas.dispatchEvent(Event("zepy-open-head"))
                return True
            if key == "t":
                self.canvas.dispatchEvent(Event("zepy-tab-next"))
                return True
            if key == "T":
                self.canvas.dispatchEvent(Event("zepy-tab-prev"))
                return True
            if self.path.startswith("review:"):
                if key == "]":
                    self.canvas.dispatchEvent(Event("zepy-review-next"))
                    return True
                if key == "[":
                    self.canvas.dispatchEvent(Event("zepy-review-prev"))
                    return True
            if key == "b":
                self.canvas.dispatchEvent(Event("zepy-review-back"))
                return True
            self.vim.reset_pending()
            return True

        if key == "g":
            self.vim.g_pending = True
            return True

        if key == '"' and self.vim.operator == "" and self.vim.text_object == "":
            self.vim.register_pending = True
            return True
        if key == "m" and self.vim.operator == "":
            self.vim.mark_pending = True
            return True

        if key == "d" or key == "c" or key == "y":
            if self.vim.operator == key:
                count = self.vim.take_count()
                if key == "y":
                    self._vim_yank_line(count)
                elif key == "c":
                    self.vim.operator = "c"
                    start = Position(self.cursor.line_number, 1)
                    bot = self.cursor.line_number + count - 1
                    last = self.buffer.get_line_count()
                    bot = min(bot, last)
                    self._apply_operator(start, Position(bot, 1), False, True)
                else:
                    self._vim_delete_line(count)
                    self._remember_edit("dd", count, "")
                return True
            if self.vim.operator == "":
                self.vim.operator = key
                return True

        if key == "f" or key == "F" or key == "t" or key == "T":
            self.vim.find_pending = key
            return True

        if key == ">" or key == "<":
            if self.vim.indent_pending == key:
                count = self.vim.take_count()
                bot = self.cursor.line_number + count - 1
                add = key == ">"
                self._indent_lines(self.cursor.line_number, bot, add)
                if add:
                    self._remember_edit("indent", count, "")
                else:
                    self._remember_edit("unindent", count, "")
                return True
            self.vim.indent_pending = key
            return True

        if self.vim.indent_pending != "":
            add = self.vim.indent_pending == ">"
            self.vim.indent_pending = ""
            count = self.vim.take_count()
            start_line = self.cursor.line_number
            if key == "j":
                self._indent_lines(start_line, start_line + count, add)
                return True
            if key == "k":
                top = start_line - count
                top = max(top, 1)
                self._indent_lines(top, start_line, add)
                return True
            if key == "G":
                self._indent_lines(start_line, self.buffer.get_line_count(), add)
                return True
            return True

        if self.vim.text_object != "":
            around = self.vim.text_object == "a"
            self.vim.text_object = ""
            span = self._text_object_span(key, around)
            if span.start_line_number >= 1:
                self._apply_operator(
                    span.get_start_position(),
                    span.get_end_position(),
                    False,
                    False,
                )
            return True

        if self.vim.operator != "" and (key == "i" or key == "a"):
            self.vim.text_object = key
            return True

        if self.vim.z_pending:
            self.vim.z_pending = False
            if key == "z":
                self._center_cursor()
            elif key == "a":
                self._toggle_fold()
            elif key == "M":
                self._close_all_folds()
            elif key == "R":
                self._open_all_folds()
            elif key == "w":
                self.wrap = not self.wrap
                if self.wrap:
                    self.scroll_x = 0.0
                self.ensure_visible()
                self.render()
                self._notify()
            return True

        if self.vim.operator == "" and (key == "`" or key == "'"):
            self.vim.jump_pending = key
            return True

        start = Position(self.cursor.line_number, self.cursor.column)
        if key == "G":
            self._record_jump()
            if self.vim.count > 0:
                self._vim_go_line(self.vim.take_count())
            else:
                self.vim.take_count()
                self._vim_go_line(self.buffer.get_line_count())
            if self.vim.operator != "":
                self._apply_operator(start, self.cursor, False, True)
            else:
                self.render()
                self._notify()
            return True

        count = self.vim.take_count()
        linewise = False
        inclusive = False
        moved = False

        if key == "h":
            step = 0
            while step < count:
                self._vim_move_h(extend)
                step = step + 1
            moved = True
        elif key == "l":
            if self.vim.mode == MODE_VISUAL_BLOCK:
                col = self.cursor.column + count
                col = min(col, 200)
                self.set_cursor(Position(self.cursor.line_number, col), True)
            else:
                step = 0
                while step < count:
                    self._vim_move_l(extend)
                    step = step + 1
            moved = True
        elif key == "j":
            if self.vim.mode == MODE_VISUAL_BLOCK:
                last = self.buffer.get_line_count()
                line = self.cursor.line_number + count
                line = min(line, last)
                self.set_cursor(Position(line, self.cursor.column), True)
            else:
                step = 0
                while step < count:
                    self.move_down(extend)
                    step = step + 1
                linewise = True
            moved = True
        elif key == "k":
            if self.vim.mode == MODE_VISUAL_BLOCK:
                line = self.cursor.line_number - count
                line = max(line, 1)
                self.set_cursor(Position(line, self.cursor.column), True)
            else:
                step = 0
                while step < count:
                    self.move_up(extend)
                    step = step + 1
                linewise = True
            moved = True
        elif key == "w":
            step = 0
            while step < count:
                self.set_cursor(word_forward(self.buffer, self.cursor), extend)
                step = step + 1
            moved = True
        elif key == "b":
            step = 0
            while step < count:
                self.set_cursor(word_back(self.buffer, self.cursor), extend)
                step = step + 1
            moved = True
        elif key == "e":
            step = 0
            while step < count:
                self.set_cursor(word_end(self.buffer, self.cursor), extend)
                step = step + 1
            inclusive = True
            moved = True
        elif key == "$":
            length = self.buffer.get_line_length(self.cursor.line_number)
            col = length
            col = max(col, 1)
            self.set_cursor(Position(self.cursor.line_number, col), extend)
            inclusive = True
            moved = True
        elif key == "^":
            col = first_nonblank_column(self.buffer, self.cursor.line_number)
            self.set_cursor(Position(self.cursor.line_number, col), extend)
            moved = True
        elif key == "%":
            dest = match_bracket(self.buffer, self.cursor)
            if dest.line_number >= 1:
                if dest.line_number != self.cursor.line_number:
                    self._record_jump()
                self.set_cursor(dest, extend)
                inclusive = True
                moved = True
        elif key == ";":
            if self.vim.last_find_char != "":
                self._vim_apply_find(
                    self.vim.last_find_kind,
                    self.vim.last_find_char,
                    count,
                    extend,
                )
                return True
        elif key == ",":
            if self.vim.last_find_char != "":
                self._vim_apply_find(
                    reverse_find_kind(self.vim.last_find_kind),
                    self.vim.last_find_char,
                    count,
                    extend,
                )
                return True
        elif key == ":":
            self.enter_command()
            return True
        elif key == "i":
            self.enter_insert()
            return True
        elif key == "a":
            length = self.buffer.get_line_length(self.cursor.line_number)
            if self.cursor.column <= length:
                self.set_cursor(Position(self.cursor.line_number, self.cursor.column + 1), False)
            self.enter_insert()
            self.render()
            return True
        elif key == "I":
            col = first_nonblank_column(self.buffer, self.cursor.line_number)
            self.set_cursor(Position(self.cursor.line_number, col), False)
            self.enter_insert()
            self.render()
            return True
        elif key == "A":
            col = self.buffer.get_line_length(self.cursor.line_number) + 1
            self.set_cursor(Position(self.cursor.line_number, col), False)
            self.enter_insert()
            self.render()
            return True
        elif key == "o":
            self._vim_open_line(False)
            return True
        elif key == "O":
            self._vim_open_line(True)
            return True
        elif key == "x":
            step = 0
            while step < count:
                self._vim_delete_char()
                step = step + 1
            self._remember_edit("x", count, "")
            return True
        elif key == "u":
            if self.path.startswith("review:"):
                self.canvas.dispatchEvent(Event("zepy-review-viewed"))
                return True
            self.undo()
            self.cursor = clamp_normal(self.buffer, self.cursor)
            self.render()
            self._notify()
            return True
        elif key == "p":
            self._vim_paste(False)
            self._remember_edit("p", count, "")
            return True
        elif key == "P":
            self._vim_paste(True)
            self._remember_edit("P", count, "")
            return True
        elif key == "J":
            self._vim_join(count)
            self._remember_edit("J", count, "")
            return True
        elif key == "K":
            self.canvas.dispatchEvent(Event("zepy-comment-ask"))
            return True
        elif key == "r":
            self.vim.replace_pending = True
            self.vim.count = count
            return True
        elif key == "s":
            step = 0
            while step < count:
                self._vim_delete_char()
                step = step + 1
            self._remember_edit("s", count, "")
            self.enter_insert()
            return True
        elif key == "S":
            self._change_line(count)
            return True
        elif key == "~":
            self._toggle_case(count)
            self._remember_edit("tilde", count, "")
            return True
        elif key == ".":
            self.replay_last_edit()
            return True
        elif key == "/":
            self.enter_search()
            return True
        elif key == "n":
            self._record_jump()
            self.find_next()
            return True
        elif key == "N":
            self._record_jump()
            self.find_previous()
            return True
        elif key == "*":
            word = self._word_under_cursor()
            if word != "":
                self._record_jump()
                self.set_find_query(word)
            return True
        elif key == "}":
            self._record_jump()
            self._paragraph_move(True, count, extend)
            moved = True
        elif key == "{":
            self._record_jump()
            self._paragraph_move(False, count, extend)
            moved = True
        elif key == "z":
            self.vim.z_pending = True
            return True
        elif key == "v":
            self.enter_visual(False)
            return True
        elif key == "V":
            self.enter_visual(True)
            return True
        elif key == "D":
            length = self.buffer.get_line_length(self.cursor.line_number)
            end = Position(self.cursor.line_number, length)
            self.vim.operator = "d"
            self._apply_operator(start, end, True, False)
            return True
        elif key == "C":
            length = self.buffer.get_line_length(self.cursor.line_number)
            end = Position(self.cursor.line_number, length)
            self.vim.operator = "c"
            self._apply_operator(start, end, True, False)
            return True

        if self.path.startswith("review:") and not moved:
            if key == "]":
                self.canvas.dispatchEvent(Event("zepy-review-next-hunk"))
                return True
            if key == "[":
                self.canvas.dispatchEvent(Event("zepy-review-prev-hunk"))
                return True
            if key == "Enter":
                self.canvas.dispatchEvent(Event("zepy-review-jump"))
                return True
            if key == "u":
                self.canvas.dispatchEvent(Event("zepy-review-viewed"))
                return True

        if self.vim.mode == MODE_VISUAL_LINE and moved:
            self._vim_adjust_visual_line()

        if moved and self.vim.operator != "":
            self._apply_operator(start, self.cursor, inclusive, linewise)
            return True
        if moved:
            if self.vim.mode != MODE_INSERT and self.vim.mode != MODE_VISUAL_BLOCK:
                self.cursor = clamp_normal(self.buffer, self.cursor)
            self.render()
            self._notify()
            return True
        return False

    def _register_range(
        self,
        selected: Range,
        gutter: float,
        line_height: float,
        cell_width: float,
        red: float,
        green: float,
        blue: float,
        alpha: float,
        flags: list[int],
    ) -> None:
        line = selected.start_line_number
        while line <= selected.end_line_number:
            if line >= 1 and line <= len(flags) and flags[line - 1] == 1:
                line = line + 1
                continue
            start_col = 1
            if line == selected.start_line_number:
                start_col = selected.start_column
            end_col = self.buffer.get_line_length(line) + 1
            if line == selected.end_line_number:
                end_col = selected.end_column
            cols = self._wrap_columns()
            if cols < 1:
                width = float(end_col - start_col) * cell_width
                width = max(width, 4.0)
                y = float(visible_count_before(line, flags)) * line_height
                x = gutter + float(start_col - 1) * cell_width - self.scroll_x
                self.rectangles.register(
                    x,
                    y,
                    width,
                    line_height,
                    red,
                    green,
                    blue,
                    alpha,
                )
            else:
                col = start_col
                base_y = visual_rows_before(self.buffer, line, cols, flags)
                while col < end_col:
                    row = wrap_row_of_column(col, cols)
                    row_start = row * cols + 1
                    row_end = row_start + cols
                    seg_end = end_col
                    seg_end = min(seg_end, row_end)
                    width = float(seg_end - col) * cell_width
                    width = max(width, 4.0)
                    self.rectangles.register(
                        gutter + float(col - row_start) * cell_width,
                        float(base_y + row) * line_height,
                        width,
                        line_height,
                        red,
                        green,
                        blue,
                        alpha,
                    )
                    col = seg_end
            line = line + 1

    def _snapshot(self) -> HistoryStep:
        return HistoryStep(
            self.buffer.get_value(),
            self.cursor.line_number,
            self.cursor.column,
        )

    def _restore(self, step: HistoryStep) -> None:
        self.buffer.set_value(step.value)
        self.cursor = Position(step.line, step.column)
        self.anchor = None
        self.ensure_visible()

    def _drop_oldest_undo(self) -> None:
        if len(self._undo) <= 100:
            return
        kept: list[HistoryStep] = []
        index = len(self._undo) - 100
        while index < len(self._undo):
            kept.append(self._undo[index])
            index = index + 1
        self._undo = kept

    def _record(self) -> None:
        self._undo.append(self._snapshot())
        self._redo = []
        self._drop_oldest_undo()

    def _pop_undo(self) -> HistoryStep | None:
        count = len(self._undo)
        if count == 0:
            return None
        step = self._undo[count - 1]
        kept: list[HistoryStep] = []
        index = 0
        while index < count - 1:
            kept.append(self._undo[index])
            index = index + 1
        self._undo = kept
        return step

    def _pop_redo(self) -> HistoryStep | None:
        count = len(self._redo)
        if count == 0:
            return None
        step = self._redo[count - 1]
        kept: list[HistoryStep] = []
        index = 0
        while index < count - 1:
            kept.append(self._redo[index])
            index = index + 1
        self._redo = kept
        return step

    def undo(self) -> None:
        step = self._pop_undo()
        if step is None:
            return
        self._redo.append(self._snapshot())
        self._restore(step)

    def redo(self) -> None:
        step = self._pop_redo()
        if step is None:
            return
        self._undo.append(self._snapshot())
        self._restore(step)

    def _wrap_columns(self) -> int:
        if not self.wrap:
            return 0
        cell_width = self.glyphs.cell_width()
        if cell_width <= 0.0:
            return 8
        cols = int((float(self.canvas.width) - self.glyphs.gutter_width()) / cell_width)
        if cols < 8:
            return 8
        return cols

    def max_scroll(self) -> float:
        flags = self._fold_flags()
        cols = self._wrap_columns()
        if cols < 1:
            visible = visible_line_count(flags)
        else:
            visible = visual_line_count(self.buffer, cols, flags)
        if visible < 1:
            visible = self.buffer.get_line_count()
        height = float(visible) * self.glyphs.line_height()
        view = float(self.canvas.height)
        extra = height - view
        if extra < 0.0:
            return 0.0
        return extra

    def _max_line_width(self) -> float:
        cell_width = self.glyphs.cell_width()
        widest = 1
        last = self.buffer.get_line_count()
        line = 1
        while line <= last:
            length = self.buffer.get_line_length(line)
            widest = max(widest, length)
            line = line + 1
        return float(widest) * cell_width

    def max_scroll_x(self) -> float:
        gutter = self.glyphs.gutter_width()
        view = float(self.canvas.width) - gutter
        extra = self._max_line_width() - view
        if extra < 0.0:
            return 0.0
        return extra

    def ensure_visible(self) -> None:
        line_height = self.glyphs.line_height()
        flags = self._fold_flags()
        cols = self._wrap_columns()
        if cols < 1:
            caret_y = float(visible_count_before(self.cursor.line_number, flags)) * line_height
        else:
            caret_y = float(
                visual_rows_before(self.buffer, self.cursor.line_number, cols, flags)
                + wrap_row_of_column(self.cursor.column, cols)
            ) * line_height
        view = float(self.canvas.height)
        if caret_y < self.scroll_y:
            self.scroll_y = caret_y
        elif caret_y + line_height > self.scroll_y + view:
            self.scroll_y = caret_y + line_height - view
        self.scroll_y = max(self.scroll_y, 0.0)
        limit = self.max_scroll()
        self.scroll_y = min(self.scroll_y, limit)
        if cols >= 1:
            self.scroll_x = 0.0
            return
        cell_width = self.glyphs.cell_width()
        gutter = self.glyphs.gutter_width()
        caret_x = float(self.cursor.column - 1) * cell_width
        view_w = float(self.canvas.width) - gutter
        if caret_x < self.scroll_x:
            self.scroll_x = caret_x
        elif caret_x + cell_width > self.scroll_x + view_w:
            self.scroll_x = caret_x + cell_width - view_w
        self.scroll_x = max(self.scroll_x, 0.0)
        limit_x = self.max_scroll_x()
        self.scroll_x = min(self.scroll_x, limit_x)

    def position_at_pixel(self, x: float, y: float) -> Position:
        gutter = self.glyphs.gutter_width()
        line_height = self.glyphs.line_height()
        cell_width = self.glyphs.cell_width()
        flags = self._fold_flags()
        document_y = y + self.scroll_y
        view_index = int(document_y / line_height)
        view_index = max(view_index, 0)
        cols = self._wrap_columns()
        if cols < 1:
            line = line_at_view_index(flags, view_index)
            column = int((x - gutter + self.scroll_x) / cell_width) + 1
        else:
            found = line_at_visual_row(self.buffer, view_index, cols, flags)
            line = found[0]
            column = found[1] * cols + int((x - gutter) / cell_width) + 1
        line = max(line, 1)
        line = min(line, self.buffer.get_line_count())
        column = max(column, 1)
        line_length = self.buffer.get_line_length(line)
        column = min(column, line_length + 1)
        return Position(line, column)

    def delete_selection(self) -> bool:
        selected = self.selection_range()
        if selected.is_empty():
            return False
        self.buffer.apply_edits(selected, "")
        self.cursor = selected.get_start_position()
        self.anchor = None
        return True

    def on_mouse_down(self, event: Event) -> None:
        if not isinstance(event, MouseEvent):
            return
        event.preventDefault()
        self.input.focus()
        rect = self.canvas.getBoundingClientRect()
        x = (float(event.clientX) - rect.left) * self._dpr
        y = (float(event.clientY) - rect.top) * self._dpr
        position = self.position_at_pixel(x, y)
        visual = self._visual()
        extend = event.shiftKey or visual
        self.selecting = True
        self.set_cursor(position, extend)
        if not extend:
            self.anchor = Position(self.cursor.line_number, self.cursor.column)
        if self.vim.mode == MODE_VISUAL_LINE:
            self._vim_adjust_visual_line()
        elif self.vim.mode != MODE_INSERT:
            self.cursor = clamp_normal(self.buffer, self.cursor)
        self.render()
        self._notify()

    def attach_scrollbars(
        self,
        vertical: HTMLElement,
        vthumb: HTMLElement,
        horizontal: HTMLElement,
        hthumb: HTMLElement,
    ) -> None:
        self._vtrack = vertical
        self._vthumb = vthumb
        self._htrack = horizontal
        self._hthumb = hthumb
        vertical.addEventListener("mousedown", self.on_vscroll_down)
        vertical.addEventListener("wheel", self.on_wheel, passive=False)
        horizontal.addEventListener("mousedown", self.on_hscroll_down)
        horizontal.addEventListener("wheel", self.on_wheel, passive=False)
        self.sync_scrollbars()

    def sync_scrollbars(self) -> None:
        self._sync_one_bar(
            self._vtrack,
            self._vthumb,
            self.scroll_y,
            self.max_scroll(),
            float(self.canvas.height),
            True,
        )
        self._sync_one_bar(
            self._htrack,
            self._hthumb,
            self.scroll_x,
            self.max_scroll_x(),
            float(self.canvas.width),
            False,
        )

    def _sync_one_bar(
        self,
        track: HTMLElement | None,
        thumb: HTMLElement | None,
        offset: float,
        limit: float,
        view: float,
        vertical: bool,
    ) -> None:
        if track is None or thumb is None:
            return
        if vertical:
            track_size = float(track.clientHeight)
        else:
            track_size = float(track.clientWidth)
        content = limit + view
        if content <= view or track_size <= 0.0:
            thumb.setAttribute("hidden", "")
            return
        thumb.removeAttribute("hidden")
        size = view / content * track_size
        size = max(size, 24.0)
        size = min(size, track_size)
        max_start = track_size - size
        start = 0.0
        if limit > 0.0:
            start = offset / limit * max_start
        start = max(start, 0.0)
        start = min(start, max_start)
        if vertical:
            thumb.setAttribute(
                "style",
                "height:" + str(int(size)) + "px;top:" + str(int(start)) + "px",
            )
        else:
            thumb.setAttribute(
                "style",
                "width:" + str(int(size)) + "px;left:" + str(int(start)) + "px",
            )

    def on_vscroll_down(self, event: Event) -> None:
        if not isinstance(event, MouseEvent):
            return
        event.preventDefault()
        if event.target is self._vthumb:
            self._bar_drag = "v"
            self._bar_origin = float(event.clientY)
            self._bar_scroll = self.scroll_y
            return
        self._jump_vscroll(float(event.clientY))

    def on_hscroll_down(self, event: Event) -> None:
        if not isinstance(event, MouseEvent):
            return
        event.preventDefault()
        if event.target is self._hthumb:
            self._bar_drag = "h"
            self._bar_origin = float(event.clientX)
            self._bar_scroll = self.scroll_x
            return
        self._jump_hscroll(float(event.clientX))

    def _jump_vscroll(self, client: float) -> None:
        track = self._vtrack
        if track is None:
            return
        rect = track.getBoundingClientRect()
        y = client - rect.top
        view = float(self.canvas.height)
        content = self.max_scroll() + view
        if rect.height <= 0.0 or content <= 0.0:
            return
        self.scroll_y = (y / rect.height) * content - view / 2.0
        self.scroll_y = max(self.scroll_y, 0.0)
        self.scroll_y = min(self.scroll_y, self.max_scroll())
        self.render()
        self._notify()

    def _jump_hscroll(self, client: float) -> None:
        track = self._htrack
        if track is None:
            return
        rect = track.getBoundingClientRect()
        x = client - rect.left
        view = float(self.canvas.width)
        content = self.max_scroll_x() + view
        if rect.width <= 0.0 or content <= 0.0:
            return
        self.scroll_x = (x / rect.width) * content - view / 2.0
        self.scroll_x = max(self.scroll_x, 0.0)
        self.scroll_x = min(self.scroll_x, self.max_scroll_x())
        self.render()
        self._notify()

    def on_mouse_move(self, event: Event) -> None:
        if not isinstance(event, MouseEvent):
            return
        if self._bar_drag == "v":
            track = self._vtrack
            if track is None:
                return
            rect = track.getBoundingClientRect()
            content = self.max_scroll() + float(self.canvas.height)
            if rect.height <= 0.0:
                return
            delta = float(event.clientY) - self._bar_origin
            self.scroll_y = self._bar_scroll + delta / rect.height * content
            self.scroll_y = max(self.scroll_y, 0.0)
            self.scroll_y = min(self.scroll_y, self.max_scroll())
            self.render()
            return
        if self._bar_drag == "h":
            track = self._htrack
            if track is None:
                return
            rect = track.getBoundingClientRect()
            content = self.max_scroll_x() + float(self.canvas.width)
            if rect.width <= 0.0:
                return
            delta = float(event.clientX) - self._bar_origin
            self.scroll_x = self._bar_scroll + delta / rect.width * content
            self.scroll_x = max(self.scroll_x, 0.0)
            self.scroll_x = min(self.scroll_x, self.max_scroll_x())
            self.render()
            return
        if not self.selecting:
            return
        rect = self.canvas.getBoundingClientRect()
        x = (float(event.clientX) - rect.left) * self._dpr
        y = (float(event.clientY) - rect.top) * self._dpr
        position = self.position_at_pixel(x, y)
        self.set_cursor(position, True)
        if self.vim.mode == MODE_VISUAL_LINE:
            self._vim_adjust_visual_line()
        self.render()
        self._notify()

    def on_mouse_up(self, event: Event) -> None:
        if self._bar_drag != "":
            self._bar_drag = ""
            self.render()
            return
        if not self.selecting:
            return
        self.selecting = False
        if self.selection_range().is_empty():
            self.anchor = None
        self.render()
        self._notify()

    def on_wheel(self, event: Event) -> None:
        if not isinstance(event, WheelEvent):
            return
        event.preventDefault()
        dx = event.deltaX
        dy = event.deltaY
        if event.deltaMode == 1:
            dx = dx * self.glyphs.cell_width()
            dy = dy * self.glyphs.line_height()
        elif event.deltaMode == 2:
            dx = dx * float(self.canvas.width)
            dy = dy * float(self.canvas.height)
        else:
            dx = dx * self._dpr
            dy = dy * self._dpr
        if event.shiftKey:
            dx = dx + dy
            dy = 0.0
        self.scroll_y = self.scroll_y + dy
        self.scroll_y = max(self.scroll_y, 0.0)
        limit = self.max_scroll()
        self.scroll_y = min(self.scroll_y, limit)
        self.scroll_x = self.scroll_x + dx
        self.scroll_x = max(self.scroll_x, 0.0)
        limit_x = self.max_scroll_x()
        self.scroll_x = min(self.scroll_x, limit_x)
        self.render()

    def on_before_input(self, event: Event) -> None:
        if not isinstance(event, InputEvent):
            return
        event.preventDefault()
        if self.vim.mode != MODE_INSERT:
            return
        data = event.data
        if event.inputType == "insertText" and data is not None:
            self.insert(data)
            self.render()
            self._notify()
        elif event.inputType == "insertLineBreak":
            self.insert("\n")
            self.render()
            self._notify()
        elif event.inputType == "deleteContentBackward":
            self.backspace()
            self.render()
            self._notify()

    async def on_keydown(self, event: Event) -> None:
        if not isinstance(event, KeyboardEvent):
            return
        key = event.key
        if key == "Escape" or ((event.ctrlKey or event.metaKey) and key == "["):
            event.preventDefault()
            self.enter_normal()
            return
        if event.ctrlKey or event.metaKey:
            if key == "s" or key == "S":
                event.preventDefault()
                self.canvas.dispatchEvent(Event("zepy-save"))
                return
            if key == "z" or key == "Z":
                event.preventDefault()
                if event.shiftKey:
                    self.redo()
                else:
                    self.undo()
                self.render()
                self._notify()
                return
            if key == "y" or key == "Y":
                event.preventDefault()
                self.redo()
                self.render()
                self._notify()
                return
            if (key == "r" or key == "R") and self.vim.mode != MODE_INSERT:
                event.preventDefault()
                self.redo()
                self.cursor = clamp_normal(self.buffer, self.cursor)
                self.render()
                self._notify()
                return
            if (key == "d" or key == "D") and self.vim.mode != MODE_INSERT:
                event.preventDefault()
                self._scroll_by_lines(12)
                return
            if (key == "u" or key == "U") and self.vim.mode != MODE_INSERT:
                event.preventDefault()
                self._scroll_by_lines(-12)
                return
            if key == "a" or key == "A":
                if self.vim.mode != MODE_INSERT:
                    return
                event.preventDefault()
                self.anchor = Position(1, 1)
                last = self.buffer.get_line_count()
                self.cursor = Position(last, self.buffer.get_line_length(last) + 1)
                self.render()
                self._notify()
                return
            if key == "f" or key == "F":
                event.preventDefault()
                if event.shiftKey:
                    self.canvas.dispatchEvent(Event("zepy-search-files"))
                else:
                    self.canvas.dispatchEvent(Event("zepy-find"))
                return
            if key == "h" or key == "H":
                event.preventDefault()
                self.canvas.dispatchEvent(Event("zepy-replace"))
                return
            if key == "p" or key == "P":
                event.preventDefault()
                if event.shiftKey:
                    self.canvas.dispatchEvent(Event("zepy-palette"))
                else:
                    self.canvas.dispatchEvent(Event("zepy-quick-open"))
                return
            if key == "c" or key == "C":
                event.preventDefault()
                await self._copy_clipboard()
                return
            if key == "x" or key == "X":
                event.preventDefault()
                await self._cut_clipboard()
                return
            if key == "v" or key == "V":
                event.preventDefault()
                if self.vim.mode == MODE_INSERT:
                    await self._paste_clipboard()
                else:
                    self.enter_visual_block()
                return
            if (key == "q" or key == "Q") and self.vim.mode != MODE_INSERT:
                event.preventDefault()
                self.enter_visual_block()
                return
            if key == "o" or key == "O":
                if self.vim.mode != MODE_INSERT:
                    event.preventDefault()
                    self._jump_back()
                return
            if key == "i" or key == "I":
                if self.vim.mode != MODE_INSERT:
                    event.preventDefault()
                    self._jump_forward()
                return
            if key == "\\" or key == "|":
                event.preventDefault()
                self.canvas.dispatchEvent(Event("zepy-split"))
                return
            return
        if event.altKey:
            return
        key = event.key
        if key == "F3":
            event.preventDefault()
            if self.find_query == "":
                self.canvas.dispatchEvent(Event("zepy-find"))
            elif event.shiftKey:
                self.find_previous()
            else:
                self.find_next()
            return
        if self.vim.mode == MODE_COMMAND:
            event.preventDefault()
            if key == "Enter":
                text = self.vim.command
                kind = self.vim.command_kind
                self.enter_normal()
                if kind == "/":
                    if text != "":
                        self._record_jump()
                        self.set_find_query(text)
                else:
                    self._run_ex(text)
                return
            if key == "Backspace":
                if len(self.vim.command) > 0:
                    self.vim.command = self.vim.command[0 : len(self.vim.command) - 1]
                self._notify()
                return
            if len(key) == 1:
                self.vim.command = self.vim.command + key
                self._notify()
            return
        if self.vim.mode != MODE_INSERT:
            if (
                key == "ArrowLeft"
                or key == "ArrowRight"
                or key == "ArrowUp"
                or key == "ArrowDown"
                or key == "Home"
                or key == "End"
            ):
                extend = event.shiftKey or self._visual()
            else:
                event.preventDefault()
                if self.vim.mode != MODE_COMMAND:
                    self.handle_vim_key(key)
                return
        extend = event.shiftKey
        if self._visual():
            extend = True
        handled = False
        if key == "ArrowLeft":
            self.move_left(extend)
            handled = True
        elif key == "ArrowRight":
            self.move_right(extend)
            handled = True
        elif key == "ArrowUp":
            self.move_up(extend)
            handled = True
        elif key == "ArrowDown":
            self.move_down(extend)
            handled = True
        elif key == "Home":
            self.set_cursor(Position(self.cursor.line_number, 1), extend)
            handled = True
        elif key == "End":
            line_length = self.buffer.get_line_length(self.cursor.line_number)
            self.set_cursor(Position(self.cursor.line_number, line_length + 1), extend)
            handled = True
        elif key == "Tab":
            self.insert("    ")
            handled = True
        elif key == "Delete":
            self.delete_forward()
            handled = True
        if handled:
            event.preventDefault()
            if self.vim.mode == MODE_VISUAL_LINE:
                self._vim_adjust_visual_line()
            elif self.vim.mode == MODE_NORMAL:
                self.cursor = clamp_normal(self.buffer, self.cursor)
            self.render()
            self._notify()

    def insert(self, text: str) -> None:
        self._record()
        self.delete_selection()
        if text == "\n":
            text = "\n" + self._leading_indent(self.cursor.line_number)
        offset = self.buffer.get_offset_at(self.cursor.line_number, self.cursor.column)
        self.buffer.insert(offset, text)
        self.cursor = self.buffer.get_position_at(offset + len(text))
        self.anchor = None
        self.ensure_visible()

    def backspace(self) -> None:
        selected = self.selection_range()
        if selected.is_empty():
            offset = self.buffer.get_offset_at(self.cursor.line_number, self.cursor.column)
            if offset <= 0:
                return
        self._record()
        if self.delete_selection():
            self.ensure_visible()
            return
        offset = self.buffer.get_offset_at(self.cursor.line_number, self.cursor.column)
        self.buffer.delete(offset - 1, 1)
        self.cursor = self.buffer.get_position_at(offset - 1)
        self.ensure_visible()

    def delete_forward(self) -> None:
        selected = self.selection_range()
        if selected.is_empty():
            offset = self.buffer.get_offset_at(self.cursor.line_number, self.cursor.column)
            if offset >= self.buffer.get_length():
                return
        self._record()
        if self.delete_selection():
            self.ensure_visible()
            return
        offset = self.buffer.get_offset_at(self.cursor.line_number, self.cursor.column)
        self.buffer.delete(offset, 1)
        self.ensure_visible()

    def move_left(self, extend: bool) -> None:
        offset = self.buffer.get_offset_at(self.cursor.line_number, self.cursor.column)
        if offset <= 0:
            self.set_cursor(self.cursor, extend)
            return
        self.set_cursor(self.buffer.get_position_at(offset - 1), extend)

    def move_right(self, extend: bool) -> None:
        offset = self.buffer.get_offset_at(self.cursor.line_number, self.cursor.column)
        if offset >= self.buffer.get_length():
            self.set_cursor(self.cursor, extend)
            return
        self.set_cursor(self.buffer.get_position_at(offset + 1), extend)

    def move_up(self, extend: bool) -> None:
        if self.cursor.line_number <= 1:
            self.set_cursor(Position(1, 1), extend)
            return
        line = self._prev_visible(self.cursor.line_number - 1)
        column = self.cursor.column
        line_length = self.buffer.get_line_length(line)
        column = min(column, line_length + 1)
        self.set_cursor(Position(line, column), extend)

    def move_down(self, extend: bool) -> None:
        last = self.buffer.get_line_count()
        if self.cursor.line_number >= last:
            self.set_cursor(Position(last, self.buffer.get_line_length(last) + 1), extend)
            return
        line = self._next_visible(self.cursor.line_number + 1)
        column = self.cursor.column
        line_length = self.buffer.get_line_length(line)
        column = min(column, line_length + 1)
        self.set_cursor(Position(line, column), extend)

    def render(self) -> None:
        self._refresh_folds()
        scroll_y = self.scroll_y
        flags = self._fold_flags()
        self.glyphs.write_layout(0.0, scroll_y)
        self.rectangles.write_layout(0.0, scroll_y)
        wrap_cols = self._wrap_columns()
        self.glyphs.update(
            self.buffer,
            scroll_y,
            float(self.canvas.height),
            "#858585",
            language_from_path(self.path),
            self.scroll_x,
            self.fold_starts,
            self.fold_ends,
            wrap_cols,
        )
        self.rectangles.clear()
        gutter = self.glyphs.gutter_width()
        line_height = self.glyphs.line_height()
        cell_width = self.glyphs.cell_width()
        view_height = float(self.canvas.height)
        self.rectangles.register(0.0, scroll_y, gutter, view_height, 0.145, 0.145, 0.149, 1.0)
        if wrap_cols < 1:
            cursor_y = float(visible_count_before(self.cursor.line_number, flags)) * line_height
        else:
            cursor_y = float(
                visual_rows_before(self.buffer, self.cursor.line_number, wrap_cols, flags)
                + wrap_row_of_column(self.cursor.column, wrap_cols)
            ) * line_height
        self.rectangles.register(
            gutter,
            cursor_y,
            float(self.canvas.width) - gutter,
            line_height,
            0.165,
            0.165,
            0.169,
            1.0,
        )
        if self.find_query != "":
            self._rebuild_find()
        match_i = 0
        while match_i < len(self.find_matches) and match_i < 64:
            match = self.find_matches[match_i]
            if match_i == self.find_index:
                self._register_range(
                    match, gutter, line_height, cell_width, 0.80, 0.55, 0.15, 0.7, flags
                )
            else:
                self._register_range(
                    match,
                    gutter,
                    line_height,
                    cell_width,
                    0.545,
                    0.278,
                    0.149,
                    0.55,
                    flags,
                )
            match_i = match_i + 1
        if self.vim.mode == MODE_VISUAL_BLOCK and self.anchor is not None:
            top = self._block_top()
            bot = self._block_bot()
            left = self._block_left()
            right = self._block_right()
            line = top
            while line <= bot:
                if line >= 1 and line <= len(flags) and flags[line - 1] == 1:
                    line = line + 1
                    continue
                length = self.buffer.get_line_length(line)
                if length >= left:
                    end_col = right + 1
                    end_col = min(end_col, length + 1)
                    width = float(end_col - left) * cell_width
                    width = max(width, cell_width * 0.4)
                    self.rectangles.register(
                        gutter + float(left - 1) * cell_width - self.scroll_x,
                        float(visible_count_before(line, flags)) * line_height,
                        width,
                        line_height,
                        0.149,
                        0.31,
                        0.471,
                        1.0,
                    )
                line = line + 1
        else:
            selected = self.selection_range()
            if not selected.is_empty():
                self._register_range(
                    selected,
                    gutter,
                    line_height,
                    cell_width,
                    0.149,
                    0.31,
                    0.471,
                    1.0,
                    flags,
                )
        first_view = int(scroll_y / line_height)
        first_view = max(first_view, 0)
        last_view = first_view + int(view_height / line_height) + 2
        view_i = first_view
        while view_i <= last_view:
            line = line_at_view_index(flags, view_i)
            if line >= 1 and line <= len(self.git_kind):
                kind = self.git_kind[line - 1]
                if kind != 0:
                    red = 0.33
                    green = 0.75
                    blue = 0.41
                    if kind == 2:
                        red = 0.90
                        green = 0.75
                        blue = 0.20
                    elif kind == 3:
                        red = 0.95
                        green = 0.30
                        blue = 0.30
                    self.rectangles.register(
                        gutter - 3.0,
                        float(visible_count_before(line, flags)) * line_height,
                        3.0,
                        line_height,
                        red,
                        green,
                        blue,
                        1.0,
                    )
            view_i = view_i + 1
        fold_i = 0
        while fold_i < len(self.fold_starts):
            start = self.fold_starts[fold_i]
            self.rectangles.register(
                4.0,
                float(visible_count_before(start, flags)) * line_height + line_height * 0.3,
                8.0,
                line_height * 0.4,
                0.55,
                0.55,
                0.60,
                1.0,
            )
            fold_i = fold_i + 1
        if wrap_cols < 1:
            caret_x = gutter + float(self.cursor.column - 1) * cell_width - self.scroll_x
        else:
            caret_x = gutter + float(wrap_col_of_column(self.cursor.column, wrap_cols) - 1) * cell_width
        caret_y = cursor_y
        if self.vim.mode == MODE_INSERT:
            self.rectangles.register(caret_x, caret_y, 2.0, line_height, 0.86, 0.86, 0.86, 1.0)
        else:
            self.rectangles.register(
                caret_x, caret_y, cell_width, line_height, 0.86, 0.86, 0.86, 0.35
            )
        encoder = self.device.createCommandEncoder()
        render_pass = encoder.beginRenderPass(
            GPURenderPassDescriptor(
                [
                    GPURenderPassColorAttachment(
                        self._context.getCurrentTexture().createView(),
                        GPUColor(0.118, 0.118, 0.118),
                    )
                ]
            )
        )
        self.rectangles.draw(render_pass)
        self.glyphs.draw(render_pass)
        render_pass.end()
        self.device.queue.submit([encoder.finish()])
        self.sync_scrollbars()


@js
async def create_gpu_text_editor(
    canvas: HTMLCanvasElement,
    input: HTMLTextAreaElement,
    initial: str = "Hello, Zepy",
) -> GpuTextEditor | None:
    return await GpuTextEditor.create(canvas, input, initial)
