from pyjs import js

from zepy.editor.common.comment import line_span_label, numbered_snippet


@js
def test_line_span_label_uses_basename_and_range():
    assert line_span_label("zepy/app.py", 12, 12) == "app.py:12"
    assert line_span_label("zepy/app.py", 12, 18) == "app.py:12-18"
    assert line_span_label("notes.txt", 0, 0) == "notes.txt"


@js
def test_numbered_snippet_prefixes_source_lines():
    assert numbered_snippet("alpha\nbeta", 10) == "10| alpha\n11| beta"
    assert numbered_snippet("only\n", 1) == "1| only"
    assert numbered_snippet("", 4) == ""
