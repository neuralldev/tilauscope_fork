#
# ABOUT
# tilau_privacy.py - one scrubber for everything that leaves the machine

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

"""Personal-data scrubbing for anything that leaves the user's machine.

Two destinations, one rule table, two profiles:

``Profile.DIAGNOSTIC``
    The debug archive attached to a public issue. Nothing there needs a
    reachable address, so every URL is destroyed outright.

``Profile.AI_OUTBOUND``
    A prompt sent to a third-party model. The bean extractor *needs* its URL —
    destroying it would destroy the feature — so URLs are normalised instead:
    credentials, fragment, tracking and identifying query parameters removed,
    private hosts refused. Everything else is scrubbed harder than in a log,
    because a prompt can carry a free-text note the user typed.

This is a last line of defence, not a personal-data classifier. A caller that
knows a field is personal must not put it in the payload in the first place.
"""

from __future__ import annotations

import ipaddress
import logging
import platform
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_log: Final[logging.Logger] = logging.getLogger(__name__)

REDACTION: Final[str] = '[REDACTED]'


class Profile(StrEnum):
    """Where the text is going. Chooses how URLs are treated."""

    DIAGNOSTIC   = 'DIAGNOSTIC'    # debug archive: URLs destroyed
    AI_OUTBOUND  = 'AI_OUTBOUND'   # model prompt: URLs normalised


# ─────────────────────────────────────────────────────────────────────────────
# Rule table
#
# Each rule is (tag, pattern, replacement). The tag is what the report counts;
# matching on it is stable, matching on the replacement prose is not.
# ─────────────────────────────────────────────────────────────────────────────

Rule = tuple[str, re.Pattern[str], str]

_AUTH: Final[Rule] = (
    'auth',
    re.compile(r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+"),
    '[REDACTED_AUTH]',
)
_SECRET: Final[Rule] = (
    'secret',
    re.compile(
        r"(?i)([\"']?(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|"
        r"device[_ -]?token|token|password|passwd|secret|authorization|cookie|"
        r"session[_ -]?id)[\"']?\s*[:=]\s*)"
        r"(?:[\"'][^\"'\r\n]*[\"']|[^\s,;}\]\r\n]+)"),
    r'\1[REDACTED_SECRET]',
)
_EMAIL: Final[Rule] = (
    'email',
    re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    '[REDACTED_EMAIL]',
)
_URL: Final[Rule] = (
    'url',
    re.compile(r"(?i)\b(?:https?|wss?|mqtts?)://[^\s<>\"']+"),
    '[REDACTED_URL]',
)
_PATH_RULES: Final[tuple[Rule, ...]] = (
    ('path',
     re.compile(
         r"(?i)([\"']?(?:path|file[_ -]?path|file[_ -]?name|directory|folder|"
         r"background[_ -]?path|alog[_ -]?directory|beancave[_ -]?directory)"
         r"[\"']?\s*[:=]\s*)(?:[\"'][^\"'\r\n]*[\"']|[^\s,;}\]\r\n]+)"),
     r'\1[REDACTED_PATH]'),
    ('path',
     re.compile(
         r"(?<![\w:])/(?:Users|home|Volumes|mnt|media|tmp|private/(?:var|tmp))"
         r"/[^/\s\"'<>]+(?:/[^\s\"'<>]*)?"),
     '[REDACTED_PATH]'),
    ('path',
     re.compile(r"(?i)\b[A-Z]:\\[^\r\n\"'<>]+"),
     '[REDACTED_PATH]'),
    ('path',
     re.compile(r"(?<![\w~])~/[^\s\"'<>]+"),
     '[REDACTED_PATH]'),
    ('path',
     re.compile(r"\\\\[^\\\s]+\\[^\\\s]+(?:\\[^\r\n\"'<>]*)?"),
     '[REDACTED_PATH]'),
)
_NETWORK_RULES: Final[tuple[Rule, ...]] = (
    ('ip',
     re.compile(
         r"(?<![\w.])(?:25[0-5]|2[0-4]\d|1?\d?\d)"
         r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\w.])"),
     '[REDACTED_IP]'),
    ('mac',
     re.compile(r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])"),
     '[REDACTED_MAC]'),
    ('uuid',
     re.compile(
         r"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
         r"[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![0-9a-f])"),
     '[REDACTED_UUID]'),
)
_PERSONAL: Final[Rule] = (
    'personal',
    re.compile(
        r"(?i)([\"']?(?:operator|organization|organisation|user[_ -]?name|"
        r"device[_ -]?name|full[_ -]?name|phone|telephone|contact|customer|"
        r"client|supplier)[\"']?\s*[:=]\s*)"
        r"(?:[\"'][^\"'\r\n]*[\"']|[^\s,;}\]\r\n]+)"),
    r'\1[REDACTED_PERSONAL]',
)

#: Only ever applied to a prompt. A log line is machine-written and these
#: patterns cost more in false positives there than they buy back; a note the
#: user typed by hand is exactly where a phone number or an IBAN turns up.
_FREE_TEXT_RULES: Final[tuple[Rule, ...]] = (
    ('phone',
     re.compile(r"(?<![\w.])\+\d[\d .\-()]{7,}\d(?![\w])"),
     '[REDACTED_PHONE]'),
    ('phone',
     re.compile(r"(?<![\w.])0[1-9](?:[ .\-]\d{2}){4}(?![\w])"),
     '[REDACTED_PHONE]'),
    ('iban',
     re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}[ ]?[A-Z0-9]{1,4}\b"),
     '[REDACTED_IBAN]'),
)

_IPV6_CANDIDATE: Final[re.Pattern[str]] = re.compile(
    r"(?<![0-9A-Fa-f:])\[?(?P<address>[0-9A-Fa-f:.]*:[0-9A-Fa-f:.]+)\]?"
    r"(?![0-9A-Fa-f:])"
)

#: 13-19 digits, separators allowed. Luhn-checked before replacement — without
#: that check the pattern eats ordinary long numbers.
_CARD_CANDIDATE: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w.])(?:\d[ -]?){12,18}\d(?![\w.])"
)

#: Sentinels that park an already-cleaned URL while the other rules run, so a
#: product path such as ``/home/blend`` is not eaten by the file-path rule.
_MARK_OPEN:  Final[str] = ''
_MARK_CLOSE: Final[str] = ''


def _redact_ipv6(match: re.Match[str]) -> str:
    try:
        if ipaddress.ip_address(match.group('address')).version == 6:
            return '[REDACTED_IP]'
    except ValueError:
        pass
    return match.group(0)


def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, char in enumerate(digits):
        value = int(char)
        if i % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RedactionReport:
    """What the scrubber took out, by tag. Shown to the user, logged, asserted."""

    counts: dict[str, int] = field(default_factory=dict)
    urls_cleaned: int = 0
    urls_refused: int = 0
    truncated_chars: int = 0

    def note(self, tag: str, n: int = 1) -> None:
        if n:
            self.counts[tag] = self.counts.get(tag, 0) + n

    def merge(self, other: RedactionReport) -> None:
        for tag, n in other.counts.items():
            self.note(tag, n)
        self.urls_cleaned    += other.urls_cleaned
        self.urls_refused    += other.urls_refused
        self.truncated_chars += other.truncated_chars

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def is_clean(self) -> bool:
        return not self.total and not self.urls_cleaned and not self.urls_refused

    def summary(self) -> str:
        """One line, for a log or a status pill. Empty when nothing was touched."""
        parts = [f'{tag}×{n}' for tag, n in sorted(self.counts.items())]
        if self.urls_cleaned:
            parts.append(f'urls-cleaned×{self.urls_cleaned}')
        if self.urls_refused:
            parts.append(f'urls-refused×{self.urls_refused}')
        if self.truncated_chars:
            parts.append(f'truncated {self.truncated_chars} chars')
        return ', '.join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# URL purge
# ─────────────────────────────────────────────────────────────────────────────

#: Parameter names that carry identity or tracking. Matched case-insensitively
#: and exactly: a shop's ``product_id`` must survive, a ``customer_id`` must not.
_DENY_PARAMS: Final[frozenset[str]] = frozenset({
    'access_token', 'account', 'account_id', 'aff', 'affiliate', 'apikey',
    'api_key', 'auth', 'authorization', 'client_id', 'code', 'customer',
    'customer_id', 'email', 'e_mail', 'epik', 'fbclid', 'gclid', 'hmac',
    'id_token', 'igshid', 'irclickid', 'jsessionid', 'key', 'login', 'mail',
    'mc_cid', 'mc_eid', 'msclkid', 'nonce', 'order', 'orderid', 'order_id',
    'partner', 'passwd', 'password', 'phone', 'phpsessid', 'pwd', 'ref',
    'referrer', 'refresh_token', 's_kwcid', 'secret', 'session', 'sessionid',
    'session_id', 'sid', 'sig', 'signature', 'state', 'subid', 'token',
    'ttclid', 'uid', 'user', 'userid', 'user_id', 'username', 'yclid',
})

#: Prefixes that mark a whole family of tracking parameters.
_DENY_PREFIXES: Final[tuple[str, ...]] = ('utm_', '_hs', 'pk_', 'mtm_', 'oly_')

#: Substrings that betray a secret whatever the vendor called the parameter.
_DENY_SUBSTRINGS: Final[tuple[str, ...]] = ('token', 'secret', 'passw', 'apikey')

#: Names worth keeping even when the value looks opaque — a product reference
#: often is. An address-shaped value is still dropped below.
_ALLOW_PARAMS: Final[frozenset[str]] = frozenset({
    'c', 'cat', 'category', 'collection', 'currency', 'id', 'lang', 'language',
    'locale', 'model', 'p', 'page', 'product', 'product_id', 'q', 'search',
    'sku', 'variant', 'variant_id',
})

#: Hostnames that are never a public product page. Checked literally: this
#: module must not resolve DNS — that would block the caller's thread and the
#: answer could change between the check and the fetch anyway.
_LOCAL_HOSTS: Final[frozenset[str]] = frozenset({
    'localhost', 'localhost.localdomain', 'ip6-localhost',
    'metadata.google.internal', 'instance-data',
})
_LOCAL_SUFFIXES: Final[tuple[str, ...]] = ('.local', '.internal', '.localdomain', '.home', '.lan')

_ALLOWED_PORTS: Final[frozenset[int]] = frozenset({80, 443})

_JWT_LIKE:    Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}$")
_HEX_LIKE:    Final[re.Pattern[str]] = re.compile(r"^[0-9a-fA-F]{24,}$")
_OPAQUE_LIKE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_\-+/=]{32,}$")

#: A URL longer than this is not a product page any more.
MAX_URL_CHARS: Final[int] = 2048


@dataclass(frozen=True)
class UrlVerdict:
    """Outcome of :func:`sanitize_url`.

    ``url`` is safe to fetch, to log and to put in a prompt. It is empty when
    ``refused`` is set — the caller must then do nothing at all with the input.
    """

    url: str
    removed: tuple[str, ...] = ()
    refused: str | None = None

    @property
    def ok(self) -> bool:
        return self.refused is None


def _param_is_personal(name: str, value: str) -> bool:
    low = name.strip().lower()
    if low in _DENY_PARAMS:
        return True
    if low.startswith(_DENY_PREFIXES):
        return True
    if any(bit in low for bit in _DENY_SUBSTRINGS):
        return True
    if '@' in value or _EMAIL[1].search(value):
        return True
    if low in _ALLOW_PARAMS:
        return False
    return bool(_JWT_LIKE.match(value) or _HEX_LIKE.match(value)
                or _OPAQUE_LIKE.match(value))


def _host_is_local(host: str) -> bool:
    host = host.strip('[]').lower().rstrip('.')
    if not host:
        return True
    if host in _LOCAL_HOSTS or host.endswith(_LOCAL_SUFFIXES):
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return '.' not in host          # a bare label is an intranet name
    return bool(addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified)


def sanitize_url(raw: str) -> UrlVerdict:
    """Strip a URL of everything that identifies a person, or refuse it.

    Removed: userinfo, fragment, tracking and identity query parameters, and
    any parameter whose *value* looks like a token or an address whatever its
    name. Refused: anything but http/https, a non-standard port, and any host
    that is not on the public internet — which also closes the door on using
    the bean extractor to read the local network and hand it to a model.
    """
    text = (raw or '').strip()
    if not text:
        return UrlVerdict('', refused='empty')
    if len(text) > MAX_URL_CHARS:
        return UrlVerdict('', refused='too-long')

    try:
        parts = urlsplit(text)
    except ValueError:
        return UrlVerdict('', refused='unparsable')

    if parts.scheme.lower() not in ('http', 'https'):
        return UrlVerdict('', refused='scheme')

    try:
        host, port = parts.hostname, parts.port
    except ValueError:
        return UrlVerdict('', refused='unparsable')
    if not host:
        return UrlVerdict('', refused='no-host')
    if _host_is_local(host):
        return UrlVerdict('', refused='private-host')
    if port is not None and port not in _ALLOWED_PORTS:
        return UrlVerdict('', refused='port')

    removed: list[str] = []
    if parts.username or parts.password:
        removed.append('credentials')
    if parts.fragment:
        removed.append('fragment')

    kept: list[tuple[str, str]] = []
    for name, value in parse_qsl(parts.query, keep_blank_values=True):
        if _param_is_personal(name, value):
            removed.append(f'query:{name}')
        else:
            kept.append((name, value))

    netloc = host.lower()
    default_port = 443 if parts.scheme.lower() == 'https' else 80
    if port is not None and port != default_port:
        netloc = f'{netloc}:{port}'

    clean = urlunsplit((parts.scheme.lower(), netloc, parts.path,
                        urlencode(kept), ''))
    return UrlVerdict(clean, tuple(removed))


# ─────────────────────────────────────────────────────────────────────────────
# Text scrubbing
# ─────────────────────────────────────────────────────────────────────────────

def runtime_sensitive_values() -> tuple[str, ...]:
    """Local identity values that must never leave the machine.

    Read fresh on every call: the operator may be set in Settings between two
    requests, and this is never on a hot path.
    """
    values: set[str] = {Path.home().name, platform.node()}
    try:
        from PyQt6.QtCore import QSettings  # noqa: PLC0415
        settings = QSettings()
        values.update(
            str(settings.value(key, '') or '').strip() for key in (
                'operator', 'operator_setup', 'organization', 'organization_setup')
        )
    except Exception:  # noqa: BLE001 - headless tooling has no Qt settings
        pass
    # Very short values create destructive false positives (an operator initial
    # such as "T"), while paths and labelled fields stay covered by the
    # structural rules.
    return tuple(sorted((value for value in values if len(value) >= 3),
                        key=len, reverse=True))


def _rules_for(profile: Profile) -> tuple[Rule, ...]:
    common = (_AUTH, _SECRET, *_PATH_RULES, *_NETWORK_RULES, _PERSONAL)
    if profile is Profile.AI_OUTBOUND:
        return (*common, *_FREE_TEXT_RULES)
    return common


def _apply(rule: Rule, text: str, report: RedactionReport) -> str:
    tag, pattern, replacement = rule
    cleaned, n = pattern.subn(replacement, text)
    report.note(tag, n)
    return cleaned


def _mask_urls(text: str, profile: Profile,
               report: RedactionReport) -> tuple[str, list[str]]:
    """Replace every URL with a sentinel, returning the texts to restore."""
    parked: list[str] = []

    def _swap(match: re.Match[str]) -> str:
        found = match.group(0)
        if profile is Profile.DIAGNOSTIC:
            report.note('url')
            return _URL[2]
        # A URL at the end of a sentence keeps its punctuation out of the parse.
        trailing = ''
        while found and found[-1] in '.,;:)]}\'"':
            trailing, found = found[-1] + trailing, found[:-1]
        verdict = sanitize_url(found)
        if not verdict.ok:
            report.urls_refused += 1
            report.note('url')
            replacement = _URL[2]
        else:
            if verdict.removed:
                report.urls_cleaned += 1
            replacement = verdict.url
        parked.append(replacement + trailing)
        return f'{_MARK_OPEN}{len(parked) - 1}{_MARK_CLOSE}'

    return _URL[1].sub(_swap, text), parked


def _unmask_urls(text: str, parked: Sequence[str]) -> str:
    if not parked:
        return text
    return re.sub(
        f'{_MARK_OPEN}(\\d+){_MARK_CLOSE}',
        lambda m: parked[int(m.group(1))],
        text,
    )


def sanitize_text(text: str,
                  sensitive_values: Iterable[str] = (),
                  *,
                  profile: Profile = Profile.DIAGNOSTIC,
                  report: RedactionReport | None = None) -> str:
    """Remove personal data and credentials from *text*.

    ``sensitive_values`` are exact strings known to identify this user; they go
    first so a multi-word name is still whole when it is matched, before a
    field-level rule replaces part of its context.
    """
    rep = report if report is not None else RedactionReport()
    cleaned = text or ''

    # Addresses go before the identity values: an e-mail is self-contained, and
    # scrubbing the user's first name out of it first would leave the domain
    # standing as a half-redacted address.
    cleaned = _apply(_EMAIL, cleaned, rep)

    for value in sensitive_values:
        private_value = str(value).strip()
        if len(private_value) >= 3:
            cleaned, n = re.subn(re.escape(private_value), REDACTION, cleaned,
                                 flags=re.IGNORECASE)
            rep.note('identity', n)

    cleaned, parked = _mask_urls(cleaned, profile, rep)
    for rule in _rules_for(profile):
        cleaned = _apply(rule, cleaned, rep)
    cleaned = _IPV6_CANDIDATE.sub(
        lambda m: _count_ipv6(m, rep), cleaned)
    if profile is Profile.AI_OUTBOUND:
        cleaned = _CARD_CANDIDATE.sub(lambda m: _redact_card(m, rep), cleaned)
    return _unmask_urls(cleaned, parked)


def _count_ipv6(match: re.Match[str], report: RedactionReport) -> str:
    out = _redact_ipv6(match)
    if out != match.group(0):
        report.note('ip')
    return out


def _redact_card(match: re.Match[str], report: RedactionReport) -> str:
    digits = re.sub(r'\D', '', match.group(0))
    if 13 <= len(digits) <= 19 and _luhn_ok(digits):
        report.note('card')
        return '[REDACTED_CARD]'
    return match.group(0)


def sanitize_log_text(text: str, sensitive_values: Iterable[str] = ()) -> str:
    """Diagnostic-profile scrubbing, kept as the name the crash reporter uses."""
    return sanitize_text(text, sensitive_values, profile=Profile.DIAGNOSTIC)


# ─────────────────────────────────────────────────────────────────────────────
# The AI choke point
# ─────────────────────────────────────────────────────────────────────────────

#: Hard ceiling on one prompt. Data minimisation with teeth: the scraper's
#: structured-data sections have no length limit of their own, and a page that
#: long is not carrying bean facts any more.
MAX_PROMPT_CHARS: Final[int] = 32_000

_TRUNCATION_NOTE: Final[str] = '\n\n[…truncated by TilauScope before sending…]'


def _cap(text: str, limit: int, report: RedactionReport) -> str:
    if len(text) <= limit:
        return text
    report.truncated_chars += len(text) - limit
    return text[:limit] + _TRUNCATION_NOTE


def prepare_ai_messages(system_prompt: str,
                        user_content: str,
                        *,
                        task: str = '',
                        limit: int = MAX_PROMPT_CHARS,
                        ) -> tuple[list[dict[str, str]], RedactionReport]:
    """Build the message list for a model request, scrubbed and capped.

    Every AI call site in TilauScope goes through here — the system prompt too,
    because ours interpolate runtime values such as the roaster's name. Returns
    the messages and a report of what was taken out, which the caller logs and
    may show before sending.
    """
    report = RedactionReport()
    known  = runtime_sensitive_values()

    system = sanitize_text(system_prompt, known,
                           profile=Profile.AI_OUTBOUND, report=report)
    user   = sanitize_text(user_content, known,
                           profile=Profile.AI_OUTBOUND, report=report)
    user   = _cap(user, limit, report)

    if not report.is_clean:
        _log.info('AI payload sanitized%s: %s',
                  f' for {task}' if task else '', report.summary())

    return ([{'role': 'system', 'content': system},
             {'role': 'user',   'content': user}], report)
