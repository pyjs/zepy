"""Build desktop wheels and the small PyPI source archive from tested runtimes."""
from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import html
import io
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from email.parser import BytesParser
from importlib.metadata import distribution
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
VERSION = PROJECT["version"]
TARGETS = {
    "linux-x64": "linux_x86_64", "linux-arm64": "linux_aarch64",
    "windows-x64": "win_amd64", "macos-x64": "macosx_12_0_x86_64",
    "macos-arm64": "macosx_12_0_arm64",
}


def target_name() -> str:
    system = {"Linux": "linux", "Windows": "windows", "Darwin": "macos"}[platform.system()]
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64" if machine in ("amd64", "x86_64") else ""
    target = system + "-" + arch
    if target not in TARGETS:
        raise ValueError(f"Unsupported desktop platform: {platform.system()} {machine}")
    return target


def sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def metadata() -> str:
    return (f"Metadata-Version: 2.4\nName: zepy\nVersion: {VERSION}\n"
            f"Summary: {PROJECT['description']}\nRequires-Python: {PROJECT['requires-python']}\n"
            "License-Expression: MIT\nLicense-File: LICENSE\nLicense-File: THIRD_PARTY_NOTICES.md\n"
            "Project-URL: Homepage, https://github.com/pyjs/zepy\n"
            "Description-Content-Type: text/markdown\n\n" + (ROOT / "README.md").read_text())


def prepare_runtime(runtime: Path) -> str:
    system = platform.system()
    if system == "Darwin":
        app = runtime / "Electron.app"
        plist = app / "Contents/Info.plist"
        with plist.open("rb") as file:
            info = plistlib.load(file)
        minimum = info.get("LSMinimumSystemVersion", "12.0").split(".")
        arch = "arm64" if target_name().endswith("arm64") else "x86_64"
        TARGETS[target_name()] = f"macosx_{minimum[0]}_{minimum[1] if len(minimum) > 1 else '0'}_{arch}"
        info.update(CFBundleName="Zepy", CFBundleDisplayName="Zepy", CFBundleIdentifier="dev.zepy.app",
                    CFBundleShortVersionString=VERSION, CFBundleVersion=VERSION)
        with plist.open("wb") as file:
            plistlib.dump(info, file)
        app.rename(runtime / "Zepy.app")
        resources = runtime / "Zepy.app/Contents/Resources/app"
        executable = "Zepy.app/Contents/MacOS/Electron"
    else:
        source = "electron.exe" if system == "Windows" else "electron"
        executable = "zepy.exe" if system == "Windows" else "zepy"
        (runtime / source).rename(runtime / executable)
        resources = runtime / "resources/app"
    manifest = resources / "package.json"
    info = json.loads(manifest.read_text())
    info.update(name="zepy", productName="Zepy", version=VERSION)
    manifest.write_text(json.dumps(info, indent=2) + "\n")
    for path in resources.rglob("*.map"):
        source_map = json.loads(path.read_text(encoding="utf-8"))
        sources = []
        for source in source_map.get("sources", []):
            candidate = Path(source)
            try:
                source = candidate.relative_to(ROOT).as_posix()
            except ValueError:
                parts = candidate.parts
                if "pyjs" in parts:
                    source = "_dependencies/" + "/".join(parts[parts.index("pyjs"):])
                elif candidate.is_absolute():
                    source = "_dependencies/" + candidate.name
            sources.append(source.replace("\\", "/"))
        source_map["sources"] = sources
        path.write_text(json.dumps(source_map, separators=(",", ":")), encoding="utf-8")
    licenses = runtime / "licenses/zepy"
    licenses.mkdir(parents=True)
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, licenses / name)
    dependency = distribution("pyjs")
    for file in dependency.files or []:
        if str(file).endswith(".dist-info/licenses/LICENSE"):
            license_path = runtime / "licenses/pyjs/LICENSE"
            license_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dependency.locate_file(file), license_path)
    if system == "Darwin":
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(runtime / "Zepy.app")], check=True)
    return executable


def build_wheel(runtime: Path, output: Path, target: str, executable: str) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"zepy-{VERSION}-{target}.tar.gz"
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "1767225600"))
    def normalize(member):
        member.uid = member.gid = 0
        member.uname = member.gname = ""
        member.mtime = epoch
        return member
    with (archive.open("wb") as raw,
          gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=epoch) as compressed,
          tarfile.open(fileobj=compressed, mode="w") as tar):
        for item in sorted(runtime.iterdir()):
            tar.add(item, arcname=item.name, filter=normalize)
    wheel = output / f"zepy-{VERSION}-py3-none-{TARGETS[target]}.whl"
    info = f"zepy-{VERSION}.dist-info"
    records = []
    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as package:
        def add(name: str, content: bytes, compression=zipfile.ZIP_DEFLATED):
            member = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            member.external_attr = 0o100644 << 16
            package.writestr(member, content, compress_type=compression)
            digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
            records.append((name, "sha256=" + digest, len(content)))
        for name in ("__init__.py", "__main__.py", "launcher.py"):
            add("zepy/" + name, (ROOT / "zepy" / name).read_bytes())
        add("zepy/_desktop/runtime.tar.gz", archive.read_bytes(), zipfile.ZIP_STORED)
        add("zepy/_desktop/runtime.json", json.dumps({"version": VERSION, "target": target,
            "executable": executable, "sha256": sha256(archive)}).encode())
        add(info + "/METADATA", metadata().encode())
        add(info + "/WHEEL", f"Wheel-Version: 1.0\nGenerator: zepy\nRoot-Is-Purelib: false\nTag: py3-none-{TARGETS[target]}\n".encode())
        add(info + "/entry_points.txt", b"[console_scripts]\nzepy = zepy.__main__:main\n")
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            add(info + "/licenses/" + name, (ROOT / name).read_bytes())
        record = io.StringIO(newline="")
        csv.writer(record).writerows([*records, (info + "/RECORD", "", "")])
        package.writestr(zipfile.ZipInfo(info + "/RECORD", (2026, 1, 1, 0, 0, 0)), record.getvalue())
    return wheel


def build(output: Path, runtime: Path) -> None:
    subprocess.run([sys.executable, "-m", "pyjs", "build", "zepy.app", "--target", "electron",
                    "--electron-host", "zepy/desktop/host", "-o", str(runtime)], cwd=ROOT, check=True)
    executable = prepare_runtime(runtime)
    wheel = build_wheel(runtime, output, target_name(), executable)
    print(wheel)


def assemble(wheels: list[Path], output: Path, index_url: str, release_url: str) -> Path:
    from wheel_stub.buildapi import build_sdist

    if not wheels:
        raise ValueError("No desktop wheels were provided")
    entries = []
    expected_metadata = None
    for wheel in sorted(wheels):
        with zipfile.ZipFile(wheel) as archive:
            raw = archive.read(f"zepy-{VERSION}.dist-info/METADATA")
            parsed = BytesParser().parsebytes(raw)
            if parsed["Name"] != "zepy" or parsed["Version"] != VERSION or parsed.get_all("Requires-Dist"):
                raise ValueError("Desktop wheel metadata does not match this dependency-free release")
            if expected_metadata is not None and raw != expected_metadata:
                raise ValueError("Platform wheels have different metadata")
            expected_metadata = raw
        entries.append({"filename": wheel.name, "sha256": sha256(wheel), "size": wheel.stat().st_size,
                        "url": release_url.rstrip("/") + "/" + wheel.name})
    output = output.resolve()
    index = output / "index/zepy"
    index.mkdir(parents=True, exist_ok=True)
    links = [f'<a href="{html.escape(item["url"])}#sha256={item["sha256"]}">{html.escape(item["filename"])}</a>'
             for item in entries]
    (index / "index.html").write_text('<!doctype html><html><body>\n' + '<br>\n'.join(links) + '\n</body></html>\n')
    (output / "index/index.html").write_text('<!doctype html><a href="zepy/">zepy</a>\n')
    (output / "release.json").write_text(json.dumps({"version": VERSION, "wheels": entries}, indent=2) + "\n")
    (output / "SHA256SUMS").write_text("".join(f'{entry["sha256"]}  {entry["filename"]}\n' for entry in entries))
    with tempfile.TemporaryDirectory(prefix="zepy-stub-") as temporary:
        project = Path(temporary)
        (project / "pyproject.toml").write_text(
            '[build-system]\nrequires = ["wheel-stub==0.5.0"]\nbuild-backend = "wheel_stub.buildapi"\n\n'
            '[tool.wheel_stub]\nindex_url = ' + json.dumps(index_url.rstrip("/") + "/") + '\n'
        )
        previous = Path.cwd()
        try:
            os.chdir(project)
            name = build_sdist(str(output / "pypi"), {"source_wheel": str(wheels[0].resolve())})
        finally:
            os.chdir(previous)
    # The upstream stub carries metadata; include the referenced license files too.
    sdist = output / "pypi" / name
    with tarfile.open(sdist) as tar:
        content = [(member, tar.extractfile(member).read() if member.isfile() else None) for member in tar]
    with tarfile.open(sdist, "w:gz") as tar:
        for member, data in content:
            member.name = member.name.replace("\\", "/")
            tar.addfile(member, io.BytesIO(data) if data is not None else None)
        for filename in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            tar.add(ROOT / filename, arcname=f"zepy-{VERSION}/" + filename)
    return sdist


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--output", type=Path, default=Path("dist/release"))
    build_parser.add_argument("--runtime", type=Path, default=Path("dist/release-runtime"))
    assemble_parser = sub.add_parser("assemble")
    assemble_parser.add_argument("--wheels", type=Path, required=True)
    assemble_parser.add_argument("--output", type=Path, default=Path("dist/publication"))
    assemble_parser.add_argument("--require-all", action="store_true")
    assemble_parser.add_argument("--index-url", required=True)
    assemble_parser.add_argument("--release-url", required=True)
    sub.add_parser("version")
    args = parser.parse_args()
    if args.command == "version":
        print(VERSION)
    elif args.command == "build":
        build(args.output.resolve(), args.runtime.resolve())
    else:
        wheels = list(args.wheels.resolve().glob("*.whl"))
        if args.require_all:
            targets = []
            for wheel in wheels:
                with zipfile.ZipFile(wheel) as archive:
                    targets.append(json.loads(archive.read("zepy/_desktop/runtime.json"))["target"])
            if sorted(targets) != sorted(TARGETS):
                raise ValueError("Release requires exactly one wheel for every supported platform")
        print(assemble(wheels, args.output, args.index_url, args.release_url))


if __name__ == "__main__":
    main()
