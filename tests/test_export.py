"""Tests for the CSV exports (README: CSV output)."""
import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from extractor import export, store

WTP = "LDP7 Water Treatment Plant"


def ts(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())


class ExportTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name) / "output"
        self.conn = store.connect(Path(tmp.name) / "readings.db")
        self.addCleanup(self.conn.close)

    def write(self, site, readings=()):
        store.upsert(self.conn, readings, now=1)
        path, _ = export.write_site(self.conn, site, self.folder)
        with open(path, newline="", encoding="utf-8") as f:
            return path, list(csv.reader(f))

    def test_columns_and_file_names(self):
        path, rows = self.write("Upstream")
        self.assertEqual(path.name, "upstream.csv")
        self.assertEqual(rows, [["timestamp_utc", "timestamp_local", "ph", "specific_conductivity", "temperature",
                                 "turbidity"]])
        path, rows = self.write(WTP)
        self.assertEqual(path.name, "ldp7-water-treatment-plant.csv")
        self.assertEqual(rows[0][-1], "flow_volume")

    def test_rows_are_exactly_as_stored(self):
        _, rows = self.write(WTP, [
            (WTP, "ph", ts("2024-01-05 00:10:24"), 8.770000457763672),     # off the 15-minute grid: kept as is
            (WTP, "turbidity", ts("2024-01-05 00:10:24"), None),           # stored null
            (WTP, "flow_volume", ts("2024-01-05 00:15:00"), 18000.0),      # flow on its own timestamp
            (WTP, "ph", ts("2024-01-05 00:00:00"), 0.1 + 0.2),
            ("Upstream", "ph", ts("2024-01-05 00:05:00"), 7.0),            # another site: not in this file
        ])
        self.assertEqual(rows[1:], [
            ["2024-01-05T00:00:00Z", "2024-01-05T11:00:00+11:00", "0.30000000000000004", "", "", "", ""],
            ["2024-01-05T00:10:24Z", "2024-01-05T11:10:24+11:00", "8.770000457763672", "", "", "", ""],
            ["2024-01-05T00:15:00Z", "2024-01-05T11:15:00+11:00", "", "", "", "", "18000.0"],
        ])

    def test_local_time_across_daylight_saving_end(self):
        # Sydney clocks go back at 03:00 AEDT on 2024-04-07 (16:00 UTC on the 6th): 02:30 local happens twice
        _, rows = self.write("Downstream", [("Downstream", "ph", ts(t), 7.0)
                                            for t in ("2024-04-06 15:30:00", "2024-04-06 16:30:00")])
        self.assertEqual([r[1] for r in rows[1:]], ["2024-04-07T02:30:00+11:00", "2024-04-07T02:30:00+10:00"])

    def test_a_failed_write_keeps_the_previous_file(self):
        readings = [("Upstream", "ph", ts("2024-01-05 00:00:00"), 7.0)]
        path, before = self.write("Upstream", readings)
        with mock.patch("extractor.export.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.write("Upstream", [("Upstream", "ph", ts("2024-01-05 00:15:00"), 7.1)])
        with open(path, newline="", encoding="utf-8") as f:
            self.assertEqual(list(csv.reader(f)), before)
        self.assertEqual([p.name for p in self.folder.iterdir()], ["upstream.csv"])  # no temporary file left

    def test_write_all_writes_four_files(self):
        with self.assertLogs("extractor.export", "INFO"):
            export.write_all(self.conn, self.folder)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), [
            "downstream.csv", "ldp7-water-treatment-plant.csv", "ldp8-turkeys-nest.csv", "upstream.csv"])


if __name__ == "__main__":
    unittest.main()
