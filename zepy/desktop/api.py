"""Electron renderer transport and runtime detection."""
from pyjs import js
from pyjs.web.network import Response


@js.inline("Boolean(globalThis.zepyDesktop)")
def is_desktop() -> bool:
    return False


@js
async def fetch(url: str, options: object | None = None) -> Response: ...


@fetch.inline
def fetch(_arg_strs, **kwargs):
    url = _arg_strs[0]
    options = _arg_strs[1] if len(_arg_strs) > 1 else "undefined"
    return (
        "((url, options) => {"
        "options = options instanceof Map ? Object.fromEntries(options) : options;"
        "return globalThis.zepyDesktop ? globalThis.zepyDesktop.request(url, options)"
        ".then(result => new Response(result.body, {status: result.status}))"
        ": fetch(url, options);"
        f"}})({url}, {options})"
    )


@js.inline("globalThis.zepyDesktop.workspace({operation}, {arguments}).then(result => new Response(result.body, {{status: result.status}}))")
async def workspace_request(operation: str, arguments: object) -> Response: ...
