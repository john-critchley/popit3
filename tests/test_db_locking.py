import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager

import gdata
import pytest

import job_api


@contextmanager
def locked_temp_db():
    """Create a temporary gdbm database and hold a write lock with gdata.

    Yields the path to the database file while the lock is held. The lock is
    released as soon as the context exits in order to minimise interference
    with any real writers.
    """
    fd, path = tempfile.mkstemp(suffix=".gdbm")
    os.close(fd)

    # Create the DB and add a dummy record so read-only opens succeed when
    # the DB is not locked.
    db = gdata.gdata(path, mode="c")
    db["k"] = "v"
    db.close()

    writer = gdata.gdata(path, mode="w")
    try:
        yield path
    finally:
        writer.close()


# ---------------------------------------------------------------------------
# CLI locking behaviour
# ---------------------------------------------------------------------------


def test_cli_reports_locked_database(tmp_path):
    """CLI should return a JSON error when the DB is locked."""
    with locked_temp_db() as db_path:
        cmd = [
            sys.executable,
            "job_api.py",
            "--db-path",
            db_path,
            "--days",
            "1",
            "--min-score",
            "5",
        ]
        proc = subprocess.run(
            cmd,
            cwd=os.path.dirname(os.path.dirname(__file__)),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    # CLI should exit non-zero and emit JSON on stderr.
    assert proc.returncode == 1
    err = proc.stderr.strip()
    data = json.loads(err)
    assert data["status"] == "error"
    # Error message should indicate a locked DB via BlockingIOError re-raise.
    assert "Database locked" in data["error"]


# ---------------------------------------------------------------------------
# WSGI locking behaviour (reuses session-scoped wsgi_server fixture)
# ---------------------------------------------------------------------------


def test_wsgi_returns_503_when_db_locked(wsgi_server, monkeypatch):
    """WSGI interface should return 503 + locked payload when DB is locked."""
    with locked_temp_db() as db_path:
        monkeypatch.setenv("JOBSERVE_DBFILE", db_path)

        import urllib.request

        url = f"{wsgi_server}/jobs?days=1&min_score=5"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})

        with pytest.raises(Exception) as exc_info:
            # We expect an HTTPError for 503 from urllib
            urllib.request.urlopen(req, timeout=10)

        err = exc_info.value
        # urllib.error.HTTPError behaves like a file-like object; inspect code/body.
        resp = err
        assert getattr(resp, "code", None) == 503
        body = resp.read().decode("utf-8")
        data = json.loads(body)
        assert data["status"] == "locked"
        assert "Database locked" in data["error"]


# ---------------------------------------------------------------------------
# FastAPI locking behaviour (only if FastAPI is available)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not getattr(job_api, "HAS_FASTAPI", False), reason="FastAPI not available")
def test_fastapi_returns_503_when_db_locked(monkeypatch):
    from fastapi.testclient import TestClient

    app = job_api.app

    with locked_temp_db() as db_path:
        monkeypatch.setenv("JOBSERVE_DBFILE", db_path)
        client = TestClient(app)
        resp = client.get("/jobs", headers={"Accept": "application/json"})

    assert resp.status_code == 503
    assert resp.headers.get("Retry-After") == str(job_api.get_config_from_env()["refresh_timeout"])
    data = resp.json()
    assert data["status"] == "locked"
    assert "Database locked" in data["error"]
