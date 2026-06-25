#!/usr/bin/python3
"""
Shim loader: delegates to the real script at the path below.
Checks mtime on every request and reloads if the source has changed.
"""

import os
import sys
import threading
import importlib.util

sys.path.insert(0, '/home/john/.local/lib/python3.13/site-packages')

_SOURCE = '/home/dav/wsgi/wsgi_get_pop_refresh_token.py'

_lock  = threading.Lock()
_mod   = None
_mtime = None


def _reload():
    global _mod, _mtime
    spec = importlib.util.spec_from_file_location('_pop_refresh_token_impl', _SOURCE)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _mod   = mod
    _mtime = os.path.getmtime(_SOURCE)


def _get_application():
    global _mod, _mtime
    current_mtime = os.path.getmtime(_SOURCE)
    if _mod is None or current_mtime != _mtime:
        with _lock:
            if _mod is None or current_mtime != _mtime:   # double-check inside lock
                _reload()
    return _mod.application


def application(environ, start_response):
    return _get_application()(environ, start_response)
