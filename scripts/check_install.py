"""Install a release wheel in isolation and expose its prepared desktop executable."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--environment", type=Path, default=Path(".local/installed-release"))
    args = parser.parse_args()
    directory = args.environment.resolve()
    subprocess.run(["uv", "venv", str(directory), "--python", sys.executable], check=True)
    python = directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(["uv", "pip", "install", "--python", str(python), "--no-deps", str(args.wheel.resolve())], check=True)
    with tempfile.TemporaryDirectory(prefix="zepy-install-check-") as temporary:
        subprocess.run([str(python), "-c",
            "import importlib.util; assert importlib.util.find_spec('pyjs') is None; import zepy.launcher"],
            cwd=temporary, check=True)
        subprocess.run([str(python), "-m", "zepy", "--version"], cwd=temporary, check=True)
        executable = subprocess.check_output([str(python), "-m", "zepy", "--install-only"],
                                             cwd=temporary, text=True, encoding="utf-8").strip()
    assert Path(executable).is_file(), executable
    if os.environ.get("GITHUB_ENV"):
        with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as env:
            env.write("ZEPY_ELECTRON_BIN=" + executable + "\n")
    print(json.dumps({"python": str(python), "executable": executable}))


if __name__ == "__main__":
    main()
