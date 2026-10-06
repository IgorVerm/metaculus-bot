"""Fetch a public web page as plain text, refusing anything that is not plainly public.

The URLs come from question text, which anyone can write, so every hop is checked: only http
and https, only ports 80 and 443, no credentials in the URL, and every address the host name
resolves to must be a public internet address. Redirects are followed by hand so each new
location goes through the same check. Known gap: the name is resolved once for the check and
again by the connection, so a host that changes its answer in between is not caught.
"""

import ipaddress
import socket
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urljoin, urlsplit

USER_AGENT = "metaculus-bot (+https://github.com/IgorVerm/metaculus-bot)"
ALLOWED_PORTS = {80, 443}
MAX_BYTES = 400_000
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 10  # per network operation
TOTAL_SECONDS = 30  # for one page, redirects included
CHUNK_BYTES = 16_384
# Public by the address rules, but the cloud provider's internal service on GitHub's runners.
REFUSED_ADDRESSES = {"168.63.129.16"}
TEXT_TYPES = ("text/", "application/json", "application/xml", "application/xhtml+xml")
SKIPPED_TAGS = {"script", "style", "noscript", "template", "svg", "head"}

Resolver = Callable[..., list]


def refusal_reason(url: str, resolver: Resolver = socket.getaddrinfo) -> str | None:
    """Why this URL must not be fetched, or None when it may be."""
    try:
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return "malformed URL"
    if parts.scheme not in ("http", "https"):
        return "scheme is not http or https"
    if parts.username or parts.password:
        return "URL carries credentials"
    host = parts.hostname
    if not host:
        return "no host"
    if port not in ALLOWED_PORTS:
        return f"port {port} is not allowed"
    try:
        answers = resolver(host, None)
    except OSError:
        return "host does not resolve"
    if not answers:
        return "host does not resolve"
    for answer in answers:
        try:
            address = ipaddress.ip_address(answer[4][0].split("%")[0])
        except ValueError:
            return "host resolves to an unreadable address"
        if not address.is_global or address.is_multicast or str(address) in REFUSED_ADDRESSES:
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


def fetch_text(
    url: str,
    resolver: Resolver = socket.getaddrinfo,
    opener: urllib.request.OpenerDirector | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> str | None:
    """The page's text, or None when it is refused, unreachable, too slow or not plain text."""
    opener = opener or urllib.request.build_opener(_NoRedirect)
    deadline = clock() + TOTAL_SECONDS
    for _ in range(MAX_REDIRECTS + 1):
        if refusal_reason(url, resolver):
            return None
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        )
        try:
            with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                content_type = response.headers.get("Content-Type", "").lower()
                encoding = response.headers.get("Content-Encoding", "identity").lower()
                if not content_type.startswith(TEXT_TYPES) or encoding != "identity":
                    return None
                raw = b""
                while len(raw) < MAX_BYTES:
                    if clock() > deadline:
                        return None
                    chunk = response.read(min(CHUNK_BYTES, MAX_BYTES - len(raw)))
                    if not chunk:
                        break
                    raw += chunk
                charset = response.headers.get_content_charset() or "utf-8"
        except urllib.error.HTTPError as error:
            location = error.headers.get("Location") if error.headers else None
            if error.code in (301, 302, 303, 307, 308) and location and clock() <= deadline:
                url = urljoin(url, location)
                continue
            return None
        except Exception:  # noqa: BLE001 - any network or protocol failure means "no page"
            return None
        try:
            text = raw.decode(charset, errors="replace")
        except LookupError:  # the page named a character set Python does not know
            text = raw.decode("utf-8", errors="replace")
        return html_to_text(text) if "html" in content_type else " ".join(text.split())
    return None
