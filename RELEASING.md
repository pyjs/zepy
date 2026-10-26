# Releases

CI runs Python, compiled Node, and managed-browser tests. It builds desktop
wheels on Linux x64/ARM64, Windows x64, and macOS Intel/Apple Silicon, then
installs each wheel without development dependencies and tests the installed
app's explorer, source scrolling, Codex protocol fixture, and Python debugger.
The Linux browser job retains a composited WebGPU screenshot for visual review.

## Publish a version

1. Update `project.version` in `pyproject.toml`, refresh `uv.lock`, and commit.
2. Wait for the main branch's **All checks passed** check and review the artifacts.
3. Tag that commit with the matching version and push the tag:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

The tag workflow runs the full CI matrix again and publishes those tested
wheels without rebuilding them. It creates a GitHub release with desktop wheels,
standalone archives, a checksum manifest, and the small PyPI source archive.
It then deploys the versioned wheel index to GitHub Pages and publishes to PyPI.
The final job verifies a clean installation from public PyPI.

`publish.yml` can also be dispatched against an existing version tag. Re-run
failed jobs to reuse the tested artifacts. Published release assets and versioned
indexes cannot be changed to different contents; publish a new version instead.

## Distribution layout

The PyPI source archive uses `wheel-stub==0.5.0`. Its metadata comes from the
platform wheels, and its index links include SHA-256 checksums. The complete
Electron payload downloads during installation, avoiding PyPI's per-file size
limit. The app starts without network access or compilation. The launcher
checks the embedded archive before extracting it into a versioned user cache.

The `gh-pages` branch stores indexes for all released versions. The Pages
workflow deploys that content, retaining old versions so older PyPI installs
continue working. This branch is package-index data, separate from application
source. Repository Pages must use GitHub Actions as its build source.

Application and dependency licenses ship inside the desktop archive. Electron's
own license and Chromium notices are retained alongside Zepy's MIT notices and
PyJS's BSD license. Release bundles use portable Python source-map paths.

## Publishing configuration

GitHub release jobs use the workflow's repository token. PyPI publication runs
in the `pypi` environment, restricted to version tags. It can use the environment's
`PYPI_API_TOKEN` secret or PyPI Trusted Publishing for repository `pyjs/zepy`,
workflow `publish.yml`, environment `pypi`. Remove the secret when switching to
Trusted Publishing; enable attestations in that workflow at the same time.

The `github-pages` environment must also allow version tags. Signing and Apple
notarization credentials are not configured; the first releases explicitly
identify that limitation. Normal application launches retain Electron sandboxing.

## Local packaging checks

```bash
uv sync --locked --extra test --group release
uv run --locked --extra test --group release python scripts/release.py build
uv run --locked --extra test --group release python scripts/check_install.py dist/release/*.whl
uv run --locked --extra test --group release pytest -q tests/test_release.py
```

Use a fresh runtime output directory when rebuilding (`--runtime PATH`).
`python scripts/release.py assemble --help` describes index/stub generation.
The root project's ordinary source wheel is for development; only the generated
stub under `dist/publication/pypi/` is uploaded to PyPI.
