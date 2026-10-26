# Chat transcript rows built from pyjs.web.ui MessageScroller primitives.

from pyjs import js
from pyjs.javascript import JSONObject
from pyjs.web.dom import Element
from pyjs.web.ui.bubble import Bubble, BubbleContent
from pyjs.web.ui.marker import Marker, MarkerContent
from pyjs.web.ui.message import Message, MessageContent, MessageHeader
from pyjs.web.ui.message_scroller import MessageScroller, MessageScrollerItem
from pyjs.web.ui.typeset import Typeset


class ChatLine(JSONObject):
    role: str
    text: str


@js
def chat_empty_item() -> Element:
    hint = MarkerContent(
        "Ask Codex about the open file. Selection is included when you send."
    )
    hint.setAttribute("style", "color:#d4d4d4")
    return MessageScrollerItem(Marker(hint), message_id="empty")


@js
def chat_item(role: str, text: str, message_id: str = "") -> Element:
    if role == "tool" or role == "stream":
        content = MarkerContent(text)
        content.setAttribute("style", "color:#d4d4d4")
        if role == "stream":
            content.setAttribute("data-shimmer", "")
        return MessageScrollerItem(Marker(content), message_id=message_id)
    align = "start"
    variant = "ghost"
    name = "Codex"
    if role == "user":
        align = "end"
        variant = "default"
        name = "You"
    return MessageScrollerItem(
        Message(
            MessageContent(
                MessageHeader(name),
                Bubble(
                    BubbleContent(Typeset(text, preset="chat")),
                    align=align,
                    variant=variant,
                ),
            ),
            align=align,
        ),
        scroll_anchor=role == "user",
        message_id=message_id,
    )


@js
def chat_row_id(index: int, role: str) -> str:
    return "m-" + str(index) + "-" + role


@js
def sync_chat_log(
    scroller: MessageScroller,
    messages: list[ChatLine],
    partial: str,
    rendered_count: int,
    rendered_partial: str,
) -> None:
    rows: list[Element] = []
    if len(messages) == 0 and partial == "":
        scroller.replace_messages(chat_empty_item())
        return
    index = 0
    while index < len(messages):
        line = messages[index]
        rows.append(chat_item(line["role"], line["text"], chat_row_id(index, line["role"])))
        index = index + 1
    if partial != "":
        rows.append(chat_item("stream", partial, "stream"))
    if rendered_count < 0 or len(messages) < rendered_count:
        scroller.replace_messages(*rows)
        return
    if len(messages) == rendered_count and partial == rendered_partial:
        return
    if len(messages) == rendered_count and rendered_partial != partial:
        items = scroller.item_elements()
        if len(items) > 0:
            last = items[len(items) - 1]
            marker = last.querySelector("[data-slot=marker-content]")
            if marker is not None and partial != "":
                marker.textContent = partial
                if partial != "":
                    marker.setAttribute("data-shimmer", "")
                return
            if marker is not None and partial == "":
                last.remove()
                return
        scroller.replace_messages(*rows)
        return
    if rendered_count == 0 and len(scroller.item_elements()) <= 1:
        scroller.replace_messages(*rows)
        return
    start = rendered_count
    added: list[Element] = []
    while start < len(rows):
        added.append(rows[start])
        start = start + 1
    if rendered_partial != "" and len(scroller.item_elements()) > 0:
        last = scroller.item_elements()[len(scroller.item_elements()) - 1]
        last.remove()
    scroller.append_messages(*added)
