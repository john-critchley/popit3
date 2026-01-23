import threading
import time
from wsgiref.simple_server import make_server

import pytest

from job_api import application


@pytest.fixture(scope="session")
def wsgi_server():
    """Session-scoped WSGI server for tests that need the HTTP interface.

    Starts a wsgiref-based HTTP server in a background thread before the
    first test that uses this fixture, and shuts it down after the last
    such test has finished.

    Tests that do not depend on this fixture will not start the server.
    """

    host = "127.0.0.1"
    port = 8051

    httpd = make_server(host, port, application)

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    # Give the server a brief moment to start listening
    time.sleep(0.2)

    base_url = f"http://{host}:{port}"
    try:
        yield base_url
    finally:
        # Gracefully stop the server after all dependent tests complete
        httpd.shutdown()
        thread.join(timeout=2)
