"""Tests for the pollution-indicator metrics (README: Metrics)."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from extractor import config, metrics, store

WTP = "LDP7 Water Treatment Plant"
TN = "LDP8 Turkeys Nest"


def ts(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())


def at(day, hour=0, minute=0):
    """A timestamp on 2024-01-<day> (UTC), for building a series across several days."""
    return ts(f"2024-01-{day:02d} {hour:02d}:{minute:02d}:00")


class SanitizeTest(unittest.TestCase):
    def test_keeps_values_inside_bounds(self):
        self.assertTrue(metrics.sanitize("ph", 7.0))
        self.assertTrue(metrics.sanitize("specific_conductivity", 460.0))
        self.assertTrue(metrics.sanitize("turbidity", 0.0))

    def test_rejects_values_outside_bounds(self):
        self.assertFalse(metrics.sanitize("ph", -156931.7))      # a real fault value seen in the data
        self.assertFalse(metrics.sanitize("ph", 22.9))
        self.assertFalse(metrics.sanitize("specific_conductivity", 1.0))   # sensor stuck at (near) zero
        self.assertFalse(metrics.sanitize("specific_conductivity", 1882993.0))  # a real LDP7 fault value
        self.assertFalse(metrics.sanitize("turbidity", -502.0))

    def test_rejects_null(self):
        self.assertFalse(metrics.sanitize("ph", None))

    def test_parameter_with_no_bounds_is_never_rejected(self):
        self.assertTrue(metrics.sanitize("flow_volume", -1.0))
        self.assertTrue(metrics.sanitize("flow_volume", 1_000_000.0))


class MetricsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name) / "output"
        self.conn = store.connect(Path(tmp.name) / "readings.db")
        self.addCleanup(self.conn.close)

    def seed(self, readings):
        store.upsert(self.conn, readings, now=1)

    def test_ratio_series_pairs_shared_timestamps_and_drops_bad_values(self):
        self.seed([
            ("Upstream", "specific_conductivity", at(1, 0, 0), 200.0),
            ("Downstream", "specific_conductivity", at(1, 0, 0), 400.0),
            ("Upstream", "specific_conductivity", at(1, 0, 15), 1.0),       # sanitize rejects: stuck near zero
            ("Downstream", "specific_conductivity", at(1, 0, 15), 500.0),
            ("Upstream", "specific_conductivity", at(1, 0, 30), 250.0),     # no matching Downstream reading
        ])
        self.assertEqual(metrics.ratio_series(self.conn), [(at(1, 0, 0), 2.0)])

    def test_ph_excursions_outside_licence_band(self):
        self.seed([
            (WTP, "ph", at(1, 0, 0), 7.0),    # inside 6.5-8.5
            (WTP, "ph", at(1, 0, 15), 6.0),   # outside
            (WTP, "ph", at(1, 0, 30), 9.0),   # outside
            (WTP, "ph", at(1, 0, 45), 20.6),  # a fault value: sanitize drops it before the band check
        ])
        self.assertEqual(metrics.ph_excursions(self.conn, WTP), [(at(1, 0, 15), 6.0), (at(1, 0, 30), 9.0)])

    def test_turbidity_spikes_against_the_sites_own_baseline(self):
        # alternating values so the baseline has a genuine (nonzero) spread for the median/MAD calculation
        baseline = [("Downstream", "turbidity", at(1, i), 1.0 if i % 2 else 2.0) for i in range(20)]
        spike = [("Downstream", "turbidity", at(1, 20), 500.0)]
        self.seed(baseline + spike)
        spikes = metrics.turbidity_spikes(self.conn, "Downstream")
        self.assertEqual([(t, v) for t, v, _ in spikes], [(at(1, 20), 500.0)])

    def test_turbidity_spikes_empty_when_baseline_has_no_spread(self):
        self.seed([("Downstream", "turbidity", at(1, i), 1.0) for i in range(5)])
        self.assertEqual(metrics.turbidity_spikes(self.conn, "Downstream"), [])

    def test_flagged_periods_merges_nearby_elevated_readings(self):
        readings = []
        for i, ratio_values in enumerate([(100.0, 350.0), (100.0, 320.0)]):  # 3.5x, 3.2x: both elevated
            up, down = ratio_values
            when = at(1, 0, 15 * i)
            readings += [("Upstream", "specific_conductivity", when, up),
                         ("Downstream", "specific_conductivity", when, down)]
        self.seed(readings)
        periods = metrics.flagged_periods(self.conn)
        self.assertEqual(len(periods), 1)
        self.assertEqual((periods[0].start, periods[0].end), (at(1, 0, 0), at(1, 0, 15)))
        self.assertAlmostEqual(periods[0].peak_ratio, 3.5)

    def test_flagged_periods_splits_readings_far_apart(self):
        readings = []
        for day, (up, down) in [(1, (100.0, 350.0)), (5, (100.0, 350.0))]:  # more than the merge gap apart
            readings += [("Upstream", "specific_conductivity", at(day), up),
                         ("Downstream", "specific_conductivity", at(day), down)]
        self.seed(readings)
        self.assertEqual(len(metrics.flagged_periods(self.conn)), 2)

    def test_flagged_periods_confidence_tiers(self):
        # high: alert-level ratio, corroborated by a Downstream turbidity spike at the same time
        baseline = [("Downstream", "turbidity", at(1, i), 1.0 if i % 2 else 2.0) for i in range(20)]
        high = [("Upstream", "specific_conductivity", at(1, 20), 100.0),
                ("Downstream", "specific_conductivity", at(1, 20), 900.0),   # 9x: above the alert threshold
                ("Downstream", "turbidity", at(1, 20), 500.0)]               # corroborating spike
        # medium: alert-level ratio alone, no corroboration
        medium = [("Upstream", "specific_conductivity", at(2), 100.0),
                  ("Downstream", "specific_conductivity", at(2), 900.0)]
        # low: elevated but below alert, no corroboration
        low = [("Upstream", "specific_conductivity", at(3), 100.0),
               ("Downstream", "specific_conductivity", at(3), 350.0)]        # 3.5x: elevated, not alert
        self.seed(baseline + high + medium + low)
        by_start = {p.start: p for p in metrics.flagged_periods(self.conn)}
        self.assertEqual(by_start[at(1, 20)].confidence, "high")
        self.assertEqual(by_start[at(1, 20)].corroborated_by, ["turbidity"])
        self.assertEqual(by_start[at(2)].confidence, "medium")
        self.assertEqual(by_start[at(3)].confidence, "low")

    def test_chronic_trend_daily_median_and_rolling_window(self):
        readings = []
        for day, ratio in [(1, 2.0), (2, 4.0), (3, 6.0)]:
            readings += [("Upstream", "specific_conductivity", at(day), 100.0),
                         ("Downstream", "specific_conductivity", at(day), 100.0 * ratio)]
        self.seed(readings)
        trend = metrics.chronic_trend(self.conn)
        self.assertEqual([daily for _, daily, _ in trend], [2.0, 4.0, 6.0])
        self.assertEqual([rolling for _, _, rolling in trend], [2.0, 3.0, 4.0])  # median of the days seen so far

    def test_data_health_completeness_and_gaps(self):
        self.seed([
            ("Downstream", "ph", at(1, 0), 7.0),
            ("Downstream", "ph", at(1, 1), None),                       # null: counts as a record, not sanitized
            ("Downstream", "ph", at(1, 0 + config.GAP_HOURS + 1), 7.1),  # a gap of more than GAP_HOURS before this
        ])
        health = metrics.data_health(self.conn)["Downstream"]
        self.assertEqual(health["total"], 3)
        self.assertEqual(health["valid"], 2)
        self.assertEqual(len(health["gaps"]), 1)

    def test_write_summary_is_valid_json_with_the_expected_keys(self):
        self.seed([("Upstream", "specific_conductivity", at(1), 200.0),
                   ("Downstream", "specific_conductivity", at(1), 400.0)])
        path = metrics.write_summary(self.conn, self.folder, now=1700000000)
        self.assertEqual(path.name, "metrics.json")
        data = json.loads(path.read_text())
        self.assertEqual(data["generated_at"], 1700000000)
        self.assertEqual(set(data), {"generated_at", "conductivity_ratio", "sites", "chronic_trend",
                                      "flagged_periods", "data_health"})

    def test_a_failed_write_keeps_the_previous_file(self):
        self.seed([("Upstream", "specific_conductivity", at(1), 200.0),
                   ("Downstream", "specific_conductivity", at(1), 400.0)])
        path = metrics.write_summary(self.conn, self.folder, now=1)
        before = path.read_text()
        with mock.patch("extractor.metrics.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                metrics.write_summary(self.conn, self.folder, now=2)
        self.assertEqual(path.read_text(), before)
        self.assertEqual([p.name for p in self.folder.iterdir()], ["metrics.json"])  # no temporary file left


if __name__ == "__main__":
    unittest.main()
