import job_api


def test_cli_format_map_values():
    assert job_api.CLI_FORMAT_MAP['json'] == 'application/json'
    assert job_api.CLI_FORMAT_MAP['csv'] == 'text/csv'
    assert job_api.CLI_FORMAT_MAP['yaml'] == 'application/yaml'
    assert job_api.CLI_FORMAT_MAP['xml'] == 'application/xml'


def test_format_output_default_to_json():
    # Requesting an unknown content type should fall back to JSON mime
    out, mime = job_api.format_output([], 'nonexistent/type')
    assert mime.startswith('application/json')


def test_format_output_csv_mime():
    out, mime = job_api.format_output([], 'text/csv')
    assert 'text/csv' in mime


def test_get_content_type_recognises_formats():
    assert job_api.get_content_type('text/csv') == 'text/csv'
    assert job_api.get_content_type('application/x-yaml') == 'application/yaml'
    assert job_api.get_content_type('application/yaml') == 'application/yaml'
    assert job_api.get_content_type('application/xml') == 'application/xml'
    assert job_api.get_content_type('text/xml') == 'application/xml'


def test_get_content_type_defaults_to_json():
    assert job_api.get_content_type('') == 'application/json'
    # Unrecognised Accept header should still default to JSON
    assert job_api.get_content_type('text/html') == 'application/json'


# ---------------------------------------------------------------------------
# Helpers: success and locked-error payloads
# ---------------------------------------------------------------------------


def test_format_locked_error_response_json():
    body, ctype, headers = job_api.format_locked_error_response('application/json', 10, url='/jobs')
    assert 'locked' in body
    assert 'retry in 10s' in body
    assert ctype.startswith('application/json')
    assert headers['Refresh'].startswith('10; url=/jobs')
    assert headers['Retry-After'] == '10'


def test_format_locked_error_response_csv():
    body, ctype, headers = job_api.format_locked_error_response('text/csv', 5, url='/foo')
    assert 'status,error' in body
    assert 'locked,Database locked - retry in 5s' in body
    assert 'text/csv' in ctype
    assert headers['Refresh'] == '5; url=/foo'
    assert headers['Retry-After'] == '5'


def test_build_success_payload_uses_helpers(monkeypatch):
    calls = {}

    def fake_load_and_extract(db_path, days, min_score):
        calls['load_and_extract'] = (db_path, days, min_score)
        return [{'k': 'v'}]

    def fake_get_content_type(header):
        calls['accept'] = header
        return 'text/csv'

    def fake_format_output(jobs, content_type):
        calls['format_args'] = (list(jobs), content_type)
        return 'OUT', 'text/csv; charset=utf-8'

    monkeypatch.setattr(job_api, 'load_and_extract_jobs', fake_load_and_extract)
    monkeypatch.setattr(job_api, 'get_content_type', fake_get_content_type)
    monkeypatch.setattr(job_api, 'format_output', fake_format_output)

    output, ctype = job_api.build_success_payload('dbfile', 7, 5, 'Accept: text/csv')

    assert output == 'OUT'
    assert ctype == 'text/csv; charset=utf-8'
    assert calls['load_and_extract'] == ('dbfile', 7, 5)
    assert calls['accept'] == 'Accept: text/csv'
    assert calls['format_args'] == ([{'k': 'v'}], 'text/csv')


# ---------------------------------------------------------------------------
# format_output: YAML and XML
# ---------------------------------------------------------------------------


def test_format_output_yaml_mime():
    out, mime = job_api.format_output([], 'application/yaml')
    assert 'application/yaml' in mime
    # YAML output should be parseable and contain expected keys
    import yaml
    data = yaml.safe_load(out)
    assert data['status'] == 'ok'
    assert data['count'] == 0
    assert data['jobs'] == []


def test_format_output_xml_structure():
    jobs = [{'message_id': 'test', 'score': 10}]
    out, mime = job_api.format_output(jobs, 'application/xml')
    assert 'application/xml' in mime
    # Basic XML structure checks
    assert '<response>' in out
    assert '<status>ok</status>' in out
    assert '<count>1</count>' in out
    assert '<job>' in out
    assert '<score>10</score>' in out


# ---------------------------------------------------------------------------
# format_locked_error_response: YAML and XML
# ---------------------------------------------------------------------------


def test_format_locked_error_response_yaml():
    body, ctype, headers = job_api.format_locked_error_response('application/yaml', 8, url='/test')
    assert 'application/yaml' in ctype
    assert 'status: locked' in body
    assert 'retry in 8s' in body
    assert headers['Refresh'] == '8; url=/test'
    assert headers['Retry-After'] == '8'


def test_format_locked_error_response_xml():
    body, ctype, headers = job_api.format_locked_error_response('application/xml', 12, url='/xml')
    assert 'application/xml' in ctype
    assert '<status>locked</status>' in body
    assert 'retry in 12s' in body
    assert headers['Refresh'] == '12; url=/xml'
    assert headers['Retry-After'] == '12'


# ---------------------------------------------------------------------------
# Edge case: empty results
# ---------------------------------------------------------------------------


def test_format_output_empty_json():
    out, mime = job_api.format_output([], 'application/json')
    import json
    data = json.loads(out)
    assert data['status'] == 'ok'
    assert data['count'] == 0
    assert data['jobs'] == []


def test_format_output_empty_csv():
    out, mime = job_api.format_output([], 'text/csv')
    # Empty CSV should have a minimal status line
    assert 'status' in out.lower() or 'ok' in out.lower()
