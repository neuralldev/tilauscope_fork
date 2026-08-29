# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. It is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License
# for more details. You should have received a copy of the GNU Affero General
# Public License along with this program. If not, see
# <https://www.gnu.org/licenses/>.

# AUTHOR
# TiLau 2026

"""What leaves the machine towards a model provider, and what does not.

The scrubber has two jobs that pull in opposite directions: destroy personal
data, and keep the prompt useful. A test that only checked the first would be
satisfied by returning an empty string, so every case here asserts both sides —
what is gone *and* what survived.
"""

from __future__ import annotations

from tilauscope.tilau_privacy import (
    MAX_PROMPT_CHARS,
    Profile,
    prepare_ai_messages,
    sanitize_text,
    sanitize_url,
)


# ── URL purge ────────────────────────────────────────────────────────────────

def test_url_keeps_the_product_and_drops_the_person() -> None:
    verdict = sanitize_url(
        'https://Shop.Example.com:443/coffee/lot-7'
        '?product_id=42&variant=250g'
        '&utm_source=newsletter&gclid=abc&customer=jane%40mail.com'
        '&session=9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c#reviews'
    )

    assert verdict.ok
    assert verdict.url == ('https://shop.example.com/coffee/lot-7'
                           '?product_id=42&variant=250g')
    assert 'query:utm_source' in verdict.removed
    assert 'query:customer' in verdict.removed
    assert 'fragment' in verdict.removed


def test_url_drops_an_opaque_value_whatever_the_vendor_called_it() -> None:
    """The deny list cannot know every vendor's name for a session id."""
    verdict = sanitize_url(
        'https://shop.example/p?ref_code=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.dBjftJeZ4CV'
        '&sku=ETH-001'
    )
    assert verdict.url == 'https://shop.example/p?sku=ETH-001'


def test_url_strips_credentials() -> None:
    verdict = sanitize_url('https://jane:hunter2@shop.example/p?id=7')
    assert verdict.url == 'https://shop.example/p?id=7'
    assert 'credentials' in verdict.removed


def test_a_page_that_is_not_public_is_refused() -> None:
    """Also closes the door on reading the local network into a prompt."""
    for address in ('http://192.168.1.10/admin', 'http://localhost:8000/x',
                    'https://roaster.local/status', 'http://10.0.0.5/'):
        verdict = sanitize_url(address)
        assert not verdict.ok, address
        assert verdict.url == ''
        assert verdict.refused == 'private-host'


def test_only_web_pages_are_fetchable() -> None:
    assert sanitize_url('file:///Users/jane/secrets.txt').refused == 'scheme'
    assert sanitize_url('ftp://example.com/x').refused == 'scheme'
    assert sanitize_url('  ').refused == 'empty'
    assert sanitize_url('https://shop.example:8443/p').refused == 'port'


# ── text scrubbing ───────────────────────────────────────────────────────────

_NOTE = (
    'Roasted for jane.roaster@example.com, call +33 6 12 34 56 78, '
    'card 4111 1111 1111 1111, profile in /Users/jane/roasts/ethiopia.alog '
    'and ~/Desktop/notes.txt — bought at '
    'https://shop.example/home/ethiopia?product_id=12&customer=jane%40mail.com'
)


def test_a_prompt_keeps_its_url_and_loses_everything_personal() -> None:
    cleaned = sanitize_text(_NOTE, ('Jane Roaster',), profile=Profile.AI_OUTBOUND)

    for gone in ('jane.roaster@example.com', '+33 6 12 34 56 78',
                 '4111 1111 1111 1111', '/Users/jane', '~/Desktop',
                 'customer=jane'):
        assert gone not in cleaned

    # The supplier page is why the feature exists: the address survives, and
    # the file-path rule has not eaten the '/home/' in it.
    assert 'https://shop.example/home/ethiopia?product_id=12' in cleaned


def test_a_debug_archive_still_destroys_every_url() -> None:
    """The two profiles share one rule table; this is the half that must not move."""
    cleaned = sanitize_text(_NOTE, (), profile=Profile.DIAGNOSTIC)
    assert 'shop.example' not in cleaned
    assert '[REDACTED_URL]' in cleaned


def test_an_ordinary_number_is_not_mistaken_for_a_card() -> None:
    """Luhn keeps the roast data readable — a prompt full of holes is useless."""
    metrics = 'Drop BT 214.5 C, total 11:20, DTR 21.4%, batch 20260827123456'
    assert sanitize_text(metrics, (), profile=Profile.AI_OUTBOUND) == metrics


def test_a_short_identity_value_is_not_substituted() -> None:
    """An operator initial would otherwise shred every word containing it."""
    text = 'Charge at 200 C, TP at 1:35'
    assert sanitize_text(text, ('T',), profile=Profile.AI_OUTBOUND) == text


# ── the gate ─────────────────────────────────────────────────────────────────

def test_prepare_ai_messages_scrubs_both_halves() -> None:
    """The system prompt is ours, but it interpolates the roaster's name."""
    messages, report = prepare_ai_messages(
        'You advise on a roaster named Jane-MacBook.', _NOTE, task='TEST')

    assert [m['role'] for m in messages] == ['system', 'user']
    assert 'jane.roaster@example.com' not in messages[1]['content']
    assert report.total > 0
    assert 'email' in report.summary()


def test_prepare_ai_messages_caps_the_payload() -> None:
    """The scraper's structured sections have no length limit of their own."""
    messages, report = prepare_ai_messages('sys', 'x' * (MAX_PROMPT_CHARS + 5000))
    assert len(messages[1]['content']) < MAX_PROMPT_CHARS + 100
    assert report.truncated_chars == 5000


def test_a_clean_payload_reports_clean() -> None:
    messages, report = prepare_ai_messages(
        'You are a roasting consultant.', 'Drop BT 214 C, DTR 21%.')
    assert report.is_clean
    assert report.summary() == ''
    assert messages[1]['content'] == 'Drop BT 214 C, DTR 21%.'
