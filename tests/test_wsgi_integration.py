import json
import urllib.request


def _get(url: str, accept: str) -> tuple[int, dict, str]:
    req = urllib.request.Request(url, headers={"Accept": accept})
    with urllib.request.urlopen(req, timeout=10) as resp:
        status = resp.getcode()
        headers = dict(resp.getheaders())
        body = resp.read().decode("utf-8")
    return status, headers, body


def test_wsgi_jobs_json_ok(wsgi_server):
    url = f"{wsgi_server}/jobs?days=1&min_score=5"
    status, headers, body = _get(url, "application/json")

    assert status == 200
    assert headers["Content-Type"].startswith("application/json")

    data = json.loads(body)
    assert data["status"] == "ok"
    assert isinstance(data["count"], int)
    assert isinstance(data["jobs"], list)


def test_wsgi_jobs_csv_ok(wsgi_server):
    url = f"{wsgi_server}/jobs?days=1&min_score=5"
    status, headers, body = _get(url, "text/csv")

    assert status == 200
    assert headers["Content-Type"].startswith("text/csv")

    # Basic CSV sanity: header line and at least one data line
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert lines[0].startswith("score,reference,job_title,")
    assert len(lines) >= 1
