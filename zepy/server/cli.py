from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from zepy.server.app import create_workbench_server
from zepy.server.workspace import git_dir_path, workspace_root


def port_file(root: Path) -> Path:
    git_dir = git_dir_path(root)
    if git_dir is not None:
        return git_dir / "zepy.port"
    digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[0:12]
    return Path("/tmp") / ("zepy-" + digest + ".port")


def live_port(root: Path) -> int:
    path = port_file(root)
    if not path.is_file():
        return 0
    try:
        port = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0
    try:
        urlopen("http://127.0.0.1:" + str(port) + "/", timeout=0.4)
    except (URLError, OSError, TimeoutError):
        return 0
    return port


def write_port(root: Path, port: int) -> None:
    path = port_file(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(port) + "\n", encoding="utf-8")
    except OSError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(prog="zepy", description="Zepy review workbench")
    parser.add_argument("command", nargs="?", default="serve")
    parser.add_argument("--unpushed", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    root = workspace_root()
    port = live_port(root)
    query = ""
    if args.command == "review":
        query = "?review=dirty"
        if args.unpushed:
            query = "?review=unpushed"
    if port > 0:
        print("Zepy is already running at http://127.0.0.1:" + str(port) + "/" + query)
        return
    write_port(root, args.port)
    if query != "":
        print("Open http://127.0.0.1:" + str(args.port) + "/" + query)
    server = create_workbench_server(port=args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.close()
        path = port_file(root)
        try:
            path.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
