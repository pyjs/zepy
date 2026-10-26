from pyjs import js

from zepy.workbench_chat import chat_empty_item, chat_item


@js
def test_chat_rows_use_message_bubble_and_marker_slots():
    user = chat_item("user", "hello")
    assert user.querySelector("[data-slot='message']") is not None
    assert user.querySelector("[data-slot='bubble']") is not None
    assert user.querySelector("[data-slot='typeset']") is not None
    assert user.getAttribute("data-scroll-anchor") == "true"
    assistant = chat_item("assistant", "hi")
    assert assistant.querySelector("[data-align='start']") is not None
    assert assistant.querySelector("[data-slot='bubble']") is not None
    tool = chat_item("tool", "read_file")
    assert tool.querySelector("[data-slot='marker']") is not None
    stream = chat_item("stream", "Thinking")
    marker = stream.children[0]
    content = marker.children[0]
    assert content.getAttribute("data-slot") == "marker-content"
    assert content.getAttribute("data-shimmer") == ""
    empty = chat_empty_item()
    assert empty.querySelector("[data-slot='marker']") is not None
