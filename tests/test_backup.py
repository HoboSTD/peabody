"""Tests for backups and retention (README: Backups and restore)."""
import gzip
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from extractor import backup, store

SYDNEY = ZoneInfo("Australia/Sydney")
NOW = datetime(2026, 9, 27, 21, 30, tzinfo=SYDNEY)
READINGS = [("Downstream", "ph", 1_790_236_800 + 900 * i, 7.0 + i / 100) for i in range(10)] + \
           [("Downstream", "turbidity", 1_790_236_800, None)]


def restore(backup_path, db_path):
    """What the README says to do: gunzip -c backups/<file>.db.gz > data/readings.db"""
    with gzip.open(backup_path, "rb") as src:
        db_path.write_bytes(src.read())


class BackupTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.folder = self.dir / "backups"
        self.conn = store.connect(self.dir / "readings.db")
        self.addCleanup(self.conn.close)

    def rows(self, conn):
        return conn.execute("SELECT * FROM readings ORDER BY site, parameter, ts").fetchall()

    def test_daily_backup_restores_to_the_same_data(self):
        store.upsert(self.conn, READINGS, now=1)
        path = backup.daily(self.conn, self.folder, now=NOW)
        self.assertEqual(path.name, "readings-2026-09-27.db.gz")
        restored = self.dir / "restored.db"
        restore(path, restored)
        other = sqlite3.connect(restored)
        self.addCleanup(other.close)
        self.assertEqual(self.rows(other), self.rows(self.conn))
        self.assertEqual(other.execute("PRAGMA integrity_check").fetchone(), ("ok",))

    def test_daily_backup_is_made_once_per_local_date(self):
        store.upsert(self.conn, READINGS, now=1)
        self.assertIsNotNone(backup.daily(self.conn, self.folder, now=NOW))
        self.assertIsNone(backup.daily(self.conn, self.folder, now=NOW + timedelta(hours=2)))  # 23:30, same day
        later = backup.daily(self.conn, self.folder, now=NOW + timedelta(hours=3))  # 00:30 the next day
        self.assertEqual(later.name, "readings-2026-09-28.db.gz")

    def test_uses_sydney_date_not_utc(self):
        store.upsert(self.conn, READINGS, now=1)
        utc_evening = datetime(2026, 9, 27, 20, 0, tzinfo=ZoneInfo("UTC"))  # already the 28th in Sydney
        path = backup.daily(self.conn, self.folder, now=utc_evening.astimezone(SYDNEY))
        self.assertEqual(path.name, "readings-2026-09-28.db.gz")

    def test_no_backup_of_an_empty_database(self):
        self.assertIsNone(backup.daily(self.conn, self.folder, now=NOW))
        self.assertIsNone(backup.before_backfill(self.conn, self.folder, now=NOW))
        self.assertFalse(self.folder.exists())

    def test_backfill_backup_is_always_made(self):
        store.upsert(self.conn, READINGS, now=1)
        backup.daily(self.conn, self.folder, now=NOW)
        path = backup.before_backfill(self.conn, self.folder, now=NOW)
        self.assertEqual(path.name, "readings-2026-09-27T2130-backfill.db.gz")
        self.assertEqual(len(list(self.folder.iterdir())), 2)  # no temporary files left behind

    def test_backup_leaves_no_file_if_it_fails(self):
        store.upsert(self.conn, READINGS, now=1)
        with mock.patch("shutil.copyfileobj", side_effect=OSError("disk full")):  # fails while compressing
            with self.assertRaises(OSError):
                backup.daily(self.conn, self.folder, now=NOW)
        self.assertEqual(list(self.folder.iterdir()), [])  # no partial backup or temporary files
        self.assertIsNotNone(backup.daily(self.conn, self.folder, now=NOW))  # and the next run retries


class PruneTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def make(self, *names):
        for name in names:
            (self.folder / name).write_bytes(b"")

    def remaining(self):
        return sorted(p.name for p in self.folder.iterdir())

    def test_keeps_last_7_days_and_earliest_of_each_month(self):
        today = date(2026, 9, 27)
        days = [today - timedelta(days=n) for n in range(100)]  # a daily backup for 100 days
        self.make(*(f"readings-{d}.db.gz" for d in days))
        self.make("readings-2026-08-10T0915-backfill.db.gz", "readings-2026-07-01T0800-backfill.db.gz")
        self.make("notes.txt", "readings.db.gz")  # not backups: never touched
        backup.prune(self.folder, today)
        self.assertEqual(self.remaining(), [
            "notes.txt",
            "readings-2026-06-20.db.gz",                # earliest in June (99 days ago)
            "readings-2026-07-01.db.gz",                # earliest in July (sorts before the backfill one)
            "readings-2026-08-01.db.gz",                # earliest in August
            "readings-2026-09-01.db.gz",                # earliest in September
            *(f"readings-2026-09-{d}.db.gz" for d in range(21, 28)),  # the last 7 days
            "readings.db.gz",
        ])

    def test_old_monthly_backups_are_kept_indefinitely(self):
        self.make("readings-2024-01-15.db.gz", "readings-2024-01-20.db.gz", "readings-2025-03-02.db.gz")
        backup.prune(self.folder, date(2026, 9, 27))
        self.assertEqual(self.remaining(), ["readings-2024-01-15.db.gz", "readings-2025-03-02.db.gz"])

    def test_running_again_changes_nothing(self):
        self.make(*(f"readings-2026-08-{d:02}.db.gz" for d in range(1, 32)))
        backup.prune(self.folder, date(2026, 9, 27))
        first = self.remaining()
        backup.prune(self.folder, date(2026, 9, 27))
        self.assertEqual(self.remaining(), first)
        self.assertEqual(first, ["readings-2026-08-01.db.gz"])


if __name__ == "__main__":
    unittest.main()
