"""
Tests for dl_email.parse_david_lloyd_email_part using saved fixtures.
"""
import email as emaillib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import dl_email

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def _html_from_eml(filename):
    path = os.path.join(FIXTURES, filename)
    with open(path, 'rb') as f:
        raw = f.read()
    # strip BOM-like leading high bytes
    i = 0
    while i < len(raw) and raw[i] > 0x7f:
        i += 1
    msg = emaillib.message_from_bytes(raw[i:])
    for part in msg.walk():
        if part.get_content_type() == 'text/html':
            payload = part.get_payload(decode=True)
            if payload:
                return payload.decode(part.get_content_charset() or 'utf-8', errors='replace')
            return part.get_payload()
    return None


def test_booking_bodypump():
    html = _html_from_eml('dl_booking_bodypump.eml')
    result = dl_email.parse_david_lloyd_email_part(html)
    assert result['kind'] == 'booking'
    assert result['booking_reference'] is not None
    assert result['start'] is not None
    assert result['end'] is not None
    assert result['activity'] is not None


def test_cancellation():
    html = _html_from_eml('dl_cancellation.eml')
    result = dl_email.parse_david_lloyd_email_part(html)
    assert result['kind'] == 'cancellation'
    assert result['booking_reference'] is not None


def test_pt_session_not_stored():
    """PT sessions (FT- ref) parse correctly but are excluded from DB by process_dl_mails."""
    html = _html_from_eml('dl_pt_session.eml')
    result = dl_email.parse_david_lloyd_email_part(html)
    assert result['kind'] == 'booking'
    assert result['booking_reference'].startswith('FT-')
    assert result['start'] is not None
    assert result['end'] is not None
    assert result['activity'] == 'Personal Training'
    assert result['coach'] is not None


def test_payment_receipt_no_booking_ref():
    """Payment receipt emails should not yield a DL booking reference."""
    html = _html_from_eml('dl_payment_receipt.eml')
    result = dl_email.parse_david_lloyd_email_part(html)
    # booking_reference will be None since BOOKING_REF_RE only matches DL-/FT-
    assert result['booking_reference'] is None or not result['booking_reference'].startswith('DL-')


def test_stages_workout_no_booking_ref():
    """StagesStudio workout summaries should not yield any booking reference."""
    html = _html_from_eml('dl_stages_workout_summary.eml')
    result = dl_email.parse_david_lloyd_email_part(html)
    assert result['booking_reference'] is None
