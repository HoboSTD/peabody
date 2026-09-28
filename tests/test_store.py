"""Tests for the write-once upsert (README: Storage). Run: .venv/bin/python -m unittest"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from extractor import store

SITE, PH = "Downstream", "ph"
T0 = 1_790_236_800  # a 15-minute boundary


def series(values, site=SITE, parameter=PH, start=T0):
    """Readings at 15-minute steps from start."""
    return [(site, parameter, start + 900 * i, v) for i, v in enumerate(values)]


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "readings.db"
        self.conn = store.connect(self.path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def rows(self):
        return self.conn.execute(
            "SELECT site, parameter, ts, value, fetched_at FROM readings ORDER BY site, parameter, ts").fetchall()

    def values(self, site=SITE, parameter=PH):
        return [v for (v,) in self.conn.execute(
            "SELECT value FROM readings WHERE site = ? AND parameter = ? ORDER BY ts", (site, parameter))]

    def test_inserts_values_and_nulls(self):
        result = store.upsert(self.conn, series([7.7, None, 7.6]), now=1)
        self.assertEqual(result.inserted, 3)
        self.assertEqual(self.values(), [7.7, None, 7.6])

    def test_rerunning_same_window_changes_nothing(self):
        store.upsert(self.conn, series([7.7, None, 7.6]), now=1)
        before = self.rows()
        changes_before = self.conn.total_changes
        result = store.upsert(self.conn, series([7.7, None, 7.6]), now=2)
        self.assertEqual(result.unchanged, 3)
        self.assertEqual(self.conn.total_changes, changes_before)  # no row written at all
        self.assertEqual(self.rows(), before)  # fetched_at not bumped either

    def test_empty_response_writes_nothing(self):
        store.upsert(self.conn, series([7.7, 7.6]), now=1)
        before = self.rows()
        result = store.upsert(self.conn, [], now=2)
        self.assertEqual(result, store.UpsertResult())
        self.assertEqual(self.rows(), before)

    def test_empty_series_leaves_that_series_alone(self):
        store.upsert(self.conn, series([7.7, 7.6]) + series([500.0], parameter="turbidity"), now=1)
        # Next response only has pH (turbidity came back as values: []).
        store.upsert(self.conn, series([7.7, 7.6, 7.5]), now=2)
        self.assertEqual(self.values(parameter="turbidity"), [500.0])

    def test_null_never_overwrites_a_value(self):
        store.upsert(self.conn, series([7.7, 7.6]), now=1)
        result = store.upsert(self.conn, series([None, None]), now=2)
        self.assertEqual(result.kept, 2)
        self.assertEqual(self.values(), [7.7, 7.6])

    def test_value_fills_a_stored_null(self):
        store.upsert(self.conn, series([7.7, None]), now=1)
        result = store.upsert(self.conn, series([7.7, 7.65]), now=2)
        self.assertEqual((result.filled, result.kept), (1, 0))
        self.assertEqual(self.values(), [7.7, 7.65])

    def test_stored_values_are_never_changed(self):
        store.upsert(self.conn, series([7.0, 7.0, None]), now=1)
        before = self.rows()
        with self.assertLogs("extractor.store", "WARNING") as logs:
            result = store.upsert(self.conn, series([7.1, 0.0, None, 7.3]), now=2)
        self.assertEqual((result.inserted, result.filled, result.unchanged, result.kept), (1, 0, 1, 2))
        self.assertEqual(self.rows()[:3], before)  # fetched_at untouched too
        self.assertEqual(self.values(), [7.0, 7.0, None, 7.3])
        self.assertIn("stored 7.0, sent 7.1", logs.output[0])

    def test_mass_change_is_ignored_and_new_readings_still_written(self):
        store.upsert(self.conn, series([7.0] * 100), now=1)
        # A glitch returns 0.0 everywhere, alongside a genuinely new reading in another series.
        bad = series([0.0] * 100) + series([20.0], parameter="temperature")
        with self.assertLogs("extractor.store", "WARNING"):
            result = store.upsert(self.conn, bad, now=2)
        self.assertEqual((result.kept, result.inserted, len(result.samples)), (100, 1, store.SAMPLE_SIZE))
        self.assertEqual(set(self.values()), {7.0})
        self.assertEqual(self.values(parameter="temperature"), [20.0])

    def test_sql_upsert_alone_never_changes_a_value(self):
        store.upsert(self.conn, series([7.0, None]), now=1)
        self.conn.executemany(store.UPSERT, [(SITE, PH, T0, 0.0, 2), (SITE, PH, T0 + 900, 7.1, 2)])
        self.assertEqual(self.values(), [7.0, 7.1])

    def test_failed_write_rolls_back_and_connection_is_reusable(self):
        store.upsert(self.conn, series([7.0]), now=1)
        before = self.rows()
        with self.assertRaises(sqlite3.IntegrityError):  # the null ts fails mid-write, after the temperature row
            store.upsert(self.conn, series([7.5], parameter="temperature") + [(SITE, "turbidity", None, 1.0)], now=2)
        self.assertEqual(self.rows(), before)
        store.upsert(self.conn, series([20.0], parameter="temperature"), now=3)
        self.assertEqual(self.values(parameter="temperature"), [20.0])

    def test_fetched_at_records_the_last_write(self):
        store.upsert(self.conn, series([7.0, None]), now=1)
        store.upsert(self.conn, series([7.0, 7.1]), now=2)
        self.assertEqual([r[4] for r in self.rows()], [1, 2])


if __name__ == "__main__":
    unittest.main()
