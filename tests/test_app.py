import pytest
from pyjs import js
from pyjs.web.ssr import render_html

from zepy.app import App, main
from zepy.server.app import render


@pytest.mark.pyjs_python
@js
def test_app_hosts_a_gpu_canvas():
    app = App()

    assert app.stage.tagName == "CANVAS"
    assert app.stage.getAttribute("width") == "960"
    assert app.stage.getAttribute("height") == "640"
    assert app.input.tagName == "TEXTAREA"
    assert app.tree_list.getAttribute("data-testid") == "explorer"


@pytest.mark.pyjs_python
def test_main_returns_the_application():
    import zepy.app as app_module

    page = main()
    assert type(page).__name__ == "App"
    assert isinstance(page, app_module.App)


@pytest.mark.pyjs_python
def test_server_html_includes_workspace_files():
    page = render(None)
    html = render_html(page)
    assert 'data-testid="explorer"' in html
    assert 'data-testid="palette-input"' in html
    assert 'data-testid="search-input"' in html
    assert 'data-testid="quick-open-input"' in html
    assert "workspace/welcome.md" in html
    assert "workspace/hello.py" in html
    assert "Explorer" in html


@pytest.mark.pyjs_python
@js
def test_app_renders_explorer_files():
    app = App(
        '[{"name":"hello.py","path":"hello.py","kind":"file","depth":0,'
        '"content":"print(1)","git":""}]'
    )
    assert len(app.tree_list.children) == 1
    node = app.tree_list.children[0]
    assert node.getAttribute("data-path") == "hello.py"
