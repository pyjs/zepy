"""HTTP application for browser development."""

import asyncio
import json

from zepy.app import main
from zepy.server.chat import serve_chat_history, serve_chat_send
from zepy.server.review import (
    serve_git_diff,
    serve_review,
    serve_review_comment,
    serve_review_viewed,
)
from zepy.server.workspace import (
    list_workspace,
    serve_file,
    serve_git,
    serve_git_status,
    serve_save,
    serve_search,
    serve_tree,
)


def render(request):
    return main(json.dumps(asyncio.run(list_workspace()), separators=(",", ":")))


ROUTES = {
    ("GET", "/api/tree"): serve_tree,
    ("GET", "/api/file"): serve_file,
    ("POST", "/api/file"): serve_save,
    ("GET", "/api/search"): serve_search,
    ("GET", "/api/git"): serve_git,
    ("GET", "/api/git-status"): serve_git_status,
    ("GET", "/api/git-diff"): serve_git_diff,
    ("GET", "/api/review"): serve_review,
    ("POST", "/api/review/viewed"): serve_review_viewed,
    ("POST", "/api/review/comment"): serve_review_comment,
    ("GET", "/api/chat"): serve_chat_history,
    ("POST", "/api/chat"): serve_chat_send,
}


def create_workbench_server(*, port: int = 8000):
    from pyjs.server.dev import create_server

    from zepy.services.workspace import MAX_FILE_BYTES

    server = create_server(__name__, render=render, routes=ROUTES, port=port)
    # JSON escaping can expand one text byte to six bytes in the HTTP body.
    server.application.body_limit = MAX_FILE_BYTES * 6 + 64 * 1024
    return server
