"""Desktop package integrity, local extraction, and release metadata."""
import hashlib
import io
import json
import runpy
import tarfile
import zipfile
from pathlib import Path

import pytest

from zepy.launcher import runtime_executable

pytestmark = pytest.mark.pyjs_python
ROOT = Path(__file__).resolve().parents[1]


def release_tools():
    return runpy.run_path(str(ROOT / "scripts/release.py"))


def bundle(tmp_path, members=None):
    package = tmp_path / "package"
    package.mkdir()
    archive = package / "runtime.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        if members is None:
            info = tarfile.TarInfo("app")
            info.mode = 0o755
            info.size = 4
            tar.addfile(info, io.BytesIO(b"app\n"))
        else:
            for member, content in members:
                tar.addfile(member, io.BytesIO(content) if content is not None else None)
    (package / "runtime.json").write_text(json.dumps({"version": "0.1.0", "executable": "app",
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}))
    return package


def test_runtime_is_verified_and_cached_without_network(tmp_path):
    package = bundle(tmp_path)
    executable = runtime_executable(package, tmp_path / "cache")
    assert executable.read_bytes() == b"app\n"
    (package / "runtime.tar.gz").unlink()
    assert runtime_executable(package, tmp_path / "cache") == executable


def test_runtime_rejects_corrupt_archive_before_extraction(tmp_path):
    package = bundle(tmp_path)
    (package / "runtime.tar.gz").write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="checksum"):
        runtime_executable(package, tmp_path / "cache")
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize("symlink", [False, True])
def test_runtime_extraction_rejects_escaping_paths(tmp_path, symlink):
    info = tarfile.TarInfo("link" if symlink else "../../outside")
    content = b"escape"
    if symlink:
        info.type = tarfile.SYMTYPE
        info.linkname = "../../outside"
        content = None
    else:
        info.size = len(content)
    package = bundle(tmp_path, [(info, content)])
    with pytest.raises(tarfile.FilterError):
        runtime_executable(package, tmp_path / "cache")
    assert not (tmp_path / "outside").exists()


def test_desktop_wheel_and_stub_share_dependency_free_metadata(tmp_path):
    pytest.importorskip("wheel_stub")
    tools = release_tools()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "app").write_bytes(b"app\n")
    wheel = tools["build_wheel"](runtime, tmp_path / "wheels", "linux-x64", "app")
    output = tmp_path / "publication"
    stub = tools["assemble"]([wheel], output, "https://example.invalid/simple/",
                              "https://github.com/pyjs/zepy/releases/download/v0.1.0/")
    with zipfile.ZipFile(wheel) as archive:
        metadata = archive.read("zepy-0.1.0.dist-info/METADATA").decode()
        assert "Requires-Dist:" not in metadata
        assert "License-File: LICENSE" in metadata
        assert "zepy/_desktop/runtime.tar.gz" in archive.namelist()
        assert "zepy/app.py" not in archive.namelist()
        assert "from .app" not in archive.read("zepy/__init__.py").decode()
    with tarfile.open(stub) as archive:
        names = {member.name for member in archive if member.isfile()}
        assert names == {"zepy-0.1.0/PKG-INFO", "zepy-0.1.0/pyproject.toml",
                         "zepy-0.1.0/LICENSE", "zepy-0.1.0/THIRD_PARTY_NOTICES.md"}
        assert "Requires-Dist:" not in archive.extractfile("zepy-0.1.0/PKG-INFO").read().decode()
    index = (output / "index/zepy/index.html").read_text()
    assert "#sha256=" + tools["sha256"](wheel) in index
    manifest = json.loads((output / "release.json").read_text())
    assert manifest["wheels"][0]["size"] == wheel.stat().st_size
