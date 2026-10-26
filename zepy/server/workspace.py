"""Browser workspace routes and Git metadata."""

import asyncio
import os
import re
import subprocess
from pathlib import Path

from pyjs import nojs
from pyjs.server.dev import Response

from zepy.server.filesystem import PythonFileSystem
from zepy.services.workspace import MAX_FILE_BYTES, WorkspaceService

DIFF_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@nojs
def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


@nojs
def git_root_from(start: Path) -> Path | None:
    current = start.resolve()
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


@nojs
def workspace_root() -> Path:
    env = os.environ.get("ZEPY_ROOT")
    if env:
        return Path(env).resolve()
    pkg = package_root()
    cwd = Path.cwd().resolve()
    try:
        cwd.relative_to(pkg)
        return pkg
    except ValueError:
        pass
    found = git_root_from(cwd)
    if found is not None:
        return found
    return pkg


@nojs
def safe_path(relative: str) -> Path | None:
    if relative == "" or relative == ".":
        return workspace_root()
    if Path(relative).is_absolute() or ".." in relative.replace("\\", "/").split("/"):
        return None
    candidate = (workspace_root() / relative).resolve()
    try:
        candidate.relative_to(workspace_root())
    except ValueError:
        return None
    return candidate


@nojs
def read_text_file(path: Path) -> str:
    if not path.is_file():
        return ""
    if path.stat().st_size > MAX_FILE_BYTES:
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""


def workspace_service() -> WorkspaceService:
    return WorkspaceService(str(workspace_root()), PythonFileSystem())


async def list_workspace() -> list[dict[str, object]]:
    entries = await workspace_service().tree()
    apply_git_status(entries, await asyncio.to_thread(git_status_map))
    return entries


def serve_tree(request) -> Response:
    return Response.json(asyncio.run(list_workspace()))


def workspace_request(operation: str, arguments: dict[str, object]) -> Response:
    try:
        return Response.json(asyncio.run(workspace_service().execute(operation, arguments)))
    except FileNotFoundError:
        return Response.json({"error": "File not found"}, status=404)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        return Response.json({"error": str(error)}, status=400)


def serve_file(request) -> Response:
    return workspace_request(
        "read", {"path": request.query_value("path"), "revision": request.query_value("rev")}
    )


def serve_save(request) -> Response:
    try:
        arguments = request.json()
    except ValueError, UnicodeDecodeError:
        return Response.json({"error": "Invalid JSON"}, status=400)
    if not isinstance(arguments, dict):
        return Response.json({"error": "Expected an object"}, status=400)
    return workspace_request("write", arguments)


def serve_search(request) -> Response:
    return workspace_request("search", {"query": request.query_value("q")})


@nojs
def parse_diff_gutter(diff: str) -> list[dict[str, object]]:
    marks: list[dict[str, object]] = []
    for row in diff.splitlines():
        matched = DIFF_HUNK.match(row)
        if matched is None:
            continue
        old_count = 1
        if matched.group(2) is not None:
            old_count = int(matched.group(2))
        new_start = int(matched.group(3))
        new_count = 1
        if matched.group(4) is not None:
            new_count = int(matched.group(4))
        if new_count > 0:
            kind = "mod"
            if old_count == 0:
                kind = "add"
            index = 0
            while index < new_count:
                marks.append({"line": new_start + index, "kind": kind})
                index = index + 1
        elif old_count > 0:
            line = new_start
            line = max(line, 1)
            marks.append({"line": line, "kind": "del"})
    return marks


@nojs
def parse_blame(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    line_no = 0
    author = ""
    summary = ""
    for row in text.splitlines():
        if len(row) >= 42 and row[40] == " ":
            parts = row.split(" ")
            if len(parts) >= 3 and len(parts[0]) == 40:
                try:
                    line_no = int(parts[2])
                except ValueError:
                    line_no = 0
                author = ""
                summary = ""
                continue
        if row.startswith("author "):
            author = row[7:]
        elif row.startswith("summary "):
            summary = row[8:]
        elif row.startswith("\t") and line_no > 0:
            rows.append({"line": line_no, "author": author, "summary": summary})
            line_no = 0
    return rows


@nojs
def run_git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=workspace_root(),
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


@nojs
def porcelain_kind(xy: str) -> str:
    if len(xy) < 2:
        return ""
    a = xy[0]
    b = xy[1]
    if a == "U" or b == "U" or xy == "AA" or xy == "DD":
        return "conflict"
    if a == "?" or b == "?":
        return "untracked"
    if a == "D" or b == "D":
        return "del"
    if a == "R" or b == "R":
        return "ren"
    if a == "C" or b == "C":
        return "copy"
    if a == "M" or b == "M" or a == "T":
        return "mod"
    if a == "A" or b == "A":
        return "add"
    return ""


@nojs
def git_kind_rank(kind: str) -> int:
    if kind == "conflict":
        return 5
    if kind == "mod" or kind == "ren" or kind == "copy":
        return 4
    if kind == "del":
        return 3
    if kind == "add":
        return 2
    if kind == "untracked":
        return 1
    return 0


@nojs
def parent_dir(path: str) -> str:
    slash = path.rfind("/")
    if slash <= 0:
        return ""
    return path[0:slash]


@nojs
def merge_git_kind(current: str, incoming: str, for_dir: bool) -> str:
    kind = incoming
    if for_dir and kind == "del":
        kind = "mod"
    if git_kind_rank(kind) > git_kind_rank(current):
        return kind
    return current


@nojs
def parse_status_porcelain(text: str) -> dict[str, str]:
    status: dict[str, str] = {}
    for raw in text.splitlines():
        if len(raw) < 4:
            continue
        kind = porcelain_kind(raw[0:2])
        if kind == "":
            continue
        rest = raw[3:]
        if rest.startswith('"') and rest.endswith('"') and len(rest) >= 2:
            rest = rest[1 : len(rest) - 1]
        path = rest
        arrow = rest.find(" -> ")
        if arrow >= 0:
            path = rest[arrow + 4 :]
            if path.startswith('"') and path.endswith('"') and len(path) >= 2:
                path = path[1 : len(path) - 1]
        previous = status.get(path, "")
        status[path] = merge_git_kind(previous, kind, False)
    return status


@nojs
def inherit_git_status(file_status: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path, kind in file_status.items():
        result[path] = merge_git_kind(result.get(path, ""), kind, False)
        parent = parent_dir(path)
        while parent != "":
            result[parent] = merge_git_kind(result.get(parent, ""), kind, True)
            parent = parent_dir(parent)
    return result


@nojs
def git_dir_path(start: Path | None = None) -> Path | None:
    root = start
    if root is None:
        root = workspace_root()
    git = git_root_from(root)
    if git is None:
        return None
    meta = git / ".git"
    if meta.is_dir():
        return meta
    return None


@nojs
def zepy_state_dir() -> Path:
    git_dir = git_dir_path()
    parent = git_dir if git_dir is not None else workspace_root()
    name = "zepy" if git_dir is not None else ".zepy"
    return parent / name


@nojs
def git_prefix() -> str:
    root = workspace_root()
    git = git_root_from(root)
    if git is None:
        return ""
    try:
        rel = root.relative_to(git)
    except ValueError:
        return ""
    text = str(rel).replace("\\", "/")
    if text == ".":
        return ""
    return text


@nojs
def to_workspace_path(git_path: str) -> str:
    prefix = git_prefix()
    if prefix == "":
        return git_path
    lead = prefix + "/"
    if git_path == prefix:
        return ""
    if git_path.startswith(lead):
        return git_path[len(lead) :]
    return git_path


@nojs
def to_git_path(relative: str) -> str:
    prefix = git_prefix()
    if prefix == "":
        return relative
    if relative == "" or relative == ".":
        return prefix
    return prefix + "/" + relative


@nojs
def remap_git_paths(status: dict[str, str]) -> dict[str, str]:
    prefix = git_prefix()
    remapped: dict[str, str] = {}
    for path, kind in status.items():
        if prefix != "" and path != prefix and not path.startswith(prefix + "/"):
            continue
        mapped = to_workspace_path(path)
        remapped[mapped] = merge_git_kind(remapped.get(mapped, ""), kind, False)
    return remapped


@nojs
def cheap_digest(text: str) -> str:
    n = 0
    index = 0
    while index < len(text):
        n = (n * 33 + ord(text[index])) & 0xFFFFFFFF
        index = index + 1
    return str(n)


@nojs
def git_watch_stamp() -> str:
    head = run_git(["rev-parse", "HEAD"]).strip()
    status = run_git(["status", "--porcelain"])
    mtime = 0
    git_dir = git_dir_path()
    if git_dir is not None:
        for name in ("HEAD", "index"):
            path = git_dir / name
            if path.is_file():
                try:
                    stamp = int(path.stat().st_mtime)
                except OSError:
                    stamp = 0
                mtime = max(mtime, stamp)
    return head + ":" + str(mtime) + ":" + cheap_digest(status)


@nojs
def git_file_status() -> dict[str, str]:
    return remap_git_paths(parse_status_porcelain(run_git(["status", "--porcelain", "-uall"])))


@nojs
def git_status_map() -> dict[str, str]:
    return inherit_git_status(git_file_status())


@nojs
def apply_git_status(entries: list[dict[str, object]], status: dict[str, str]) -> None:
    index = 0
    while index < len(entries):
        entry = entries[index]
        path = entry["path"]
        if isinstance(path, str):
            entry["git"] = status.get(path, "")
        index = index + 1


@nojs
def status_items(status: dict[str, str]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for path, kind in status.items():
        items.append({"path": path, "git": kind, "plus": 0, "minus": 0})
    return items


@nojs
def serve_git_status(request) -> Response:
    from zepy.server.review import git_changes_for_scope, git_numstat, normalize_scope

    scope = normalize_scope(request.query_value("scope"))
    ignore_ws = request.query_value("ws") == "1"
    files = git_changes_for_scope(scope)
    counts = git_numstat(scope, ignore_ws)
    changes: list[dict[str, object]] = []
    plus_all = 0
    minus_all = 0
    for path, kind in files.items():
        pair = counts.get(path, (0, 0))
        plus = pair[0]
        minus = pair[1]
        if kind == "untracked" and plus == 0:
            disk = safe_path(path)
            if disk is not None and disk.is_file():
                plus = len(read_text_file(disk).splitlines())
        plus_all = plus_all + plus
        minus_all = minus_all + minus
        changes.append({"path": path, "git": kind, "plus": plus, "minus": minus})
    return Response.json(
        {
            "scope": scope,
            "tree": status_items(inherit_git_status(files)),
            "changes": changes,
            "plus": plus_all,
            "minus": minus_all,
            "stamp": git_watch_stamp(),
        }
    )


@nojs
def serve_git(request) -> Response:
    relative = request.query_value("path")
    path = safe_path(relative)
    if path is None or not path.is_file():
        return Response.json({"path": relative, "gutter": [], "blame": []}, status=404)
    diff = run_git(["diff", "--no-color", "-U0", "--", relative])
    blame = run_git(["blame", "-p", "--", relative])
    return Response.json(
        {
            "path": relative,
            "gutter": parse_diff_gutter(diff),
            "blame": parse_blame(blame),
        }
    )
