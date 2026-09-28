"""Site-list check via GetMappingData (README: Other endpoints; Maintenance).

The server's map lists the monitoring sites. If that list stops matching SITES in config.py, a site has been added,
renamed or removed, and the log says so. It's a warning only: collection carries on with the configured sites.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from extractor import client, config
from extractor.backup import local_now
from extractor.client import FetchError, RequestFailed
from extractor.session import SessionError

log = logging.getLogger(__name__)


def parse(body):
    """The site names (the last part of each feature's asset path) in a GetMappingData body."""
    try:
        data = json.loads(body)
        if isinstance(data, str):
            data = json.loads(data)
        paths = [feature["GroupSelectionResult"] for layer in data["layers"] for feature in layer["features"]]
    except (ValueError, KeyError, TypeError) as e:
        raise RequestFailed(f"unexpected GetMappingData response: {e!r}") from None
    sites = {[part for part in path.split("\\") if part][-1] for path in paths if isinstance(path, str) and path}
    if not sites:
        raise RequestFailed("GetMappingData listed no sites")
    return sites


def fetch(session):
    """The site names the server lists now. Raises FetchError or SessionError."""
    end = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    form = {"input": json.dumps(config.MAP_INPUT), "start": (end - timedelta(hours=1)).isoformat(),
            "end": end.isoformat()}
    return client.post(session, config.MAP_URL, form, parse)


def compare(found):
    """(new on the server, no longer on the server), each sorted."""
    return sorted(found - set(config.SITES)), sorted(set(config.SITES) - found)


def check(session):
    """Fetch the site list, log whether it matches, and return (new, gone)."""
    new, gone = compare(fetch(session))
    if new or gone:
        log.warning("site list changed: new on the server: %s; no longer on the server: %s. "
                    "Collection continues with the configured sites; update SITES in extractor/config.py "
                    "(README: When a site is added, renamed or removed)", new or "none", gone or "none")
    else:
        log.info("site list matches (%d sites)", len(config.SITES))
    return new, gone


def daily_check(session, path=config.SITES_CHECKED_PATH, now=None):
    """Run check() once per Sydney date. A failed check is logged and retried on the next run."""
    today = (now or local_now()).date().isoformat()
    try:
        if path.read_text().strip() == today:
            return
    except FileNotFoundError:
        pass
    try:
        check(session)
    except (FetchError, SessionError) as e:
        log.warning("site-list check failed; will try again next run: %s", e)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(today + "\n")
