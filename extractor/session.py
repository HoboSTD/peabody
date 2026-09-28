"""Token + cookie handling (README: Getting a session; Session and failures)."""
import json
import logging
import os
import re

import requests

from extractor import config

log = logging.getLogger(__name__)

TOKEN_INPUT = re.compile(r'<input[^>]*name="__RequestVerificationToken"[^>]*>')
VALUE = re.compile(r'value="([^"]+)"')


class SessionError(Exception):
    """Couldn't get a token: likely a Cloudflare challenge or a site change. Fatal."""


def extract_token(html):
    """Return the first __RequestVerificationToken in the page, or None."""
    tag = TOKEN_INPUT.search(html)
    value = VALUE.search(tag.group(0)) if tag else None
    return value.group(1) if value else None


class Session:
    """An HTTP session carrying the anti-forgery token and cookie, cached in state/session.json."""

    def __init__(self, path=config.SESSION_PATH, http=None):
        self.path = path
        self.http = http or requests.Session()
        self.http.headers["User-Agent"] = config.USER_AGENT
        self.token = None
        self._load()

    def _load(self):
        try:
            saved = json.loads(self.path.read_text())
            self.token = saved["token"]
            self.http.cookies.update(saved["cookies"])
        except FileNotFoundError:
            pass
        except (ValueError, KeyError, TypeError) as e:
            log.warning("ignoring unreadable %s: %s", self.path, e)

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"token": self.token, "cookies": self.http.cookies.get_dict()}, f)
        tmp.replace(self.path)

    def ensure(self):
        """Make sure there's a token, fetching one if nothing is cached."""
        if not self.token:
            self.refresh()

    def refresh(self):
        """Load the home page for a new token and cookie, and cache them. Raises SessionError."""
        log.info("refreshing session token")
        self.http.cookies.clear()
        try:
            response = self.http.get(config.BASE_URL + "/", timeout=config.TIMEOUT)
        except requests.RequestException as e:
            raise SessionError(f"GET {config.BASE_URL}/ failed: {e}") from e
        if response.status_code != 200:
            raise SessionError(f"GET {config.BASE_URL}/ returned HTTP {response.status_code}: "
                               f"{response.text[:500]!r}")
        token = extract_token(response.text)
        if not token:
            raise SessionError(f"no __RequestVerificationToken in {config.BASE_URL}/ "
                               f"(HTTP 200, {len(response.text)} bytes): {response.text[:500]!r}")
        if not self.http.cookies:
            raise SessionError(f"GET {config.BASE_URL}/ set no cookie")
        self.token = token
        self._save()
