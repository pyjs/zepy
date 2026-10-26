import asyncio
import json

from pyjs.server.dev import Request

import zepy.server.app as app_module
from zepy.server.app import (
    serve_chat_history,
    serve_chat_send,
    serve_file,
    serve_git,
    serve_git_status,
    serve_save,
    serve_search,
    serve_tree,
)
from zepy.server.workspace import (
    git_prefix,
    inherit_git_status,
    list_workspace,
    parse_blame,
    parse_diff_gutter,
    parse_status_porcelain,
    porcelain_kind,
    read_text_file,
    remap_git_paths,
    safe_path,
    to_git_path,
    to_workspace_path,
    workspace_root,
)


def test_workspace_lists_sample_files():
    entries = asyncio.run(list_workspace())
    paths = [entry["path"] for entry in entries]
    assert "workspace" in paths
    assert "workspace/welcome.md" in paths
    assert "workspace/hello.py" in paths
    assert "zepy/app.py" in paths
    assert "external" not in paths
    welcome = next(entry for entry in entries if entry["path"] == "workspace/welcome.md")
    assert welcome["kind"] == "file"
    assert welcome["content"] is None


def test_git_paths_strip_the_nested_workspace_prefix():
    prefix = git_prefix()
    if prefix == "":
        assert to_workspace_path("zepy/app.py") == "zepy/app.py"
        return
    assert to_workspace_path(prefix + "/workspace/hello.py") == "workspace/hello.py"
    assert to_git_path("workspace/hello.py") == prefix + "/workspace/hello.py"
    remapped = remap_git_paths({prefix + "/README.md": "mod", "other/file.py": "mod"})
    assert remapped.get("README.md") == "mod"
    assert "other/file.py" not in remapped


def test_porcelain_rename_is_its_own_kind():
    assert porcelain_kind("R ") == "ren"
    assert porcelain_kind("C ") == "copy"
    status = parse_status_porcelain("R  old.py -> new.py\n")
    assert status["new.py"] == "ren"


def test_safe_path_rejects_parent_segments():
    assert safe_path("..") is None
    assert safe_path("workspace/../external") is None
    path = safe_path("workspace/hello.py")
    assert path is not None
    assert path.is_file()
    assert "greet" in read_text_file(path)


def test_server_callbacks_live_on_the_served_module():
    assert hasattr(app_module, "serve_tree")
    assert hasattr(app_module, "serve_file")
    assert hasattr(app_module, "serve_save")
    assert hasattr(app_module, "serve_search")
    assert hasattr(app_module, "serve_git")
    assert hasattr(app_module, "serve_git_status")
    assert hasattr(app_module, "serve_chat_history")
    assert hasattr(app_module, "serve_chat_send")
    assert hasattr(app_module, "serve_review")
    assert hasattr(app_module, "serve_git_diff")
    assert hasattr(app_module, "render")
    assert serve_tree.__name__ == "serve_tree"
    assert serve_file.__name__ == "serve_file"
    assert serve_save.__name__ == "serve_save"
    assert serve_search.__name__ == "serve_search"
    assert serve_git.__name__ == "serve_git"
    assert serve_git_status.__name__ == "serve_git_status"
    assert serve_chat_history.__name__ == "serve_chat_history"
    assert serve_chat_send.__name__ == "serve_chat_send"


def test_serve_search_finds_sample_text():
    request = Request(
        method="GET",
        path="/api/search",
        raw_path="/api/search",
        query={"q": ("greet",)},
        headers={},
        body=b"",
    )
    response = serve_search(request)
    assert response.status == 200
    payload = json.loads(response.body)
    assert len(payload) >= 1
    assert any("hello.py" in hit["path"] for hit in payload)


def _post_save(path: str, content: str) -> Request:
    body = json.dumps({"path": path, "content": content}).encode("utf-8")
    return Request(
        method="POST",
        path="/api/file",
        raw_path="/api/file",
        query={},
        headers={"Content-Type": "application/json"},
        body=body,
    )


def test_serve_save_overwrites_an_existing_file():
    relative = "workspace/_zepy_save_probe.txt"
    path = workspace_root() / relative
    path.write_text("before\n", encoding="utf-8")
    try:
        response = serve_save(_post_save(relative, "after\n"))
        assert response.status == 200
        assert path.read_text(encoding="utf-8") == "after\n"
    finally:
        if path.exists():
            path.unlink()


def test_serve_save_rejects_parent_segments_and_missing_files():
    assert serve_save(_post_save("..", "nope")).status == 400
    assert serve_save(_post_save("workspace/missing-nope.txt", "x")).status == 404


def test_parse_diff_gutter_marks_add_mod_and_del():
    diff = """\
@@ -1 +1 @@
-old
+new
@@ -10,0 +11,2 @@
+a
+b
@@ -20,3 +21,0 @@
-a
-b
-c
"""
    marks = parse_diff_gutter(diff)
    kinds = {(mark["line"], mark["kind"]) for mark in marks}
    assert (1, "mod") in kinds
    assert (11, "add") in kinds
    assert (12, "add") in kinds
    assert (21, "del") in kinds


def test_parse_blame_reads_author_and_summary():
    text = (
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 1 1 1\n"
        "author Ada\n"
        "summary hello\n"
        "\tline one\n"
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 2 2\n"
        "author Beau\n"
        "summary there\n"
        "\tline two\n"
    )
    rows = parse_blame(text)
    assert rows[0]["line"] == 1
    assert rows[0]["author"] == "Ada"
    assert rows[0]["summary"] == "hello"
    assert rows[1]["author"] == "Beau"


def test_serve_file_includes_mtime():
    request = Request(
        method="GET",
        path="/api/file",
        raw_path="/api/file",
        query={"path": ("workspace/hello.py",)},
        headers={},
        body=b"",
    )
    response = serve_file(request)
    assert response.status == 200
    payload = json.loads(response.body)
    assert "greet" in payload["content"]
    assert payload["mtime"] > 0


def test_serve_git_returns_gutter_payload():
    request = Request(
        method="GET",
        path="/api/git",
        raw_path="/api/git",
        query={"path": ("workspace/hello.py",)},
        headers={},
        body=b"",
    )
    response = serve_git(request)
    assert response.status == 200
    payload = json.loads(response.body)
    assert payload["path"] == "workspace/hello.py"
    assert isinstance(payload["gutter"], list)
    assert isinstance(payload["blame"], list)


def test_porcelain_kind_maps_status_letters():
    assert porcelain_kind(" M") == "mod"
    assert porcelain_kind("M ") == "mod"
    assert porcelain_kind("MM") == "mod"
    assert porcelain_kind("A ") == "add"
    assert porcelain_kind("??") == "untracked"
    assert porcelain_kind(" D") == "del"
    assert porcelain_kind("UU") == "conflict"
    assert porcelain_kind("??") == "untracked"


def test_parse_status_porcelain_and_directory_inherit():
    text = (
        " M zepy/app.py\n?? zepy/new.py\n D zepy/gone.py\n?? workspace/scratch.txt\nA  src/added.py\n"
    )
    files = parse_status_porcelain(text)
    assert files["zepy/app.py"] == "mod"
    assert files["zepy/new.py"] == "untracked"
    assert files["zepy/gone.py"] == "del"
    assert files["workspace/scratch.txt"] == "untracked"
    assert files["src/added.py"] == "add"
    inherited = inherit_git_status(files)
    assert inherited["zepy"] == "mod"
    assert inherited["workspace"] == "untracked"
    assert inherited["src"] == "add"
    assert inherited["zepy/app.py"] == "mod"


def test_serve_git_status_lists_paths():
    request = Request(
        method="GET",
        path="/api/git-status",
        raw_path="/api/git-status",
        query={},
        headers={},
        body=b"",
    )
    response = serve_git_status(request)
    assert response.status == 200
    payload = json.loads(response.body)
    assert isinstance(payload, dict)
    assert isinstance(payload["tree"], list)
    assert isinstance(payload["changes"], list)
    for item in payload["tree"] + payload["changes"]:
        assert "path" in item
        assert item["git"] in {"mod", "add", "untracked", "del", "conflict", "ren", "copy"}


def test_workspace_entries_include_git_field():
    entries = asyncio.run(list_workspace())
    assert all("git" in entry for entry in entries)
    kinds = {entry["git"] for entry in entries}
    assert kinds <= {"", "mod", "add", "untracked", "del", "conflict", "ren", "copy"}


def test_workspace_json_round_trips():
    payload = json.dumps(asyncio.run(list_workspace()), separators=(",", ":"))
    loaded = json.loads(payload)
    assert isinstance(loaded, list)
    assert loaded[0]["name"]
