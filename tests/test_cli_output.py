"""CLI success output tests (subprocess-based)."""
import json
import os
import subprocess
import sys

import pytest


CLI_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'job_api.py')


def run_cli(*args):
    cmd = [sys.executable, CLI_PATH] + list(args)
    proc = subprocess.run(
        cmd,
        cwd=os.path.dirname(CLI_PATH),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc


def test_cli_json_output():
    proc = run_cli('--format', 'json', '--days', '7', '--min-score', '5')
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data['status'] == 'ok'
    assert isinstance(data['count'], int)
    assert isinstance(data['jobs'], list)


def test_cli_csv_output():
    proc = run_cli('--format', 'csv', '--days', '7', '--min-score', '5')
    assert proc.returncode == 0
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    # At minimum we should have header or status line
    assert len(lines) >= 1
    # If jobs exist, header should have known fields
    if 'score' in lines[0]:
        assert 'job_title' in lines[0]


def test_cli_yaml_output():
    proc = run_cli('--format', 'yaml', '--days', '7', '--min-score', '5')
    assert proc.returncode == 0
    import yaml
    data = yaml.safe_load(proc.stdout)
    assert data['status'] == 'ok'
    assert isinstance(data['jobs'], list)


def test_cli_xml_output():
    proc = run_cli('--format', 'xml', '--days', '7', '--min-score', '5')
    assert proc.returncode == 0
    assert '<response>' in proc.stdout
    assert '<status>ok</status>' in proc.stdout


def test_cli_empty_results_high_min_score():
    # Very high min_score should yield no jobs but still valid output
    proc = run_cli('--format', 'json', '--days', '7', '--min-score', '9999')
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data['status'] == 'ok'
    assert data['count'] == 0
    assert data['jobs'] == []
