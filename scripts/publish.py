"""Publish immutable desktop assets and retain versioned package indexes."""
import argparse
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def publish_assets(version: str, wheels: Path, publication: Path) -> None:
    tag = "v" + version
    repository = os.environ["GITHUB_REPOSITORY"]
    info = run("gh", "api", f"repos/{repository}/commits/{tag}", capture_output=True)
    if json.loads(info.stdout)["sha"] != os.environ["GITHUB_SHA"]:
        raise RuntimeError("Release tag does not match the tested commit")
    assets = publication / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for wheel in wheels.glob("*.whl"):
        shutil.copy2(wheel, assets / wheel.name)
        with zipfile.ZipFile(wheel) as archive:
            metadata = json.loads(archive.read("zepy/_desktop/runtime.json"))
            destination = assets / f"zepy-{version}-{metadata['target']}.tar.gz"
            with archive.open("zepy/_desktop/runtime.tar.gz") as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)
    for name in ("release.json", "SHA256SUMS"):
        shutil.copy2(publication / name, assets / name)
    for sdist in (publication / "pypi").glob("*.tar.gz"):
        shutil.copy2(sdist, assets / sdist.name)
    existing = subprocess.run(["gh", "release", "view", tag, "--repo", repository,
                               "--json", "isDraft"], capture_output=True, text=True, check=False)
    if existing.returncode == 0 and not json.loads(existing.stdout)["isDraft"]:
        manifest = run("gh", "release", "download", tag, "--repo", repository, "--pattern", "release.json",
                       "--output", "-", capture_output=True).stdout
        if json.loads(manifest) != json.loads((publication / "release.json").read_text()):
            raise RuntimeError("Published assets differ; refusing to replace an existing release")
        return
    if existing.returncode != 0:
        notes = publication / "release-notes.md"
        notes.write_text(
            f"Zepy {version}\n\nInstall with `uv tool install zepy=={version}` or `pip install zepy=={version}`, "
            "then run `zepy` in a project directory. PyPI installation becomes available when the publishing workflow completes.\n\n"
            "Desktop wheels and standalone archives are provided for Linux x64/ARM64, Windows x64, "
            "and macOS Intel/Apple Silicon. The wheels download during installation; launching needs no compiler or network.\n\n"
            "These early builds are not signed with a Windows publisher certificate or notarized by Apple. "
            "Linux requires working user namespaces or a configured Electron sandbox helper. "
            "See the desktop guide for platform requirements and the current feature limits.\n",
            encoding="utf-8",
        )
        run("gh", "release", "create", tag, "--repo", repository, "--verify-tag", "--draft",
            "--title", f"Zepy {version}", "--notes-file", str(notes))
    run("gh", "release", "upload", tag, "--repo", repository, "--clobber", *map(str, sorted(assets.iterdir())))
    run("gh", "release", "edit", tag, "--repo", repository, "--draft=false")


def prepare_site(version: str, publication: Path, site: Path) -> None:
    repository = os.environ["GITHUB_REPOSITORY"]
    remote = f"https://github.com/{repository}.git"
    exists = subprocess.run(["git", "ls-remote", "--exit-code", "--heads", remote, "gh-pages"],
                            capture_output=True, text=True, check=False)
    if exists.returncode == 0:
        run("git", "clone", "--depth", "1", "--branch", "gh-pages", remote, str(site))
    else:
        site.mkdir(parents=True)
        run("git", "init", "--initial-branch=gh-pages", str(site))
        run("git", "-C", str(site), "remote", "add", "origin", remote)
    destination = site / "releases" / version / "simple"
    if destination.exists():
        for source in (publication / "index").rglob("*"):
            if source.is_file() and (destination / source.relative_to(publication / "index")).read_bytes() != source.read_bytes():
                raise RuntimeError("Refusing to change an existing version's package index")
    else:
        shutil.copytree(publication / "index", destination)
    (site / ".nojekyll").touch()
    (site / "index.html").write_text('<!doctype html><a href="https://github.com/pyjs/zepy">Zepy source and releases</a>\n')
    run("git", "-C", str(site), "config", "user.name", "github-actions[bot]")
    run("git", "-C", str(site), "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    run("git", "-C", str(site), "add", ".")
    changed = subprocess.run(["git", "-C", str(site), "diff", "--cached", "--quiet"], check=False)
    if changed.returncode:
        run("git", "-C", str(site), "commit", "-m", f"Publish package index for {version}")
        run("gh", "auth", "setup-git")
        run("git", "-C", str(site), "push", "origin", "gh-pages")
    # The Git history stores prior indexes but is not part of the public Pages artifact.
    shutil.rmtree(site / ".git")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["assets", "site"])
    parser.add_argument("--version", required=True)
    parser.add_argument("--wheels", type=Path, default=Path("dist/wheels"))
    parser.add_argument("--publication", type=Path, default=Path("dist/publication"))
    parser.add_argument("--site", type=Path, default=Path("dist/site"))
    args = parser.parse_args()
    if args.command == "assets":
        publish_assets(args.version, args.wheels, args.publication)
    else:
        prepare_site(args.version, args.publication, args.site)


if __name__ == "__main__":
    main()
