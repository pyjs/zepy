"""Build Node fixtures before tests; generated JavaScript stays outside Git."""
import importlib.util
import os
import sys
from pathlib import Path

import pytest
from pyjs.tooling.node_build import build_node


@pytest.fixture(scope="session", autouse=True)
def compiled_host_fixtures():
    from zepy.desktop.host.codex import main

    root = Path(__file__).resolve().parents[1]
    build_node(main, root / ".pyjs/desktop/codex.cjs")
    source = root / "tests/fixtures/codex_cli.py"
    name = "_zepy_codex_fixture"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    previous_module = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        fixture = build_node(module.main, root / ".pyjs/test-fixtures/codex_cli.cjs")
    finally:
        if previous_module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous_module
    key = "ZEPY_TEST_CODEX_FIXTURE"
    previous = os.environ.get(key)
    os.environ[key] = str(fixture)
    yield
    if previous is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = previous
