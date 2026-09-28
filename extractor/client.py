"""GetTrendValues: request, response checks, and one refresh-and-retry (README: GetTrendValues; Session and failures)."""
import json
import logging
from datetime import timezone

import requests

from extractor import config

log = logging.getLogger(__name__)


class RequestFailed(Exception):
    """One attempt failed. get_trends() refreshes the session and retries once."""


class FetchError(Exception):
    """A request failed twice. Fatal."""


def series_id(site, attribute):
    return f"{site}|{attribute}"


def trends_input(start, end, series):
    """The trendsinput JSON for these series, with start and end (aware datetimes) sent as naive UTC."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    start_utc, end_utc = (t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") for t in (start, end))
    return json.dumps({"trends": [
        {"starttimestamp": start_utc, "endtimestamp": end_utc,
         "tagName": f"{config.ASSET_ROOT}\\{site}|{attribute}", "id": series_id(site, attribute)}
        for site, _, attribute in series]})


def parse(body, series):
    """Decode a GetTrendValues body into (site, parameter, ts_seconds, value) readings.

    Raises RequestFailed unless every requested series comes back exactly once with no errors.
    Empty values and nulls are data, not failures.
    """
    try:
        data = json.loads(body)
        if isinstance(data, str):  # the body is a JSON string containing JSON
            data = json.loads(data)
    except ValueError:
        raise RequestFailed("body isn't JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("trends"), list):
        if isinstance(data, dict) and "Message" in data:  # .NET exception, sent with HTTP 200
            raise RequestFailed(f"server exception: {data.get('Message')} {data.get('ExceptionMessage')}")
        raise RequestFailed("body has no trends list")
    if data.get("errors"):
        raise RequestFailed(f"errors: {data['errors']}")

    wanted = {series_id(site, attribute): (site, parameter) for site, parameter, attribute in series}
    seen = set()
    readings = []
    try:
        for trend in data["trends"]:
            key = wanted.get(trend["id"])
            if key is None or key in seen:
                raise RequestFailed(f"unexpected or repeated trend id {trend['id']!r}")
            if trend.get("errors"):
                raise RequestFailed(f"errors for {trend['id']}: {trend['errors']}")
            (tag,) = trend["tags"]
            seen.add(key)
            for ts_ms, value in tag["values"]:
                if (not isinstance(ts_ms, int) or isinstance(value, bool)
                        or not (value is None or isinstance(value, (int, float)))):
                    raise RequestFailed(f"bad value in {trend['id']}: {[ts_ms, value]!r}")
                readings.append((*key, ts_ms // 1000, None if value is None else float(value)))
    except (KeyError, TypeError, ValueError) as e:
        raise RequestFailed(f"unexpected response structure: {e!r}") from None
    missing = set(wanted.values()) - seen
    if missing:
        raise RequestFailed(f"missing series: {sorted(missing)}")
    return readings


def _attempt(session, url, form, parse_body):
    try:
        response = session.http.post(url, data={"__RequestVerificationToken": session.token, **form},
                                     timeout=config.TIMEOUT)
    except requests.RequestException as e:
        raise RequestFailed(f"network error: {e}") from e
    if response.status_code != 200:
        raise RequestFailed(f"HTTP {response.status_code}; body: {response.text[:500]!r}")
    try:
        return parse_body(response.text)
    except RequestFailed as e:
        raise RequestFailed(f"{e}; HTTP 200; body: {response.text[:500]!r}") from None


def post(session, url, form, parse_body):
    """POST the form with the session token and return parse_body(body).

    On any failure: refresh the session and retry once. Raises FetchError if the retry fails too,
    or SessionError if the refresh fails.
    """
    session.ensure()
    for attempt in (1, 2):
        try:
            return _attempt(session, url, form, parse_body)
        except RequestFailed as e:
            if attempt == 2:
                raise FetchError(f"POST {url} failed twice: {e}") from e
            log.warning("%s failed, refreshing session and retrying: %s", url.rsplit("/", 1)[-1], e)
            session.refresh()


def get_trends(session, start, end, series=config.SERIES):
    """Fetch raw readings for these series between start and end (aware datetimes, both included)."""
    form = {"dataserver": config.DATASERVER, "trendsinput": trends_input(start, end, series),
            "overrideTimezoneID": config.TIMEZONE_ID}
    readings = post(session, config.TRENDS_URL, form, lambda body: parse(body, series))
    log.info("GetTrendValues %s to %s: %d series, %d readings", start.isoformat(), end.isoformat(),
             len(series), len(readings))
    return readings
