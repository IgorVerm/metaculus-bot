"""Fetch a public web page as plain text, refusing anything that is not plainly public.

The URLs come from question text, which anyone can write, so every hop is checked: only http
and https, only ports 80 and 443, no credentials in the URL, and every address the host name
resolves to must be a public internet address. Redirects are followed by hand so each new
location goes through the same check. Known gap: the name is resolved once for the check and
again by the connection, so a host that changes its answer in between is not caught.
"""

import ipaddress
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urljoin, urlsplit

USER_AGENT = "metaculus-bot (+https://github.com/IgorVerm/metaculus-bot)"
ALLOWED_PORTS = {80, 443}
MAX_BYTES = 400_000
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 10
TEXT_TYPES = ("text/", "application/json", "application/xml", "application/xhtml+xml")
SKIPPED_TAGS = {"script", "style", "noscript", "template", "svg", "head"}

Resolver = Callable[..., list]


def refusal_reason(url: str, resolver: Resolver = socket.getaddrinfo) -> str | None:
    """Why this URL must not be fetched, or None when it may be."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return "scheme is not http or https"
    if parts.username or parts.password:
        return "URL carries credentials"
    host = parts.hostname
    if not host:
        return "no host"
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return "invalid port"
    if port not in ALLOWED_PORTS:
        return f"port {port} is not allowed"
    try:
        answers = resolver(host, None)
    except OSError:
        return "host does not resolve"
    if not answers:
        return "host does not resolve"
    for answer in answers:
        address = ipaddress.ip_address(answer[4][0].split("%")[0])
        if not address.is_global or address.is_multicast:
            return "host resolves to a non-public address"
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in SKIPPED_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self.chunks.append(data.strip())


def html_to_text(html: str) -> str:
    """Visible text of an HTML page, one space between fragments."""
    extractor = _TextExtractor()
    extractor.feed(html)
    return " ".join(" ".join(extractor.chunks).split())


def fetch_text(url: str, resolver: Resolver = socket.getaddrinfo) -> str | None:
    """The page's text, or None when it is refused, unreachable or not text."""
    opener = urllib.request.build_opener(_NoRedirect)
    for _ in range(MAX_REDIRECTS + 1):
        if refusal_reason(url, resolver):
            return None
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                content_type = response.headers.get("Content-Type", "").lower()
                if not content_type.startswith(TEXT_TYPES):
                    return None
                raw = response.read(MAX_BYTES)
                charset = response.headers.get_content_charset() or "utf-8"
        except urllib.error.HTTPError as error:
            location = error.headers.get("Location") if error.headers else None
            if error.code in (301, 302, 303, 307, 308) and location:
                url = urljoin(url, location)
                continue
            return None
        except (OSError, ValueError):
            return None
        text = raw.decode(charset, errors="replace")
        return html_to_text(text) if "html" in content_type else " ".join(text.split())
    return None
