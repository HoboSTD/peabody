"""Tests for the session and client (README: API reference; Session and failures), using saved responses. No live calls."""
import fcntl
import json
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import requests

from extractor import cli, client, config, store
from extractor.client import FetchError, RequestFailed
from extractor.session import Session, SessionError, extract_token

FIXTURES = Path(__file__).parent / "fixtures"
PAGE = '<html><form><input name="__RequestVerificationToken" type="hidden" value="TOKEN-{n}" /></form></html>'
COOKIE = "__orchantiforgery_test"
DOWNSTREAM_PH = [s for s in config.SERIES if s[:2] == ("Downstream", "ph")]
START = datetime(2026, 9, 24, 8, tzinfo=timezone.utc)
END = datetime(2026, 9, 25, 8, tzinfo=timezone.utc)


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def response(status, text):
    r = requests.Response()
    r.status_code = status
    r._content = text.encode("utf-8")
    r.encoding = "utf-8"
    return r


class FakeHttp(requests.Session):
    """The home page hands out a new token and cookie on each GET. GetTrendValues POSTs return queued responses;
    GetMappingData returns map_response (the saved site list unless set)."""

    def __init__(self, posts=(), home_status=200, map_response=None):
        super().__init__()
        self.posts = list(posts)
        self.home_status = home_status
        self.map_response = map_response
        self.map_posts = 0
        self.gets = 0
        self.sent = []  # (token, cookie) sent with each GetTrendValues POST
        self.forms = []  # the form data of each GetTrendValues POST

    def get(self, url, **kwargs):
        self.gets += 1
        self.cookies.set(COOKIE, f"COOKIE-{self.gets}")
        return response(self.home_status, PAGE.format(n=self.gets))

    def post(self, url, data=None, **kwargs):
        if url == config.MAP_URL:
            self.map_posts += 1
            return response(200, fixture("site-list.json")) if self.map_response is None else self.map_response
        self.sent.append((data["__RequestVerificationToken"], self.cookies.get(COOKIE)))
        self.forms.append(data)
        item = self.posts.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ParseTest(unittest.TestCase):
    def test_all_18_series(self):
        body = fixture("all-series-1-day.json")
        readings = client.parse(body, config.SERIES)
        raw = json.loads(json.loads(body))
        self.assertEqual(len(readings), sum(len(t["tags"][0]["values"]) for t in raw["trends"]))
        self.assertEqual({r[:2] for r in readings}, {s[:2] for s in config.SERIES})
        self.assertIn(("Upstream", "ph", 1790236800, 7.4724645614624023), readings)
        self.assertTrue(all(isinstance(ts, int) and ts % 900 == 0 for _, _, ts, _ in readings))

    def test_nulls_are_kept(self):
        readings = client.parse(fixture("all-series-1-day.json"), config.SERIES)
        self.assertTrue(any(v is None for *_, v in readings))

    def test_empty_values_is_not_a_failure(self):
        body = fixture("empty-values.json").replace('\\"id\\":\\"t1\\"', '\\"id\\":\\"Downstream|pH\\"')
        self.assertEqual(client.parse(body, DOWNSTREAM_PH), [])

    def test_html_error_page(self):
        with self.assertRaisesRegex(RequestFailed, "isn't JSON"):
            client.parse(fixture("http-400-error-page.html"), DOWNSTREAM_PH)

    def test_server_exception_with_http_200(self):
        with self.assertRaisesRegex(RequestFailed, "server exception"):
            client.parse(fixture("server-exception.json"), DOWNSTREAM_PH)

    def test_missing_series(self):
        extra = config.SERIES + [("Nowhere", "ph", "pH")]
        with self.assertRaisesRegex(RequestFailed, "missing series"):
            client.parse(fixture("all-series-1-day.json"), extra)

    def test_unexpected_series(self):
        with self.assertRaisesRegex(RequestFailed, "unexpected or repeated"):
            client.parse(fixture("all-series-1-day.json"), DOWNSTREAM_PH)

    def test_errors_array(self):
        body = json.dumps(json.dumps({"trends": [], "errors": ["boom"]}))
        with self.assertRaisesRegex(RequestFailed, "boom"):
            client.parse(body, DOWNSTREAM_PH)
        body = json.dumps(json.dumps({"errors": [], "trends": [
            {"id": "Downstream|pH", "tags": [{"values": [], "name": "x"}], "errors": ["tag boom"]}]}))
        with self.assertRaisesRegex(RequestFailed, "tag boom"):
            client.parse(body, DOWNSTREAM_PH)

    def test_bad_structure(self):
        for data in ({"trends": [{"id": "Downstream|pH"}], "errors": []},
                     {"trends": [{"id": "Downstream|pH", "tags": [{"values": [[1, "7.1"]]}]}], "errors": []},
                     ["not", "a", "dict"]):
            with self.assertRaises(RequestFailed):
                client.parse(json.dumps(json.dumps(data)), DOWNSTREAM_PH)


class RequestTest(unittest.TestCase):
    def test_trends_input_sends_naive_utc(self):
        sydney = ZoneInfo("Australia/Sydney")
        body = json.loads(client.trends_input(datetime(2026, 9, 25, 18, tzinfo=sydney),
                                              datetime(2026, 9, 26, 18, tzinfo=sydney), DOWNSTREAM_PH))
        self.assertEqual(body, {"trends": [{
            "starttimestamp": "2026-09-25T08:00:00", "endtimestamp": "2026-09-26T08:00:00",
            "tagName": "Metropolitan Water Monitoring\\Downstream|pH", "id": "Downstream|pH"}]})

    def test_trends_input_rejects_naive_times(self):
        with self.assertRaises(ValueError):
            client.trends_input(datetime(2026, 9, 25), END, DOWNSTREAM_PH)

    def test_extract_token(self):
        self.assertEqual(extract_token(PAGE.format(n=1)), "TOKEN-1")
        self.assertEqual(extract_token('<input type="hidden" value="A" name="__RequestVerificationToken">'), "A")
        self.assertIsNone(extract_token("<html>Checking your browser...</html>"))


class SessionRetryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "state" / "session.json"

    def session(self, http):
        return Session(path=self.path, http=http)

    def ok(self):
        return response(200, fixture("all-series-1-day.json"))

    def test_first_run_fetches_a_token_and_caches_it(self):
        http = FakeHttp([self.ok()])
        self.assertEqual(len(client.get_trends(self.session(http), START, END)), 1569)
        self.assertEqual(http.gets, 1)
        self.assertEqual(http.sent, [("TOKEN-1", "COOKIE-1")])
        self.assertEqual(json.loads(self.path.read_text()), {"token": "TOKEN-1", "cookies": {COOKIE: "COOKIE-1"}})
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_cached_session_is_reused(self):
        client.get_trends(self.session(FakeHttp([self.ok()])), START, END)
        http = FakeHttp([self.ok()])
        client.get_trends(self.session(http), START, END)
        self.assertEqual(http.gets, 0)
        self.assertEqual(http.sent, [("TOKEN-1", "COOKIE-1")])

    def test_bad_cached_token_is_refreshed_and_retried(self):
        self.path.parent.mkdir()
        self.path.write_text(json.dumps({"token": "CORRUPTED", "cookies": {COOKIE: "OLD"}}))
        http = FakeHttp([response(400, fixture("http-400-error-page.html")), self.ok()])
        client.get_trends(self.session(http), START, END)
        self.assertEqual(http.sent, [("CORRUPTED", "OLD"), ("TOKEN-1", "COOKIE-1")])
        self.assertEqual(json.loads(self.path.read_text())["token"], "TOKEN-1")

    def test_retries_after_network_error_and_http_200_exception(self):
        for first in (requests.ConnectionError("reset"), requests.Timeout("slow"),
                      response(200, fixture("server-exception.json"))):
            http = FakeHttp([first, self.ok()])
            client.get_trends(self.session(http), START, END)
            self.assertEqual(len(http.sent), 2)

    def test_second_failure_is_fatal(self):
        http = FakeHttp([response(400, fixture("http-400-error-page.html")), response(400, fixture("http-400-error-page.html"))])
        with self.assertRaisesRegex(FetchError, "failed twice.*HTTP 400"):
            client.get_trends(self.session(http), START, END)
        self.assertEqual(len(http.sent), 2)

    def test_refresh_failure_is_fatal(self):
        http = FakeHttp(home_status=403)
        with self.assertRaisesRegex(SessionError, "HTTP 403"):
            client.get_trends(self.session(http), START, END)

    def test_unreadable_cache_is_ignored(self):
        self.path.parent.mkdir()
        self.path.write_text("{not json")
        http = FakeHttp([self.ok()])
        client.get_trends(self.session(http), START, END)
        self.assertEqual(http.gets, 1)


class CliCase(unittest.TestCase):
    """Runs commands against a temporary database, backups folder and fake server."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = self.dir / "data" / "readings.db"

    def run_cli(self, command, posts, **http_args):
        self.http = FakeHttp(posts, **http_args)
        make = lambda: Session(path=self.dir / "session.json", http=self.http)
        self.sleep = mock.Mock()
        with mock.patch.object(cli, "Session", make), mock.patch.object(config, "DB_PATH", self.db), \
                mock.patch.object(config, "BACKUP_DIR", self.dir / "backups"), \
                mock.patch.object(config, "OUTPUT_DIR", self.dir / "output"), \
                mock.patch.object(config, "LOCK_PATH", self.dir / "state" / "run.lock"), \
                mock.patch.object(config, "SITES_CHECKED_PATH", self.dir / "state" / "sites-checked"), \
                mock.patch.object(cli.time, "sleep", self.sleep), \
                mock.patch("sys.stdout"), mock.patch("logging.basicConfig"), \
                self.assertLogs("extractor", "INFO") as logs:
            return cli.main(command.split()), logs.output

    def db_rows(self):
        conn = store.connect(self.db)
        self.addCleanup(conn.close)
        return conn.execute("SELECT site, parameter, ts, value FROM readings").fetchall()


class CliTest(CliCase):
    def test_check_succeeds_and_writes_nothing(self):
        code, _ = self.run_cli("check", [response(200, fixture("all-series-1-day.json"))])
        self.assertEqual(code, 0)
        self.assertFalse(self.db.exists())
        self.assertFalse((self.dir / "output").exists())

    def test_export_writes_csvs_without_the_network(self):
        self.run_cli("fetch", [response(200, fixture("all-series-1-day.json"))])
        (self.dir / "output" / "upstream.csv").unlink()
        code, _ = self.run_cli("export", [])
        self.assertEqual(code, 0)
        self.assertEqual(self.http.forms, [])
        rows = (self.dir / "output" / "upstream.csv").read_text().splitlines()
        upstream = {ts for site, _, ts, _ in client.parse(fixture("all-series-1-day.json"), config.SERIES)
                    if site == "Upstream"}
        self.assertEqual(len(rows), 1 + len(upstream))  # header + one row per stored timestamp
        self.assertTrue(rows[1].startswith("2026-09-24T08:00:00Z,2026-09-24T18:00:00+10:00,7.472464561462402"))

    def test_second_failure_exits_non_zero(self):
        for command in ("check", "fetch"):
            code, logs = self.run_cli(command, [response(400, "<html>"), response(400, "<html>")])
            self.assertEqual(code, 1)
            self.assertTrue(any("FetchError" in line for line in logs))
        self.assertFalse(self.db.exists())

    def test_fetch_stores_readings_and_rerun_changes_nothing(self):
        body = fixture("all-series-1-day.json")
        code, logs = self.run_cli("fetch", [response(200, body)])
        self.assertEqual(code, 0)
        rows = self.db_rows()
        self.assertEqual(len(rows), 1569)
        self.assertEqual(sorted(rows), sorted(client.parse(body, config.SERIES)))
        self.assertEqual(sum("GetTrendValues" in line for line in logs), 1)  # one request per run
        self.assertEqual(len(list((self.dir / "output").glob("*.csv"))), 4)  # CSVs rewritten after the write
        self.assertLess(logs.index(next(l for l in logs if "upsert:" in l)),
                        logs.index(next(l for l in logs if "export: wrote" in l)))
        self.assertFalse((self.dir / "backups").exists())  # nothing to back up before the first write

        code, logs = self.run_cli("fetch", [response(200, body)])
        self.assertEqual(code, 0)
        self.assertTrue(any("inserted=0 filled=0 unchanged=1569 kept=0" in line for line in logs))
        (daily,) = (self.dir / "backups").iterdir()  # the second run backed up before writing
        self.assertLess(logs.index(next(l for l in logs if "backup: wrote" in l)),
                        logs.index(next(l for l in logs if "upsert:" in l)))
        self.assertRegex(daily.name, r"^readings-\d{4}-\d{2}-\d{2}\.db\.gz$")

    def test_fetch_never_changes_stored_values(self):
        body = fixture("all-series-1-day.json")
        self.run_cli("fetch", [response(200, body)])
        before = self.db_rows()
        zeroed = json.loads(json.loads(body))
        for trend in zeroed["trends"]:
            trend["tags"][0]["values"] = [[ts, 0.0] for ts, _ in trend["tags"][0]["values"]]
        code, logs = self.run_cli("fetch", [response(200, json.dumps(json.dumps(zeroed)))])
        self.assertEqual(code, 0)
        self.assertTrue(any("stored values kept" in line for line in logs))
        after = {row[:3]: row[3] for row in self.db_rows()}
        for site, parameter, ts, value in before:  # stored values kept; stored nulls filled with 0.0
            self.assertEqual(after[(site, parameter, ts)], 0.0 if value is None else value)


class HardeningTest(CliCase):
    def ok(self):
        return response(200, fixture("all-series-1-day.json"))

    def test_fetch_checks_the_site_list_once_a_day(self):
        code, logs = self.run_cli("fetch", [self.ok()])
        self.assertEqual((code, self.http.map_posts), (0, 1))
        self.assertTrue(any("site list matches" in line for line in logs))
        self.assertLess(logs.index(next(l for l in logs if "export: wrote" in l)),
                        logs.index(next(l for l in logs if "site list" in l)))  # only after the data is stored
        self.run_cli("fetch", [self.ok()])
        self.assertEqual(self.http.map_posts, 0)

    def test_a_failed_site_check_does_not_fail_fetch(self):
        code, logs = self.run_cli("fetch", [self.ok()], map_response=response(500, "oops"))
        self.assertEqual(code, 0)
        self.assertEqual(len(self.db_rows()), 1569)
        self.assertTrue(any("site-list check failed" in line for line in logs))

    def test_check_command_reports_a_changed_site_list(self):
        changed = response(200, json.dumps({"layers": [{"features": [{"GroupSelectionResult": "M\\Upstream"}]}]}))
        code, logs = self.run_cli("check", [self.ok()], map_response=changed)
        self.assertEqual(code, 0)
        self.assertTrue(any("site list changed" in line for line in logs))

    def test_stale_warning(self):
        now = datetime(2026, 9, 25, 8, tzinfo=timezone.utc)
        readings = [("Upstream", "ph", int(now.timestamp()) - 3 * 3600, 7.0), ("Upstream", "ph", int(now.timestamp()), None)]
        with self.assertRaises(AssertionError), self.assertLogs("extractor", "WARNING"):
            cli.warn_if_stale(readings, now)  # 3 hours old: normal, no warning
        with self.assertLogs("extractor", "WARNING") as logs:
            cli.warn_if_stale(readings, now + timedelta(hours=10))
        self.assertIn("newest value is 13.0 hours old (2026-09-25 05:00 UTC)", logs.output[0])
        with self.assertLogs("extractor", "WARNING") as logs:
            cli.warn_if_stale([("Upstream", "ph", 1, None)], now)
        self.assertIn("no values at any site in the last 24 hours", logs.output[0])

    def test_only_one_run_at_a_time(self):
        lock = self.dir / "state" / "run.lock"
        lock.parent.mkdir(parents=True)
        with open(lock, "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)  # e.g. a backfill in progress
            code, logs = self.run_cli("fetch", [self.ok()])
        self.assertEqual(code, 1)
        self.assertTrue(any("another run is in progress" in line for line in logs))
        self.assertEqual(self.http.sent, [])
        self.assertEqual(self.run_cli("fetch", [self.ok()])[0], 0)  # released: runs normally


class BackfillTest(CliCase):
    def ok(self):
        return response(200, fixture("all-series-1-day.json"))

    def windows(self):
        """(start, end) sent in each request."""
        return [(t["starttimestamp"], t["endtimestamp"])
                for t in (json.loads(f["trendsinput"])["trends"][0] for f in self.http.forms)]

    def test_month_chunks(self):
        utc = lambda *a: datetime(*a, tzinfo=timezone.utc)
        self.assertEqual(cli.month_chunks(utc(2025, 11, 15), utc(2026, 2, 3, 6)), [
            (utc(2025, 11, 15), utc(2025, 12, 1)), (utc(2025, 12, 1), utc(2026, 1, 1)),
            (utc(2026, 1, 1), utc(2026, 2, 1)), (utc(2026, 2, 1), utc(2026, 2, 3, 6))])
        self.assertEqual(cli.month_chunks(utc(2026, 1, 1), utc(2026, 1, 1)), [])

    def test_walks_months_and_pauses_between_requests(self):
        code, logs = self.run_cli("backfill --from 2026-07-15 --to 2026-09-10", [self.ok(), self.ok(), self.ok()])
        self.assertEqual(code, 0)
        self.assertEqual(self.windows(), [("2026-07-15T00:00:00", "2026-08-01T00:00:00"),
                                          ("2026-08-01T00:00:00", "2026-09-01T00:00:00"),
                                          ("2026-09-01T00:00:00", "2026-09-10T00:00:00")])
        self.assertEqual(self.sleep.call_args_list, [mock.call(config.BACKFILL_PAUSE)] * 2)
        self.assertEqual(len(self.db_rows()), 1569)
        self.assertTrue(any("earliest stored reading: 2026-09-24 08:00 UTC" in line for line in logs))
        self.assertEqual(len(list((self.dir / "output").glob("*.csv"))), 4)
        self.assertFalse((self.dir / "backups").exists())  # the database was empty

    def test_backs_up_existing_data_first(self):
        self.run_cli("fetch", [self.ok()])
        code, logs = self.run_cli("backfill --from 2026-09-01 --to 2026-09-10", [self.ok()])
        self.assertEqual(code, 0)
        (path,) = (p for p in (self.dir / "backups").iterdir() if "backfill" in p.name)
        self.assertLess(logs.index(next(l for l in logs if "backup: wrote" in l)),
                        logs.index(next(l for l in logs if "GetTrendValues" in l)))

    def test_local_backups_can_be_turned_off(self):
        with mock.patch.object(config, "LOCAL_BACKUPS", False):
            self.run_cli("fetch", [self.ok()])
            self.assertEqual(self.run_cli("fetch", [self.ok()])[0], 0)
            self.assertEqual(self.run_cli("backfill --from 2026-09-01 --to 2026-09-10", [self.ok()])[0], 0)
        self.assertFalse((self.dir / "backups").exists())

    def test_failure_keeps_earlier_months_and_says_where_to_resume(self):
        bad = lambda: response(400, fixture("http-400-error-page.html"))
        code, logs = self.run_cli("backfill --from 2026-07-15 --to 2026-09-10", [self.ok(), bad(), bad()])
        self.assertEqual(code, 1)
        self.assertEqual(len(self.db_rows()), 1569)
        self.assertTrue(any("stopped at 2026-08" in line and "backfill --from 2026-08-01" in line for line in logs))

    def test_bad_dates(self):
        with mock.patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                cli.main(["backfill", "--from", "2026-13-01"])
        code, logs = self.run_cli("backfill --from 2026-09-10 --to 2026-09-01", [])
        self.assertEqual(code, 1)
        self.assertEqual(self.http.forms, [])


if __name__ == "__main__":
    unittest.main()
