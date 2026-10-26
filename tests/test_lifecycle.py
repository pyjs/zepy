import pytest
from pyjs import js

from zepy.base.common.event import Emitter
from zepy.base.common.lifecycle import Disposable, DisposableStore, to_disposable
from zepy.editor.browser.gpu.buffer_dirty_tracker import BufferDirtyTracker
from zepy.editor.common.core.position import Position
from zepy.editor.common.core.range import Range
from zepy.editor.common.model.piece_tree_text_buffer.piece_tree_base import PieceTreeBase


@pytest.mark.pyjs_python
@js
def test_disposable_store_disposes_children():
    store = DisposableStore()
    disposed = [0]

    def mark() -> None:
        disposed[0] = 1

    store.add(to_disposable(mark))
    store.dispose()
    assert disposed[0] == 1


@pytest.mark.pyjs_python
@js
def test_emitter_fires_listeners():
    emitter = Emitter()
    seen = [0]

    def receive(value: object) -> None:
        seen[0] = 1

    emitter.event(receive)
    emitter.fire("ok")
    assert seen[0] == 1


@pytest.mark.pyjs_python
@js
def test_disposable_register_cleans_up():
    owner = Disposable()
    disposed = [0]

    def mark() -> None:
        disposed[0] = 1

    owner._register(to_disposable(mark))
    owner.dispose()
    assert disposed[0] == 1


@pytest.mark.pyjs_python
@js
def test_buffer_dirty_tracker_flags_a_range():
    tracker = BufferDirtyTracker()
    assert tracker.is_dirty is False
    tracker.flag(0)
    tracker.flag(31)
    assert tracker.data_offset == 0
    assert tracker.dirty_size == 32
    tracker.clear()
    assert tracker.is_dirty is False


@pytest.mark.pyjs_python
@js
def test_piece_tree_insert_delete_and_positions():
    buffer = PieceTreeBase("Hello, Zepy")
    assert buffer.get_line_count() == 1
    assert buffer.get_line_content(1) == "Hello, Zepy"
    offset = buffer.get_offset_at(1, 8)
    buffer.insert(offset, "\n")
    assert buffer.get_line_count() == 2
    assert buffer.get_line_content(1) == "Hello, "
    assert buffer.get_line_content(2) == "Zepy"
    position = buffer.get_position_at(0)
    assert position.equals(Position(1, 1))
    buffer.apply_edits(Range(1, 1, 1, 7), "Hi")
    assert buffer.get_line_content(1) == "Hi "
    buffer.delete(0, 3)
    assert buffer.get_line_content(1) == ""
    assert buffer.get_line_content(2) == "Zepy"


@pytest.mark.pyjs_python
@js
def test_piece_tree_replaces_a_selected_range():
    buffer = PieceTreeBase("abcdef")
    buffer.apply_edits(Range(1, 2, 1, 5), "XY")
    assert buffer.get_value() == "aXYef"
