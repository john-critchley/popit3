if __name__ != "__main__": print("Module:", __name__)

"""
Handler for GitHub notification emails to john.github@critchley.biz.

GitHub sends many types of notification — we classify and route them:

  Run failed/succeeded/cancelled  → notes ci/github        (CI results log)
  Dependabot / security alert     → notes github/security   (prominently)
  Release published               → notes github/releases   (rebase signal)
  Everything else (PR, issue,
    comment, review)              → logged and discarded    (noise)

Subject patterns from GitHub:
  [owner/repo] Run failed: Workflow Name (branch)
  [owner/repo] Run succeeded: Workflow Name (branch)
  [owner/repo] [Dependabot] some-dep 1.2.3 -> 1.2.4
  [GitHub] Security advisory: ...
  [owner/repo] Release v3.71.0
  [owner/repo] Pull request title (#123)
  Re: [owner/repo] Some PR or issue (#123)
"""

import email
import email.header
import email.utils
import re
import json
import datetime
import urllib.request
import urllib.error
import os

NOTES_URL    = os.environ.get('NOTES_URL', 'http://127.0.0.1:8021')
CI_KEY       = 'ci/github'
SECURITY_KEY = 'github/security'
RELEASES_KEY = 'github/releases'
MAX_RESULTS  = 100

# --- subject classifiers -------------------------------------------------

CI_RE = re.compile(
    r'^\[(?P<repo>[^\]]+)\]\s+Run\s+(?P<status>failed|succeeded|cancelled):\s+'
    r'(?P<workflow>.+?)(?:\s+\((?P<branch>[^)]+)\))?\s*$',
    re.IGNORECASE
)

SECURITY_RE = re.compile(
    r'(?:'
    r'^\[(?:[^\]]+)\]\s+\[Dependabot\]'          # [repo] [Dependabot] ...
    r'|^\[GitHub\]\s+(?:Security|Vulnerability)'  # [GitHub] Security advisory
    r'|\bsecurity\s+alert\b'                      # "security alert" anywhere in subject
    r')',
    re.IGNORECASE
)

# Matches: [owner/repo] Release v3.71.0
#          [owner/repo] New release: v1.2.3
RELEASE_RE = re.compile(
    r'^\[(?P<repo>[^\]]+)\]\s+(?:New\s+)?[Rr]elease[:\s]+(?P<tag>\S+)',
    re.IGNORECASE
)

RUN_URL_RE = re.compile(r'https://github\.com/[^\s]+/actions/runs/\d+')
GH_URL_RE  = re.compile(r'https://github\.com/\S+')


# --- helpers -------------------------------------------------------------

def _decode_header(h):
    if not h:
        return ''
    parts = email.header.decode_header(h)
    out = []
    for part, charset in parts:
        if isinstance(part, bytes):
            out.append(part.decode(charset or 'utf-8', errors='replace'))
        else:
            out.append(part)
    return ''.join(out)


def _get_body_text(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or 'utf-8', errors='replace')
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(msg.get_content_charset() or 'utf-8', errors='replace')
    return ''


def _timestamp(msg):
    try:
        return email.utils.parsedate_to_datetime(msg.get('Date', '')).isoformat()
    except Exception:
        return datetime.datetime.utcnow().isoformat()


def _notes_get(key):
    try:
        with urllib.request.urlopen(f'{NOTES_URL}/get/{key}', timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _notes_put(key, value):
    body = json.dumps(value).encode()
    req = urllib.request.Request(
        f'{NOTES_URL}/put/{key}', data=body,
        headers={'Content-Type': 'application/json'}, method='PUT'
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _store_rolling(key, new_items, build_doc_fn):
    existing  = _notes_get(key) or {}
    old_items = existing.get('_items', [])
    combined  = (new_items + old_items)[:MAX_RESULTS]
    doc = build_doc_fn(combined)
    doc['_items'] = combined
    _notes_put(key, doc)
    return len(combined)


# --- CI results ----------------------------------------------------------

def _ci_icon(status):
    return {'succeeded': '✅', 'failed': '❌', 'cancelled': '⚠️'}.get(status.lower(), '❓')


def _parse_ci(msg):
    subject = _decode_header(msg.get('Subject', ''))
    m = CI_RE.match(subject.strip())
    if not m:
        return None
    body    = _get_body_text(msg)
    url_m   = RUN_URL_RE.search(body)
    return {
        'type':     'ci',
        'repo':     m.group('repo').strip(),
        'status':   m.group('status').strip().lower(),
        'workflow': m.group('workflow').strip(),
        'branch':   (m.group('branch') or '').strip(),
        'run_url':  url_m.group(0) if url_m else '',
        'ts':       _timestamp(msg),
        'subject':  subject.strip(),
    }


def _build_ci_doc(items):
    rows = []
    for r in items:
        icon = _ci_icon(r['status'])
        link = {'link': {'href': r['run_url'], 'text': r['repo']}} if r['run_url'] else r['repo']
        rows.append({'para': [
            f"{icon} ", link,
            f" — {r['workflow']}"
            + (f" ({r['branch']})" if r['branch'] else '')
            + f" — {r['ts'][:16].replace('T', ' ')}"
        ]})
    return {
        'title':   'CI Results — GitHub Actions',
        'version': 1,
        'updated': datetime.date.today().isoformat(),
        'tags':    ['ci', 'github'],
        'content': [
            {'heading': {'level': 1, 'text': 'CI Results — GitHub Actions'}},
            {'para':    [f'{len(items)} runs, most recent first.']},
            *rows,
        ],
        'children': [],
    }


# --- releases ------------------------------------------------------------

def _parse_release(msg):
    subject = _decode_header(msg.get('Subject', ''))
    m = RELEASE_RE.match(subject.strip())
    if not m:
        return None
    body  = _get_body_text(msg)
    url_m = GH_URL_RE.search(body)
    return {
        'type':    'release',
        'repo':    m.group('repo').strip(),
        'tag':     m.group('tag').strip(),
        'url':     url_m.group(0).rstrip('.,)>') if url_m else '',
        'ts':      _timestamp(msg),
        'subject': subject.strip(),
    }


def _build_releases_doc(items):
    rows = []
    for r in items:
        link = {'link': {'href': r['url'], 'text': f"{r['repo']} {r['tag']}"}} if r['url'] \
               else f"{r['repo']} {r['tag']}"
        rows.append({'para': [f"📦 ", link, f" — {r['ts'][:16].replace('T', ' ')}"]})
    return {
        'title':   'GitHub Releases',
        'version': 1,
        'updated': datetime.date.today().isoformat(),
        'tags':    ['github', 'releases'],
        'content': [
            {'heading': {'level': 1, 'text': 'GitHub Releases'}},
            {'para':    ['Upstream releases. Check each one — may need rebase of local branches.']},
            {'para':    [f'{len(items)} releases, most recent first.']},
            *rows,
        ],
        'children': [],
    }


# --- security alerts -----------------------------------------------------

def _parse_security(msg):
    subject = _decode_header(msg.get('Subject', ''))
    body    = _get_body_text(msg)
    url_m   = GH_URL_RE.search(body)
    return {
        'type':    'security',
        'subject': subject.strip(),
        'url':     url_m.group(0).rstrip('.,)>') if url_m else '',
        'ts':      _timestamp(msg),
    }


def _build_security_doc(items):
    rows = []
    for r in items:
        link = {'link': {'href': r['url'], 'text': r['subject']}} if r['url'] else r['subject']
        rows.append({'para': [f"🔒 ", link, f" — {r['ts'][:16].replace('T', ' ')}"]})
    return {
        'title':   'GitHub Security Alerts',
        'version': 1,
        'updated': datetime.date.today().isoformat(),
        'tags':    ['security', 'github'],
        'content': [
            {'heading': {'level': 1, 'text': 'GitHub Security Alerts'}},
            {'para':    [f'{len(items)} alerts, most recent first.']},
            *rows,
        ],
        'children': [],
    }


# --- main handler --------------------------------------------------------

def process_github_mails(emails):
    """
    Handler called by process_emails.py with list of (uidl, msg) tuples.
    Returns set of UIDs to delete from the spool.

    UIDs are only marked for deletion once their data is safely written to
    the notes server.  If the notes server is down the emails stay in the
    spool and are retried on the next cron run.  "Other" emails (PRs,
    issues, comments) carry no data worth keeping and are always deleted.
    """
    if not emails:
        return set()

    ci_items       = []   # (uidl, parsed)
    security_items = []   # (uidl, parsed)
    release_items  = []   # (uidl, parsed)
    delete         = set()

    for uidl, msg in emails:
        subject = _decode_header(msg.get('Subject', '(no subject)'))

        ci = _parse_ci(msg)
        if ci:
            print(f'  GitHub CI: [{ci["status"]}] {ci["repo"]} / {ci["workflow"]} ({ci["branch"]})')
            ci_items.append((uidl, ci))
            continue

        if SECURITY_RE.search(subject):
            sec = _parse_security(msg)
            print(f'  GitHub security: {subject!r}')
            security_items.append((uidl, sec))
            continue

        rel = _parse_release(msg)
        if rel:
            print(f'  GitHub release: {rel["repo"]} {rel["tag"]}')
            release_items.append((uidl, rel))
            continue

        # PR, issue, comment, review — no data to store, always delete
        print(f'  GitHub other (discarded): {subject!r}')
        delete.add(uidl)

    if ci_items:
        try:
            n = _store_rolling(CI_KEY, [x for _, x in ci_items], _build_ci_doc)
            print(f'  GitHub CI: {len(ci_items)} new, {n} total stored at {CI_KEY}')
            delete.update(uidl for uidl, _ in ci_items)
        except Exception as e:
            print(f'  GitHub CI: notes write failed ({e}) — leaving in spool for retry')

    if security_items:
        try:
            n = _store_rolling(SECURITY_KEY, [x for _, x in security_items], _build_security_doc)
            print(f'  GitHub security: {len(security_items)} new, {n} total stored at {SECURITY_KEY}')
            delete.update(uidl for uidl, _ in security_items)
        except Exception as e:
            print(f'  GitHub security: notes write failed ({e}) — leaving in spool for retry')

    if release_items:
        try:
            n = _store_rolling(RELEASES_KEY, [x for _, x in release_items], _build_releases_doc)
            print(f'  GitHub releases: {len(release_items)} new, {n} total stored at {RELEASES_KEY}')
            delete.update(uidl for uidl, _ in release_items)
        except Exception as e:
            print(f'  GitHub releases: notes write failed ({e}) — leaving in spool for retry')

    return delete
