"""Launch the packaged desktop app without importing development dependencies."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from importlib.metadata import version
from pathlib import Path


def cache_root() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "zepy"


def runtime_executable(bundle: Path | None = None, cache: Path | None = None) -> Path:
    bundle = bundle or Path(__file__).parent / "_desktop"
    metadata_path = bundle / "runtime.json"
    if not metadata_path.is_file():
        root = Path(__file__).resolve().parents[1]
        names = {"win32": "electron.exe", "darwin": "Electron.app/Contents/MacOS/Electron"}
        executable = root / "dist/zepy" / names.get(sys.platform, "electron")
        if executable.is_file():
            return executable
        raise RuntimeError("Build the desktop app first; see the development instructions in README.md.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    digest = metadata["sha256"]
    destination = (cache or cache_root()) / (metadata["version"] + "-" + digest[:16])
    executable = destination / metadata["executable"]
    marker = destination / ".complete"
    if marker.is_file() and marker.read_text(encoding="utf-8") == digest and executable.is_file():
        return executable
    archive = bundle / "runtime.tar.gz"
    with archive.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != digest:
            raise RuntimeError("The desktop bundle checksum is invalid. Reinstall Zepy.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="install-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "runtime"
        staging.mkdir()
        with tarfile.open(archive) as source:
            source.extractall(staging, filter="data")
        if not (staging / metadata["executable"]).is_file():
            raise RuntimeError("The desktop bundle is missing its executable.")
        (staging / ".complete").write_text(digest, encoding="utf-8")
        try:
            staging.rename(destination)
        except OSError:
            if not (marker.is_file() and marker.read_text(encoding="utf-8") == digest
                    and executable.is_file()):
                raise
    return executable


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in ("serve", "review"):
        try:
            from zepy.server.cli import main as serve
        except ModuleNotFoundError as error:
            raise SystemExit("Browser development requires a source checkout and its dependencies.") from error
        serve()
        return
    parser = argparse.ArgumentParser(prog="zepy", description="Zepy Python IDE")
    parser.add_argument("workspace", nargs="?", default=None, help="Workspace directory (default: current directory)")
    parser.add_argument("--workspace", dest="workspace_option")
    parser.add_argument("--version", action="version", version="Zepy " + version("zepy"))
    parser.add_argument("--install-only", action="store_true", help="Prepare the local desktop runtime without launching")
    args, electron_args = parser.parse_known_args()
    workspace = Path(args.workspace_option or args.workspace or Path.cwd()).expanduser().resolve()
    if not workspace.is_dir():
        parser.error("The workspace must be a directory")
    try:
        executable = runtime_executable()
    except (OSError, ValueError, RuntimeError, tarfile.TarError) as error:
        raise SystemExit(str(error)) from error
    if args.install_only:
        print(executable)
        return
    environment = dict(os.environ)
    environment.pop("ELECTRON_RUN_AS_NODE", None)
    result = subprocess.run([str(executable), "--workspace=" + str(workspace), *electron_args],
                            env=environment, check=False)
    raise SystemExit(result.returncode)
