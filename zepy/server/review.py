"""Build concatenated git review documents for the workbench."""

from __future__ import annotations

import json
from pathlib import Path

from pyjs import nojs
from pyjs.server.dev import Response

from zepy.server.workspace import (
    git_file_status,
    git_watch_stamp,
    read_text_file,
    remap_git_paths,
    run_git,
    safe_path,
    to_workspace_path,
    zepy_state_dir,
)

REVIEW_MAX_CHARS = 400_000


@nojs
def normalize_scope(scope: str) -> str:
    if scope == "unpushed":
        return "unpushed"
    return "dirty"


@nojs
def upstream_ref() -> str:
    name = run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    name = name.strip()
    if name != "":
        return name
    for candidate in ("origin/main", "origin/master", "main", "master"):
        probe = run_git(["rev-parse", "--verify", candidate])
        if probe.strip() != "":
            return candidate
    return ""


@nojs
def parse_name_status(text: str) -> dict[str, str]:
    status, _orig = parse_name_status_full(text)
    return status


@nojs
def parse_name_status_full(text: str) -> tuple[dict[str, str], dict[str, str]]:
    status: dict[str, str] = {}
    orig: dict[str, str] = {}
    for raw in text.splitlines():
        if raw == "":
            continue
        parts = raw.split("\t")
        if len(parts) < 2:
            continue
        code = parts[0][0]
        path = parts[len(parts) - 1]
        kind = "mod"
        if code == "A":
            kind = "add"
        elif code == "D":
            kind = "del"
        elif code == "U":
            kind = "conflict"
        elif code == "R":
            kind = "ren"
        elif code == "C":
            kind = "copy"
        if (kind == "ren" or kind == "copy") and len(parts) >= 3:
            orig[path] = parts[1]
        status[path] = kind
    return status, orig


@nojs
def git_changes_for_scope(scope: str) -> dict[str, str]:
    scope = normalize_scope(scope)
    if scope == "dirty":
        return git_file_status()
    upstream = upstream_ref()
    if upstream == "":
        return {}
    status, _orig = parse_name_status_full(
        run_git(["diff", "--name-status", "-M", "-C", upstream + "...HEAD"])
    )
    return remap_git_paths(status)


@nojs
def git_renames_for_scope(scope: str) -> dict[str, str]:
    scope = normalize_scope(scope)
    mapped: dict[str, str] = {}
    if scope == "dirty":
        text = run_git(["diff", "--name-status", "-M", "-C", "HEAD"])
    else:
        upstream = upstream_ref()
        if upstream == "":
            return mapped
        text = run_git(["diff", "--name-status", "-M", "-C", upstream + "...HEAD"])
    _status, orig = parse_name_status_full(text)
    for dest, src in orig.items():
        mapped[to_workspace_path(dest)] = to_workspace_path(src)
    return mapped


@nojs
def diff_edit_counts(diff: str) -> tuple[int, int]:
    plus = 0
    minus = 0
    for row in diff.splitlines():
        if row.startswith(("+++", "---")):
            continue
        if row.startswith("+"):
            plus = plus + 1
        elif row.startswith("-"):
            minus = minus + 1
    return plus, minus


@nojs
def parse_numstat(text: str) -> dict[str, tuple[int, int]]:
    counts: dict[str, tuple[int, int]] = {}
    for raw in text.splitlines():
        parts = raw.split("\t")
        if len(parts) < 3:
            continue
        plus_raw = parts[0]
        minus_raw = parts[1]
        path = parts[2]
        plus = 0
        minus = 0
        if plus_raw != "-":
            try:
                plus = int(plus_raw)
            except ValueError:
                plus = 0
        if minus_raw != "-":
            try:
                minus = int(minus_raw)
            except ValueError:
                minus = 0
        counts[to_workspace_path(path)] = (plus, minus)
    return counts


@nojs
def git_numstat(scope: str, ignore_ws: bool) -> dict[str, tuple[int, int]]:
    scope = normalize_scope(scope)
    args = ["diff", "--numstat"]
    if ignore_ws:
        args.append("-w")
    if scope == "unpushed":
        upstream = upstream_ref()
        if upstream == "":
            return {}
        args.append(upstream + "...HEAD")
    else:
        args.append("HEAD")
    return parse_numstat(run_git(args))


@nojs
def file_unified_diff(path: str, scope: str, kind: str, context: int, ignore_ws: bool) -> str:
    scope = normalize_scope(scope)
    unified = "-U" + str(context)
    extra: list[str] = ["-M", "-C", "--diff-algorithm=histogram"]
    if ignore_ws:
        extra.append("-w")
    if scope == "unpushed":
        upstream = upstream_ref()
        if upstream == "":
            return ""
        return run_git(["diff", "--no-color", unified, *extra, upstream + "...HEAD", "--", path])
    if kind == "untracked" or kind == "add":
        disk = safe_path(path)
        if disk is None or not disk.is_file():
            return ""
        body = read_text_file(disk)
        lines = body.splitlines()
        header = "@@ -0,0 +" + "1," + str(max(len(lines), 1)) + " @@\n"
        rendered = ""
        if len(lines) == 0:
            return header + "+\n"
        for row in lines:
            rendered = rendered + "+" + row + "\n"
        return header + rendered
    return run_git(["diff", "--no-color", unified, *extra, "HEAD", "--", path])


@nojs
def build_review_document(scope: str, context: int, ignore_ws: bool) -> dict[str, object]:
    scope = normalize_scope(scope)
    changes = git_changes_for_scope(scope)
    renames = git_renames_for_scope(scope)
    paths = list(changes.keys())
    paths.sort()
    chunks: list[str] = []
    files: list[dict[str, object]] = []
    line_no = 1
    total = 0
    plus_all = 0
    minus_all = 0
    for path in paths:
        kind = changes[path]
        diff = file_unified_diff(path, scope, kind, context, ignore_ws)
        if diff.strip() == "":
            continue
        mark = "M"
        orig = renames.get(path, "")
        if kind == "add" or kind == "untracked":
            mark = "A"
        elif kind == "del":
            mark = "D"
        elif kind == "conflict":
            mark = "C"
        elif kind == "ren":
            mark = "R"
        elif kind == "copy":
            mark = "C"
        if orig != "":
            header = "===== " + orig + " -> " + path + " [" + mark + "] ====="
        else:
            header = "===== " + path + " [" + mark + "] ====="
        body = header + "\n" + diff.rstrip("\n")
        piece_lines = body.split("\n")
        start = line_no
        end = line_no + len(piece_lines) - 1
        plus, minus = diff_edit_counts(diff)
        plus_all = plus_all + plus
        minus_all = minus_all + minus
        files.append(
            {
                "path": path,
                "git": kind,
                "start_line": start,
                "end_line": end,
                "plus": plus,
                "minus": minus,
                "orig": orig,
            }
        )
        chunks.append(body)
        line_no = end + 2
        total = total + len(body) + 2
        if total > REVIEW_MAX_CHARS:
            break
    content = "\n\n".join(chunks)
    if content == "":
        content = "No changes in this range.\n"
    doc_path = "review:" + scope
    return {
        "path": doc_path,
        "content": content,
        "scope": scope,
        "files": files,
        "plus": plus_all,
        "minus": minus_all,
        "stamp": git_watch_stamp(),
    }


@nojs
def review_state_path() -> Path:
    return zepy_state_dir() / "review.json"


@nojs
def load_viewed() -> list[str]:
    path = review_state_path()
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError, UnicodeDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    viewed = payload.get("viewed")
    if not isinstance(viewed, list):
        return []
    rows: list[str] = []
    for item in viewed:
        if isinstance(item, str):
            rows.append(item)
    return rows


@nojs
def save_viewed(paths: list[str]) -> None:
    dest = review_state_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"viewed": paths}), encoding="utf-8")


@nojs
def serve_review(request) -> Response:
    scope = normalize_scope(request.query_value("scope"))
    context = 3
    if request.query_value("context") == "wide":
        context = 10
    ignore_ws = request.query_value("ws") == "1"
    payload = build_review_document(scope, context, ignore_ws)
    payload["viewed"] = load_viewed()
    return Response.json(payload)


@nojs
def serve_git_diff(request) -> Response:
    scope = normalize_scope(request.query_value("scope"))
    relative = request.query_value("path")
    kind = request.query_value("kind")
    context = 3
    if request.query_value("context") == "wide":
        context = 10
    ignore_ws = request.query_value("ws") == "1"
    if kind == "":
        changes = git_changes_for_scope(scope)
        kind = changes.get(relative, "mod")
    diff = file_unified_diff(relative, scope, kind, context, ignore_ws)
    plus, minus = diff_edit_counts(diff)
    return Response.json(
        {
            "path": relative,
            "scope": scope,
            "content": diff,
            "git": kind,
            "plus": plus,
            "minus": minus,
        }
    )


@nojs
def comments_path() -> Path:
    return zepy_state_dir() / "comments.jsonl"


@nojs
def serve_review_comment(request) -> Response:
    try:
        payload = request.json()
    except ValueError, UnicodeDecodeError:
        return Response.json({"ok": False}, status=400)
    if not isinstance(payload, dict):
        return Response.json({"ok": False}, status=400)
    path = payload.get("path")
    text = payload.get("text")
    line = payload.get("line")
    end_line = payload.get("end_line")
    snippet = payload.get("snippet")
    if not isinstance(path, str) or not isinstance(text, str) or text.strip() == "":
        return Response.json({"ok": False}, status=400)
    line_no = 0
    if isinstance(line, int):
        line_no = line
    end_no = line_no
    if isinstance(end_line, int) and end_line > 0:
        end_no = end_line
    clip = ""
    if isinstance(snippet, str):
        clip = snippet
    dest = comments_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    row = json.dumps(
        {
            "path": path,
            "line": line_no,
            "end_line": end_no,
            "snippet": clip,
            "text": text.strip(),
        }
    )
    with dest.open("a", encoding="utf-8") as handle:
        handle.write(row + "\n")
    return Response.json({"ok": True})


@nojs
def serve_review_viewed(request) -> Response:
    try:
        payload = request.json()
    except ValueError, UnicodeDecodeError:
        return Response.json({"ok": False}, status=400)
    if not isinstance(payload, dict):
        return Response.json({"ok": False}, status=400)
    path = payload.get("path")
    viewed_flag = payload.get("viewed")
    if not isinstance(path, str) or path == "":
        return Response.json({"ok": False}, status=400)
    rows = load_viewed()
    present = path in rows
    mark = True
    if isinstance(viewed_flag, bool):
        mark = viewed_flag
    if mark and not present:
        rows.append(path)
    if not mark and present:
        rows = [item for item in rows if item != path]
    save_viewed(rows)
    return Response.json({"ok": True, "viewed": rows})
