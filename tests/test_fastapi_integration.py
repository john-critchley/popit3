"""FastAPI success path tests (skip if FastAPI not available)."""
import json

import pytest

import job_api


pytestmark = pytest.mark.skipif(
    not getattr(job_api, 'HAS_FASTAPI', False),
    reason='FastAPI not available',
)


@pytest.fixture(scope='module')
def client():
    from fastapi.testclient import TestClient
    return TestClient(job_api.app)


def test_fastapi_jobs_json_success(client):
    resp = client.get('/jobs?days=7&min_score=5', headers={'Accept': 'application/json'})
    assert resp.status_code == 200
    assert resp.headers['content-type'].startswith('application/json')
    data = resp.json()
    assert data['status'] == 'ok'
    assert isinstance(data['count'], int)
    assert isinstance(data['jobs'], list)


def test_fastapi_jobs_csv_success(client):
    resp = client.get('/jobs?days=7&min_score=5', headers={'Accept': 'text/csv'})
    assert resp.status_code == 200
    assert resp.headers['content-type'].startswith('text/csv')
    body = resp.text
    # Header line should include known fields
    assert 'score' in body
    assert 'job_title' in body


def test_fastapi_jobs_yaml_success(client):
    resp = client.get('/jobs?days=7&min_score=5', headers={'Accept': 'application/yaml'})
    assert resp.status_code == 200
    assert 'yaml' in resp.headers['content-type']
    import yaml
    data = yaml.safe_load(resp.text)
    assert data['status'] == 'ok'


def test_fastapi_jobs_xml_success(client):
    resp = client.get('/jobs?days=7&min_score=5', headers={'Accept': 'application/xml'})
    assert resp.status_code == 200
    assert 'xml' in resp.headers['content-type']
    assert '<response>' in resp.text
    assert '<status>ok</status>' in resp.text


def test_fastapi_health(client):
    resp = client.get('/health')
    assert resp.status_code == 200
    data = resp.json()
    assert data['status'] == 'ok'
    assert data['api'] == 'job_api'
