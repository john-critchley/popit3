"""Tests for the module-level API functions (get_jobs_data, get_jobs_output)."""
import json

import pytest
import yaml

import job_api


# ---------------------------------------------------------------------------
# get_jobs_data tests
# ---------------------------------------------------------------------------


def test_get_jobs_data_returns_dict():
    """get_jobs_data should return a dict with status, count, jobs keys."""
    data = job_api.get_jobs_data()
    assert isinstance(data, dict)
    assert data['status'] == 'ok'
    assert isinstance(data['count'], int)
    assert isinstance(data['jobs'], list)


def test_get_jobs_data_count_matches_jobs_length():
    """count should equal len(jobs)."""
    data = job_api.get_jobs_data()
    assert data['count'] == len(data['jobs'])


def test_get_jobs_data_respects_min_score():
    """High min_score should filter out all jobs."""
    data = job_api.get_jobs_data(min_score=99999)
    assert data['count'] == 0
    assert data['jobs'] == []


def test_get_jobs_data_raises_on_locked_db(monkeypatch):
    """Should raise BlockingIOError when DB is locked."""
    def fake_load_and_extract(*args, **kwargs):
        raise BlockingIOError('Database locked')
    
    monkeypatch.setattr(job_api, 'load_and_extract_jobs', fake_load_and_extract)
    
    with pytest.raises(BlockingIOError):
        job_api.get_jobs_data()


def test_get_jobs_data_includes_score_reason():
    """get_jobs_data should include the score_reason field in job records."""
    data = job_api.get_jobs_data()
    for job in data['jobs']:
        assert 'score_reason' in job


# ---------------------------------------------------------------------------
# get_jobs_output tests
# ---------------------------------------------------------------------------


def test_get_jobs_output_json():
    """JSON output should be valid JSON with expected structure."""
    output = job_api.get_jobs_output(format='json')
    data = json.loads(output)
    assert data['status'] == 'ok'
    assert isinstance(data['count'], int)
    assert isinstance(data['jobs'], list)


def test_get_jobs_output_json_includes_score_reason():
    """JSON output should include the score_reason field."""
    output = job_api.get_jobs_output(format='json')
    data = json.loads(output)
    for job in data['jobs']:
        assert 'score_reason' in job


def test_get_jobs_output_csv():
    """CSV output should have header line with known fields."""
    output = job_api.get_jobs_output(format='csv')
    lines = output.strip().split('\n')
    # Either header with fields or status line for empty
    assert len(lines) >= 1
    first_line = lines[0].lower()
    assert 'score' in first_line or 'status' in first_line


def test_get_jobs_output_yaml():
    """YAML output should be valid YAML with expected structure."""
    output = job_api.get_jobs_output(format='yaml')
    data = yaml.safe_load(output)
    assert data['status'] == 'ok'
    assert isinstance(data['count'], int)
    assert isinstance(data['jobs'], list)


def test_get_jobs_output_yaml_includes_score_reason():
    """YAML output should include the score_reason field."""
    output = job_api.get_jobs_output(format='yaml')
    data = yaml.safe_load(output)
    for job in data['jobs']:
        assert 'score_reason' in job


def test_get_jobs_output_xml():
    """XML output should contain expected elements."""
    output = job_api.get_jobs_output(format='xml')
    assert '<response>' in output
    assert '<status>ok</status>' in output
    assert '<count>' in output
    assert '<jobs>' in output


def test_get_jobs_output_xml_includes_score_reason():
    """XML output should include the score_reason field."""
    output = job_api.get_jobs_output(format='xml')
    assert '<score_reason>' in output


def test_get_jobs_output_unknown_format_defaults_to_json():
    """Unknown format should default to JSON."""
    output = job_api.get_jobs_output(format='unknown')
    data = json.loads(output)
    assert data['status'] == 'ok'


def test_get_jobs_output_empty_with_high_min_score():
    """High min_score should return valid empty structure."""
    output = job_api.get_jobs_output(min_score=99999, format='json')
    data = json.loads(output)
    assert data['status'] == 'ok'
    assert data['count'] == 0
    assert data['jobs'] == []


def test_get_jobs_output_raises_on_locked_db(monkeypatch):
    """Should raise BlockingIOError when DB is locked."""
    def fake_get_jobs_data(*args, **kwargs):
        raise BlockingIOError('Database locked')
    
    monkeypatch.setattr(job_api, 'get_jobs_data', fake_get_jobs_data)
    
    with pytest.raises(BlockingIOError):
        job_api.get_jobs_output(format='json')


# ---------------------------------------------------------------------------
# Verify internal reuse
# ---------------------------------------------------------------------------


def test_build_success_payload_uses_get_jobs_data(monkeypatch):
    """build_success_payload should internally use get_jobs_data."""
    called = {}
    
    original_get_jobs_data = job_api.get_jobs_data
    
    def tracking_get_jobs_data(*args, **kwargs):
        called['get_jobs_data'] = (args, kwargs)
        return original_get_jobs_data(*args, **kwargs)
    
    monkeypatch.setattr(job_api, 'get_jobs_data', tracking_get_jobs_data)
    
    job_api.build_success_payload('~/.jobserve.gdbm', 7, 5, 'application/json')
    
    assert 'get_jobs_data' in called
