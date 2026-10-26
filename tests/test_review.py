from zepy.editor.common.review_nav import (
    extract_hunk,
    hunk_new_line,
    locate_review_target,
    next_hunk_line,
    next_review_header_line,
    parse_review_header,
)
from zepy.server.review import parse_name_status
from zepy.server.workspace import package_root, workspace_root


def test_workspace_root_stays_inside_the_zepy_checkout():
    assert workspace_root() == package_root()


def test_parse_review_headers_and_hunks():
    assert parse_review_header("===== zepy/app.py [M] =====") == "zepy/app.py"
    assert parse_review_header("===== old.py -> new.py [R] =====") == "new.py"
    assert parse_review_header("hello") == ""
    assert hunk_new_line("@@ -10,2 +12,3 @@ def x") == 12
    assert hunk_new_line("+added") == 0


def test_locate_review_target_tracks_new_file_line():
    lines = [
        "===== zepy/app.py [M] =====",
        "@@ -10,3 +10,4 @@",
        " context",
        "-old",
        "+new",
        " more",
        "",
        "===== zepy/chat.py [A] =====",
        "@@ -0,0 +1,2 @@",
        "+a",
        "+b",
    ]
    path, line = locate_review_target(lines, 5)
    assert path == "zepy/app.py"
    assert line == 11
    path, line = locate_review_target(lines, 10)
    assert path == "zepy/chat.py"
    assert line == 1
    assert next_review_header_line(lines, 2, False) == 8
    assert next_review_header_line(lines, 9, True) == 8
    assert next_review_header_line(lines, 8, True) == 1
    assert next_hunk_line(lines, 1, False) == 2
    assert next_hunk_line(lines, 3, False) == 9
    hunk = extract_hunk(lines, 5)
    assert "@@ -10,3 +10,4 @@" in hunk
    assert "+new" in hunk


def test_parse_name_status_maps_codes():
    text = "M\tzepy/app.py\nA\tzepy/new.py\nD\told.py\nR100\ta.py\tb.py\n"
    status = parse_name_status(text)
    assert status["zepy/app.py"] == "mod"
    assert status["zepy/new.py"] == "add"
    assert status["old.py"] == "del"
    assert status["b.py"] == "ren"
