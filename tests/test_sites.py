"""Tests for the site-list check (README: Other endpoints; Maintenance), using a saved GetMappingData response. No live calls."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from extractor import sites
from extractor.client import FetchError, RequestFailed
from extractor.session import Session
from tests.test_client import FakeHttp, fixture, response

NOW = datetime(2026, 9, 27, 21, 30, tzinfo=ZoneInfo("Australia/Sydney"))
CONFIGURED = {"Upstream", "LDP7 Water Treatment Plant", "LDP8 Turkeys Nest", "Downstream"}


def site_list(*paths):
    return json.dumps({"layers": [{"features": [{"GroupSelectionResult": p} for p in paths]}]})


class ParseTest(unittest.TestCase):
    def test_saved_response(self):
        self.assertEqual(sites.parse(fixture("site-list.json")), CONFIGURED)

    def test_path_forms(self):
        # the saved response has a doubled backslash; a single one, or a double-encoded body, work too
        self.assertEqual(sites.parse(site_list("Metropolitan Water Monitoring\\\\Upstream",
                                               "Metropolitan Water Monitoring\\New Site")), {"Upstream", "New Site"})
        self.assertEqual(sites.parse(json.dumps(site_list("A\\Upstream"))), {"Upstream"})

    def test_bad_responses(self):
        for body in ("<html>", "[]", json.dumps({"layers": [{}]}), site_list()):
            with self.assertRaises(RequestFailed):
                sites.parse(body)

    def test_compare(self):
        renamed = CONFIGURED - {"Upstream"} | {"Upstream Creek"}
        self.assertEqual(sites.compare(renamed), (["Upstream Creek"], ["Upstream"]))
        self.assertEqual(sites.compare(CONFIGURED), ([], []))


class DailyCheckTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "state" / "sites-checked"

    def run_check(self, map_response=None, now=NOW):
        http = FakeHttp(map_response=map_response)
        with self.assertLogs("extractor", "INFO") as logs:
            sites.daily_check(Session(path=self.dir / "session.json", http=http), self.path, now=now)
        return http.map_posts, logs.output

    def test_once_per_sydney_date(self):
        posts, logs = self.run_check()
        self.assertEqual(posts, 1)
        self.assertTrue(any("site list matches (4 sites)" in line for line in logs))
        self.assertEqual(self.path.read_text(), "2026-09-27\n")
        with self.assertRaises(AssertionError):  # nothing logged: no request made
            self.run_check(now=NOW + timedelta(hours=2))
        self.assertEqual(self.run_check(now=NOW + timedelta(hours=3))[0], 1)  # 00:30 the next day

    def test_a_changed_list_is_a_warning(self):
        posts, logs = self.run_check(response(200, site_list("M\\Upstream", "M\\Downstream", "M\\New Site")))
        self.assertTrue(any("WARNING" in line and "new on the server: ['New Site']" in line
                            and "'LDP7 Water Treatment Plant', 'LDP8 Turkeys Nest'" in line for line in logs))
        self.assertTrue(self.path.exists())  # warned once for the day

    def test_a_failed_check_is_retried_next_run(self):
        posts, logs = self.run_check(response(500, "oops"))
        self.assertEqual(posts, 2)  # the usual refresh and one retry
        self.assertTrue(any("site-list check failed; will try again next run" in line for line in logs))
        self.assertFalse(self.path.exists())

    def test_check_raises_for_the_check_command(self):
        http = FakeHttp(map_response=response(500, "oops"))
        with self.assertLogs("extractor", "WARNING"), self.assertRaises(FetchError):
            sites.check(Session(path=self.dir / "session.json", http=http))


if __name__ == "__main__":
    unittest.main()
